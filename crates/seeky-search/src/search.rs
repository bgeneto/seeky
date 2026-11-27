use crate::{Error, Result};
use seeky_core::{
    CandidateDepths, DepthReport, DocumentMetadata, FilterApplication, FilterMode, FilterReport,
    FilterSupport, ResolvedFilter, SearchHit, SearchStage, StageTiming, document_matches,
};
use seeky_store::{ChunkContext, SearchStore};
use std::collections::{HashMap, HashSet};
use std::time::Instant;

/// One search pipeline invocation.
#[derive(Clone, Copy, Debug)]
pub struct SearchParameters<'a> {
    /// Query text.
    pub query: &'a str,
    /// Query embedding when the semantic channel runs.
    pub query_vector: Option<&'a [f32]>,
    /// Effective result depth; the caller has already applied the mode clamp
    /// or the evaluation bound.
    pub limit: usize,
    /// Candidate depth requested from each first-stage retriever.
    pub candidate_depths: CandidateDepths,
    /// Validated metadata filter.
    pub filter: Option<&'a ResolvedFilter>,
    /// Which retrievers can apply predicates before their candidate cap.
    pub filter_support: FilterSupport,
    /// Opt-in stage timings.
    pub telemetry: bool,
}

/// Pipeline output, including evaluation diagnostics.
#[derive(Clone, Debug)]
pub struct SearchResult {
    /// Ranked hits.
    pub hits: Vec<SearchHit>,
    /// Depth diagnostics.
    pub depth: DepthReport,
    /// Filter diagnostics when a filter was requested.
    pub filter: Option<FilterReport>,
    /// Stage timings in canonical order; empty unless telemetry was requested.
    pub stages: Vec<StageTiming>,
}

/// v1 signature: one blocking lexical/hybrid search, clamped to 1..=50.
pub fn search(
    store: &dyn SearchStore,
    query: &str,
    query_vector: Option<&[f32]>,
    limit: usize,
) -> Result<Vec<SearchHit>> {
    let limit = limit.clamp(1, 50);
    let candidate_depths = CandidateDepths {
        filename: 40,
        lexical: 80,
        dense: if query_vector.is_some() { 80 } else { 0 },
    };
    let result = search_with_store(
        store,
        &SearchParameters {
            query,
            query_vector,
            limit,
            candidate_depths,
            filter: None,
            filter_support: FilterSupport::FULL,
            telemetry: false,
        },
    )?;
    Ok(result.hits)
}

