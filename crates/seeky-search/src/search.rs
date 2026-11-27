use crate::Result;
use seeky_core::SearchHit;
use seeky_store::{ChunkContext, SearchStore};
use std::collections::{HashMap, HashSet};

pub fn search(
    store: &dyn SearchStore,
    query: &str,
    query_vector: Option<&[f32]>,
    limit: usize,
) -> Result<Vec<SearchHit>> {
    let limit = limit.clamp(1, 50);
    let lexical = {
        let _span = tracing::info_span!("search.lexical", limit = 80_usize).entered();
        match fts_query(query) {
            Some(fts) => store.bm25(&fts, 80)?,
            None => Vec::new(),
        }
    };
    let semantic = match query_vector {
        Some(vector) => dense(store, vector, 80)?,
        None => Vec::new(),
    };
    let filename_ids = {
        let _span = tracing::info_span!("search.filename", limit = 40_usize).entered();
        store.filename_chunks(query, 40)?
    };

    let lexical_ids: Vec<i64> = lexical.iter().map(|(id, _)| *id).collect();
    let semantic_ids: Vec<i64> = semantic.iter().map(|(id, _)| *id).collect();
    let lexical_set: HashSet<i64> = lexical_ids.iter().copied().collect();
    let semantic_set: HashSet<i64> = semantic_ids.iter().copied().collect();
    let filename_set: HashSet<i64> = filename_ids.iter().copied().collect();

    let fused = {
        let _span = tracing::info_span!("search.fuse").entered();
        rrf(&[lexical_ids, semantic_ids, filename_ids], 60.0)
    };
    let mut top: Vec<(i64, f64)> = fused.into_iter().take(limit).collect();
    if top.is_empty() {
        return Ok(Vec::new());
    }
    let ids: Vec<i64> = top.iter().map(|(id, _)| *id).collect();
    let contexts = store.chunk_contexts(&ids)?;
    let by_id: HashMap<i64, ChunkContext> = contexts
        .into_iter()
        .map(|context| (context.chunk_id, context))
        .collect();

    let max_score = top
        .iter()
        .map(|(_, score)| *score)
        .fold(f64::MIN, f64::max)
        .max(1e-12);

    let _span = tracing::info_span!("search.snippets", results = top.len()).entered();
    let mut hits = Vec::new();
    for (id, score) in top.drain(..) {
        if let Some(context) = by_id.get(&id) {
            let mut matched = Vec::new();
            if lexical_set.contains(&id) {
                matched.push("bm25".to_string());
            }
            if semantic_set.contains(&id) {
                matched.push("semantic".to_string());
            }
            if filename_set.contains(&id) {
                matched.push("filename".to_string());
            }
            hits.push(SearchHit {
                chunk_id: context.chunk_id,
                doc_id: context.doc_id.clone(),
                title: context.title.clone(),
                path: context.path.clone(),
                ext: context.ext.clone(),
                snippet: snippet(&context.text, query),
                score: (score / max_score * 1000.0).round() / 1000.0,
                page: context.page,
                start: context.start,
                end: context.end,
                matched,
            });
        }
    }
    Ok(hits)
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

fn dense(store: &dyn SearchStore, query: &[f32], limit: usize) -> Result<Vec<(i64, f32)>> {
    let _span = tracing::info_span!("search.dense", limit).entered();
    if query.len() != seeky_infer::DIM {
        return Ok(Vec::new());
    }
    let mut scored = Vec::new();
    for (chunk_id, vector) in store.all_embeddings()? {
        if vector.len() != query.len() {
            continue;
        }
        let score: f32 = vector.iter().zip(query.iter()).map(|(a, b)| a * b).sum();
        scored.push((chunk_id, score));
    }
    scored.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
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
    result.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
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