/// Evaluation pipeline with optional filters, telemetry, and depth reporting.
pub fn search_with_store(
    store: &dyn SearchStore,
    params: &SearchParameters<'_>,
) -> Result<SearchResult> {
    let limit = params.limit.max(1);
    let mut filter_depths = params.candidate_depths;
    if params.query_vector.is_none() {
        filter_depths.dense = 0;
    }

    // All-or-nothing pushdown: a predicate is pushed down only when every
    // enabled retriever supports it (SPEC-0002 section 9.4.4).
    let pushdown_filter = params.filter.filter(|filter| {
        !filter.is_empty()
            && filter
                .active_kinds()
                .iter()
                .all(|kind| params.filter_support.supports(*kind))
    });

    let mut stages = Vec::with_capacity(5);

    let started = Instant::now();
    let lexical = {
        let _span = tracing::info_span!("search.lexical", limit = filter_depths.lexical).entered();
        match fts_query(params.query) {
            Some(fts) => store.bm25_filtered(&fts, filter_depths.lexical, pushdown_filter)?,
            None => Vec::new(),
        }
    };
    record_stage(
        params.telemetry,
        &mut stages,
        SearchStage::Lexical,
        started,
        None,
        lexical.len(),
    );

    let started = Instant::now();
    let dense = match params.query_vector {
        Some(vector) => {
            let _span = tracing::info_span!("search.dense", limit = filter_depths.dense).entered();
            let allowed = match pushdown_filter {
                Some(filter) => Some(
                    store
                        .chunk_ids_matching(filter)?
                        .into_iter()
                        .collect::<HashSet<i64>>(),
                ),
                None => None,
            };
            dense(store, vector, filter_depths.dense, allowed.as_ref())?
        }
        None => Vec::new(),
    };
    if params.query_vector.is_some() {
        record_stage(
            params.telemetry,
            &mut stages,
            SearchStage::Dense,
            started,
            None,
            dense.len(),
        );
    }

    let started = Instant::now();
    let filename = {
        let _span =
            tracing::info_span!("search.filename", limit = filter_depths.filename).entered();
        store.filename_chunks_filtered(params.query, filter_depths.filename, pushdown_filter)?
    };
    record_stage(
        params.telemetry,
        &mut stages,
        SearchStage::Filename,
        started,
        None,
        filename.len(),
    );

    let lexical_ids: Vec<i64> = lexical.iter().map(|(id, _)| *id).collect();
    let semantic_ids: Vec<i64> = dense.iter().map(|(id, _)| *id).collect();
    let lexical_set: HashSet<i64> = lexical_ids.iter().copied().collect();
    let semantic_set: HashSet<i64> = semantic_ids.iter().copied().collect();
    let filename_set: HashSet<i64> = filename.iter().copied().collect();
    let candidates_in = lexical_ids.len() + semantic_ids.len() + filename.len();
    let candidate_cap_reached = cap_reached(
        &filter_depths,
        params.query_vector,
        &lexical,
        &dense,
        &filename,
    );

    let started = Instant::now();
    let fused = {
        let _span = tracing::info_span!("search.fuse").entered();
        rrf(&[lexical_ids, semantic_ids, filename], 60.0)
    };
    let pool_len = fused.len();
    let post_filtering = params.filter.is_some() && pushdown_filter.is_none();

    let mut filter_report = None;
    let mut top: Vec<(ChunkContext, f64)> = Vec::new();
    let mut examined = pool_len;
    let mut matched = pool_len;
    if !fused.is_empty() {
        // Post filtering must see the complete pool; every other path only
        // needs the response depth, so the interactive cost is unchanged.
        let fetch = if post_filtering {
            pool_len
        } else {
            pool_len.min(limit)
        };
        let ids: Vec<i64> = fused[..fetch].iter().map(|(id, _)| *id).collect();
        let contexts = store.chunk_contexts(&ids)?;
        let by_id: HashMap<i64, ChunkContext> = contexts
            .into_iter()
            .map(|context| (context.chunk_id, context))
            .collect();
        let mut candidates: Vec<(ChunkContext, f64)> = Vec::new();
        for (id, score) in &fused[..fetch] {
            if let Some(context) = by_id.get(id) {
                candidates.push((context.clone(), *score));
            }
        }

        let survivors = match params.filter {
            Some(filter) if post_filtering => {
                let survivors: Vec<(ChunkContext, f64)> = candidates
                    .into_iter()
                    .filter(|(context, _)| context_matches(filter, context))
                    .collect();
                examined = pool_len;
                matched = survivors.len();
                survivors
            }
            _ => candidates,
        };
        top = survivors.into_iter().take(limit).collect();
    }
    if params.filter.is_some() {
        let mode = if pushdown_filter.is_some() {
            FilterMode::Pushdown
        } else {
            FilterMode::Post
        };
        let applications = params
            .filter
            .map(|filter| {
                filter
                    .active_kinds()
                    .into_iter()
                    .map(|kind| FilterApplication { kind, mode })
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default();
        let returned = matched.min(limit);
        filter_report = Some(FilterReport {
            mode,
            applications,
            examined,
            matched,
            returned,
            possibly_incomplete: candidate_cap_reached && matched < limit,
        });
    }
    record_stage(
        params.telemetry,
        &mut stages,
        SearchStage::Fuse,
        started,
        Some(candidates_in),
        top.len(),
    );

    let started = Instant::now();
    let mut hits: Vec<SearchHit> = Vec::with_capacity(top.len());
    let selected = top.len();
    if !top.is_empty() {
        let _span = tracing::info_span!("search.snippets", results = top.len()).entered();
        let max_score = top
            .iter()
            .map(|(_, score)| *score)
            .fold(f64::MIN, f64::max)
            .max(1e-12);
        for (context, score) in top {
            let mut matched = Vec::new();
            if lexical_set.contains(&context.chunk_id) {
                matched.push("bm25".to_string());
            }
            if semantic_set.contains(&context.chunk_id) {
                matched.push("semantic".to_string());
            }
            if filename_set.contains(&context.chunk_id) {
                matched.push("filename".to_string());
            }
            let score = (score / max_score * 1000.0).round() / 1000.0;
            if !score.is_finite() {
                return Err(Error::Internal("non-finite search score".into()));
            }
            hits.push(SearchHit {
                chunk_id: context.chunk_id,
                doc_id: context.doc_id.clone(),
                title: context.title.clone(),
                path: context.path.clone(),
                ext: context.ext.clone(),
                snippet: snippet(&context.text, params.query),
                score,
                page: context.page,
                start: context.start,
                end: context.end,
                matched,
            });
        }
        hits.sort_by(rank_hits);
        for hit in &hits {
            if !hit.score.is_finite() {
                return Err(Error::Internal("non-finite search score".into()));
            }
        }
    }
    if selected > 0 {
        record_stage(
            params.telemetry,
            &mut stages,
            SearchStage::Snippets,
            started,
            Some(selected),
            hits.len(),
        );
    }

    let mut distinct_documents = std::collections::HashSet::with_capacity(hits.len());
    for hit in &hits {
        distinct_documents.insert(hit.doc_id.as_str());
    }
    let depth = DepthReport {
        requested_hits: limit,
        returned_hits: hits.len(),
        distinct_documents: distinct_documents.len(),
        candidate_depths: filter_depths,
        candidate_cap_reached,
    };
    if params.telemetry {
        stages.sort_by_key(|timing| timing.stage as u8);
    }
    Ok(SearchResult {
        hits,
        depth,
        filter: filter_report,
        stages,
    })
}

fn cap_reached(
    depths: &CandidateDepths,
    query_vector: Option<&[f32]>,
    lexical: &[(i64, f64)],
    dense: &[(i64, f32)],
    filename: &[i64],
) -> bool {
    let lexical_capped = depths.lexical > 0 && lexical.len() == depths.lexical;
    let dense_capped = query_vector.is_some() && depths.dense > 0 && dense.len() == depths.dense;
    let filename_capped = depths.filename > 0 && filename.len() == depths.filename;
    lexical_capped || dense_capped || filename_capped
}

fn context_matches(filter: &ResolvedFilter, context: &ChunkContext) -> bool {
    document_matches(
        filter,
        &DocumentMetadata {
            ext: &context.ext,
            size: context.size,
            modified_ns: context.modified_ns,
            path: &context.path,
        },
    )
}

fn record_stage(
    telemetry: bool,
    stages: &mut Vec<StageTiming>,
    stage: SearchStage,
    started: Instant,
    items_in: Option<usize>,
    items_out: usize,
) {
    if !telemetry {
        return;
    }
    stages.push(StageTiming {
        stage,
        duration_ns: started.elapsed().as_nanos().min(u64::MAX as u128) as u64,
        items_in: items_in.map(|value| value as u64),
        items_out: Some(items_out as u64),
    });
}

/// Deterministic total order over response hits (SPEC-0002 R18).
fn rank_hits(left: &SearchHit, right: &SearchHit) -> std::cmp::Ordering {
    right
        .score
        .partial_cmp(&left.score)
        .unwrap_or(std::cmp::Ordering::Equal)
        .then_with(|| left.doc_id.cmp(&right.doc_id))
        .then_with(|| left.start.cmp(&right.start))
        .then_with(|| left.end.cmp(&right.end))
        .then_with(|| left.chunk_id.cmp(&right.chunk_id))
}

fn fts_query(query: &str) -> Option<String> {
    let mut terms = Vec::new();
    for token in query.split(|c: char| !c.is_alphanumeric()) {
        let token = token.trim();
        if token.chars().count() >= 2 {
            terms.push(format!("\"{}\"*", token.replace('"', "")));
        }
    }
    terms.dedup();
    if terms.is_empty() {
        None
    } else {
        Some(terms.join(" OR "))
    }
}

fn dense(
    store: &dyn SearchStore,
    query: &[f32],
    limit: usize,
    allowed: Option<&HashSet<i64>>,
) -> Result<Vec<(i64, f32)>> {
    if query.len() != seeky_infer::DIM {
        return Ok(Vec::new());
    }
    let mut scored = Vec::new();
    for (chunk_id, vector) in store.all_embeddings()? {
        if vector.len() != query.len() {
            continue;
        }
        if let Some(allowed) = allowed
            && !allowed.contains(&chunk_id)
        {
            continue;
        }
        let score: f32 = vector.iter().zip(query.iter()).map(|(a, b)| a * b).sum();
        if !score.is_finite() {
            return Err(Error::Internal("non-finite dense score".into()));
        }
        scored.push((chunk_id, score));
    }
    scored.sort_by(|left, right| {
        right
            .1
            .total_cmp(&left.1)
            .then_with(|| left.0.cmp(&right.0))
    });
    scored.truncate(limit);
    Ok(scored)
}

fn rrf(rankings: &[Vec<i64>], k: f64) -> Vec<(i64, f64)> {
    let mut scores: HashMap<i64, f64> = HashMap::new();
    for ranking in rankings {
        for (index, id) in ranking.iter().enumerate() {
            *scores.entry(*id).or_insert(0.0) += 1.0 / (k + (index as f64) + 1.0);
        }
    }
    let mut result: Vec<(i64, f64)> = scores.into_iter().collect();
    result.sort_by(|left, right| {
        right
            .1
            .partial_cmp(&left.1)
            .unwrap_or(std::cmp::Ordering::Equal)
            .then_with(|| left.0.cmp(&right.0))
    });
    result
}

fn snippet(text: &str, query: &str) -> String {
    let clean = text.split_whitespace().collect::<Vec<_>>().join(" ");
    if clean.chars().count() <= 320 {
        return clean;
    }
    let lower = clean.to_lowercase();
    let needle = query
        .split_whitespace()
        .find(|t| t.len() >= 3)
        .map(str::to_lowercase);
    if let Some(needle) = needle
        && let Some(byte_pos) = lower.find(&needle)
    {
        let char_pos = lower[..byte_pos].chars().count();
        let start = char_pos.saturating_sub(80);
        let snippet: String = clean.chars().skip(start).take(320).collect();
        return format!("…{}…", snippet.trim());
    }
    format!("{}…", clean.chars().take(320).collect::<String>())
}

#[cfg(test)]
mod tests {
    use super::*;
    use seeky_core::FilterKind;

    /// In-memory store with full metadata, used for pipeline property tests.
    struct FakeStore {
        chunks: Vec<ChunkContext>,
        lexical: Vec<(i64, f64)>,
        filename: Vec<i64>,
        embeddings: Vec<(i64, Vec<f32>)>,
        supports_pushdown: bool,
    }

    impl SearchStore for FakeStore {
        fn all_embeddings(&self) -> seeky_store::Result<Vec<(i64, Vec<f32>)>> {
            Ok(self.embeddings.clone())
        }

        fn bm25(&self, _query: &str, limit: usize) -> seeky_store::Result<Vec<(i64, f64)>> {
            Ok(self.lexical.iter().copied().take(limit).collect())
        }

        fn filename_chunks(&self, _query: &str, limit: usize) -> seeky_store::Result<Vec<i64>> {
            Ok(self.filename.iter().copied().take(limit).collect())
        }

        fn chunk_contexts(&self, ids: &[i64]) -> seeky_store::Result<Vec<ChunkContext>> {
            Ok(ids
                .iter()
                .filter_map(|id| {
                    self.chunks
                        .iter()
                        .find(|chunk| chunk.chunk_id == *id)
                        .cloned()
                })
                .collect())
        }

        fn bm25_filtered(
            &self,
            _query: &str,
            limit: usize,
            filter: Option<&ResolvedFilter>,
        ) -> seeky_store::Result<Vec<(i64, f64)>> {
            Ok(self
                .lexical
                .iter()
                .copied()
                .filter(|(id, _)| match filter {
                    Some(filter) if self.supports_pushdown => self
                        .chunks
                        .iter()
                        .find(|chunk| chunk.chunk_id == *id)
                        .is_some_and(|chunk| context_matches(filter, chunk)),
                    _ => true,
                })
                .take(limit)
                .collect())
        }

        fn filename_chunks_filtered(
            &self,
            _query: &str,
            limit: usize,
            filter: Option<&ResolvedFilter>,
        ) -> seeky_store::Result<Vec<i64>> {
            Ok(self
                .filename
                .iter()
                .copied()
                .filter(|id| match filter {
                    Some(filter) if self.supports_pushdown => self
                        .chunks
                        .iter()
                        .find(|chunk| chunk.chunk_id == *id)
                        .is_some_and(|chunk| context_matches(filter, chunk)),
                    _ => true,
                })
                .take(limit)
                .collect())
        }

        fn chunk_ids_matching(&self, filter: &ResolvedFilter) -> seeky_store::Result<Vec<i64>> {
            Ok(self
                .chunks
                .iter()
                .filter(|chunk| context_matches(filter, chunk))
                .map(|chunk| chunk.chunk_id)
                .collect())
        }

        fn missing_filter_metadata(
            &self,
            _filter: &ResolvedFilter,
        ) -> seeky_store::Result<Option<&'static str>> {
            Ok(None)
        }
    }

    fn context(chunk_id: i64, doc: &str, start: i64, end: i64, ext: &str) -> ChunkContext {
        ChunkContext {
            chunk_id,
            doc_id: doc.into(),
            title: doc.into(),
            path: format!("C:/corpus/{doc}.{ext}"),
            ext: ext.into(),
            text: format!("chunk {chunk_id} text"),
            page: None,
            start,
            end,
            size: 100,
            modified_ns: 1_000,
        }
    }

    #[test]
    fn equal_scores_order_by_document_then_offsets() {
        // SPEC-0002-R18
        let chunks = vec![
            context(2, "a", 0, 10, "txt"),
            context(6, "c", 0, 10, "txt"),
            context(5, "c", 5, 15, "txt"),
        ];
        let store = FakeStore {
            chunks,
            // One rank-0 candidate per channel: all three fuse to 1/61.
            lexical: vec![(5, -1.0)],
            filename: vec![2],
            embeddings: vec![(6, vec![1.0; seeky_infer::DIM])],
            supports_pushdown: true,
        };
        let query_vector = vec![1.0_f32; seeky_infer::DIM];
        let result = search_with_store(
            &store,
            &SearchParameters {
                query: "same",
                query_vector: Some(&query_vector),
                limit: 10,
                candidate_depths: CandidateDepths {
                    filename: 40,
                    lexical: 80,
                    dense: 80,
                },
                filter: None,
                filter_support: FilterSupport::FULL,
                telemetry: false,
            },
        )
        .expect("search");
        let order: Vec<(&str, i64)> = result
            .hits
            .iter()
            .map(|hit| (hit.doc_id.as_str(), hit.start))
            .collect();
        // Document ascending, then chunk start ascending for the tie.
        assert_eq!(order, vec![("a", 0), ("c", 0), ("c", 5)]);
    }

    #[test]
    fn post_filter_examines_pool_before_limit_truncation() {
        // SPEC-0002-R22
        let chunks: Vec<ChunkContext> = (1..=10)
            .map(|id| {
                context(
                    id,
                    &format!("doc{id:02}"),
                    0,
                    10,
                    if id % 2 == 0 { "txt" } else { "md" },
                )
            })
            .collect();
        let store = FakeStore {
            chunks,
            lexical: (1..=10).map(|id| (id, -(id as f64))).collect(),
            filename: vec![],
            embeddings: vec![],
            supports_pushdown: false,
        };
        let filter = ResolvedFilter {
            extensions: vec!["txt".into()],
            ..ResolvedFilter::default()
        };
        let result = search_with_store(
            &store,
            &SearchParameters {
                query: "any",
                query_vector: None,
                limit: 2,
                candidate_depths: CandidateDepths {
                    filename: 40,
                    lexical: 80,
                    dense: 0,
                },
                filter: Some(&filter),
                filter_support: FilterSupport::NONE,
                telemetry: false,
            },
        )
        .expect("search");
        let report = result.filter.expect("filter report");
        assert_eq!(report.mode, FilterMode::Post);
        assert_eq!(report.examined, 10);
        assert_eq!(report.matched, 5);
        assert_eq!(report.returned, 2);
        // Survivors keep the unfiltered ranking order: doc02 then doc04.
        let ids: Vec<&str> = result.hits.iter().map(|hit| hit.doc_id.as_str()).collect();
        assert_eq!(ids, vec!["doc02", "doc04"]);
    }

    #[test]
    fn post_filter_at_configured_depth_is_possibly_incomplete() {
        // SPEC-0002-R22
        let chunks: Vec<ChunkContext> = (1..=4)
            .map(|id| {
                context(
                    id,
                    &format!("doc{id:02}"),
                    0,
                    10,
                    if id == 1 { "txt" } else { "md" },
                )
            })
            .collect();
        let store = FakeStore {
            chunks,
            lexical: (1..=4).map(|id| (id, -(id as f64))).collect(),
            filename: vec![],
            embeddings: vec![],
            supports_pushdown: false,
        };
        let filter = ResolvedFilter {
            extensions: vec!["txt".into()],
            ..ResolvedFilter::default()
        };
        let result = search_with_store(
            &store,
            &SearchParameters {
                query: "any",
                query_vector: None,
                limit: 4,
                candidate_depths: CandidateDepths {
                    filename: 40,
                    lexical: 4,
                    dense: 0,
                },
                filter: Some(&filter),
                filter_support: FilterSupport::NONE,
                telemetry: false,
            },
        )
        .expect("search");
        let report = result.filter.expect("filter report");
        assert_eq!(report.returned, 1);
        // The cap was reached and the filter matched only one candidate.
        assert!(result.depth.candidate_cap_reached);
        assert!(report.possibly_incomplete);
    }

    #[test]
    fn filter_report_records_pushdown_mode_per_predicate() {
        // SPEC-0002-R22
        let chunks = vec![context(1, "a", 0, 10, "txt")];
        let store = FakeStore {
            chunks,
            lexical: vec![(1, -1.0)],
            filename: vec![],
            embeddings: vec![],
            supports_pushdown: true,
        };
        let filter = ResolvedFilter {
            extensions: vec!["txt".into()],
            modified_after_ns: Some(0),
            ..ResolvedFilter::default()
        };
        let result = search_with_store(
            &store,
            &SearchParameters {
                query: "any",
                query_vector: None,
                limit: 10,
                candidate_depths: CandidateDepths {
                    filename: 40,
                    lexical: 80,
                    dense: 0,
                },
                filter: Some(&filter),
                filter_support: FilterSupport::FULL,
                telemetry: false,
            },
        )
        .expect("search");
        let report = result.filter.expect("filter report");
        assert_eq!(report.mode, FilterMode::Pushdown);
        assert_eq!(
            report.applications,
            vec![
                FilterApplication {
                    kind: FilterKind::Extension,
                    mode: FilterMode::Pushdown,
                },
                FilterApplication {
                    kind: FilterKind::Modified,
                    mode: FilterMode::Pushdown,
                },
            ]
        );
        assert_eq!(report.examined, report.matched);
        assert!(!report.possibly_incomplete);
    }

    /// Property (SPEC-0002-R18): the fused ranking does not depend on the
    /// order in which the store yields its candidates.
    #[test]
    fn candidate_insertion_order_does_not_change_ranking() {
        let ids = [7_i64, 3, 9, 1, 5];
        let contexts: Vec<ChunkContext> = ids
            .iter()
            .map(|id| context(*id, &format!("doc{id}"), 0, 10, "txt"))
            .collect();
        let query_vector = vec![1.0_f32; seeky_infer::DIM];
        let mut previous: Option<Vec<(i64, f64)>> = None;
        for reversed in [false, true] {
            let mut embeddings: Vec<(i64, Vec<f32>)> = ids
                .iter()
                .map(|id| (*id, vec![1.0_f32; seeky_infer::DIM]))
                .collect();
            if reversed {
                embeddings.reverse();
            }
            let store = FakeStore {
                chunks: contexts.clone(),
                lexical: vec![],
                filename: vec![],
                embeddings,
                supports_pushdown: true,
            };
            let result = search_with_store(
                &store,
                &SearchParameters {
                    query: "any",
                    query_vector: Some(&query_vector),
                    limit: 10,
                    candidate_depths: CandidateDepths {
                        filename: 40,
                        lexical: 80,
                        dense: 80,
                    },
                    filter: None,
                    filter_support: FilterSupport::FULL,
                    telemetry: false,
                },
            )
            .expect("search");
            let ranking: Vec<(i64, f64)> = result
                .hits
                .iter()
                .map(|hit| (hit.chunk_id, hit.score))
                .collect();
            if let Some(previous) = &previous {
                assert_eq!(previous, &ranking);
            }
            previous = Some(ranking);
        }
    }

    #[test]
    fn empty_store_returns_empty_result() {
        let store = FakeStore {
            chunks: vec![],
            lexical: vec![],
            filename: vec![],
            embeddings: vec![],
            supports_pushdown: true,
        };
        let result = search_with_store(
            &store,
            &SearchParameters {
                query: "none",
                query_vector: None,
                limit: 20,
                candidate_depths: CandidateDepths {
                    filename: 40,
                    lexical: 80,
                    dense: 0,
                },
                filter: None,
                filter_support: FilterSupport::FULL,
                telemetry: true,
            },
        )
        .expect("search");
        assert!(result.hits.is_empty());
        assert_eq!(result.depth.returned_hits, 0);
        assert_eq!(result.stages.len(), 3);
    }
}
