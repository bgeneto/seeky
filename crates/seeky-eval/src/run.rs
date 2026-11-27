//! TREC run interchange and deterministic chunk mapping (SPEC-0003 R5/R7).

use std::collections::{BTreeMap, BTreeSet};
use std::path::Path;

use crate::dataset::{Dataset, DocumentId, PassageId, QueryId};
use crate::error::{EvalError, Result, display_path};
use crate::util::read_utf8;

/// Document or canonical-passage target.
#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub enum RunTarget {
    /// A corpus document.
    Document(DocumentId),
    /// A canonical gold passage.
    Passage(PassageId),
}

impl RunTarget {
    /// Stable target ID as written to TREC.
    #[must_use]
    pub fn id(&self) -> &str {
        match self {
            Self::Document(id) | Self::Passage(id) => id,
        }
    }

    /// Whether this target is a passage.
    #[must_use]
    pub const fn is_passage(&self) -> bool {
        matches!(self, Self::Passage(_))
    }
}

/// One ranked result row.
#[derive(Clone, Debug)]
pub struct RunRow {
    /// Query ID.
    pub query_id: QueryId,
    /// Target.
    pub target: RunTarget,
    /// Contiguous rank starting at 1.
    pub rank: u32,
    /// Finite score; rank remains authoritative.
    pub score: f64,
}

/// A validated, homogeneous document or passage run.
#[derive(Clone, Debug)]
pub struct Run {
    /// TREC run ID.
    pub run_id: String,
    /// System identifier used in reports.
    pub system_id: String,
    /// Rows sorted by query ID and rank.
    pub rows: Vec<RunRow>,
}

/// One un-mapped engine chunk for canonical passage evaluation.
#[derive(Clone, Debug)]
pub struct ChunkHit {
    /// Query.
    pub query_id: QueryId,
    /// Document resolved from the engine path.
    pub document_id: DocumentId,
    /// Chunk start in Unicode scalar values.
    pub start_char: u64,
    /// Exclusive chunk end in Unicode scalar values.
    pub end_char: u64,
    /// Optional page.
    pub page: Option<u32>,
    /// Rank in the engine result list.
    pub rank: u32,
    /// Engine score.
    pub score: f64,
}

/// Result of mapping engine chunks to canonical passages.
#[derive(Clone, Debug)]
pub struct MappedChunkRun {
    /// Passage run, compacted after mapping and deduplication.
    pub run: Run,
    /// Chunks that intersected no canonical passage.
    pub unmapped_chunks: usize,
}

/// Read a TREC run and resolve every target against the dataset.
pub fn read_trec_run(path: &Path, dataset: &Dataset) -> Result<Run> {
    let content = read_utf8(path)?;
    let mut rows_by_query: BTreeMap<QueryId, Vec<(u32, RunTarget, f64)>> = BTreeMap::new();
    let mut run_id: Option<String> = None;
    let mut target_type: Option<bool> = None;
    for (index, line) in content.lines().enumerate() {
        let line_number = index + 1;
        let line = line.strip_suffix('\r').unwrap_or(line);
        if line.is_empty() {
            return Err(trec_error(path, line_number, "blank TREC line"));
        }
        let fields: Vec<_> = line.split(' ').collect();
        if fields.len() != 6 || fields.iter().any(|field| field.is_empty()) {
            return Err(trec_error(
                path,
                line_number,
                "expected exactly six single-space-separated columns",
            ));
        }
        let query_id = fields[0];
        if !valid_id(query_id) {
            return Err(trec_error(path, line_number, "invalid query ID"));
        }
        if !dataset.contains_query(query_id) {
            return Err(trec_error(
                path,
                line_number,
                "query is not in the selected split",
            ));
        }
        if fields[1] != "Q0" {
            return Err(trec_error(path, line_number, "second column must be Q0"));
        }
        let target_id = fields[2];
        if !valid_id(target_id) {
            return Err(trec_error(path, line_number, "invalid target ID"));
        }
        let is_passage = match (
            dataset.passage(target_id).is_some(),
            dataset.document(target_id).is_some(),
        ) {
            (true, true) => {
                return Err(trec_error(
                    path,
                    line_number,
                    "target ID is ambiguous between a document and a passage",
                ));
            }
            (true, false) => true,
            (false, true) => false,
            (false, false) => {
                return Err(trec_error(path, line_number, "unknown target ID"));
            }
        };
        if target_type.is_some_and(|existing| existing != is_passage) {
            return Err(trec_error(
                path,
                line_number,
                "run mixes document and passage targets",
            ));
        }
        target_type = Some(is_passage);
        let rank = fields[3]
            .parse::<u32>()
            .map_err(|_| trec_error(path, line_number, "rank is not an integer"))?;
        if !(1..=1000).contains(&rank) {
            return Err(trec_error(path, line_number, "rank must be in 1..=1000"));
        }
        let score = fields[4]
            .parse::<f64>()
            .map_err(|_| trec_error(path, line_number, "score is not a finite number"))?;
        if !score.is_finite() {
            return Err(trec_error(path, line_number, "score is not finite"));
        }
        let line_run_id = fields[5];
        if !valid_run_id(line_run_id) {
            return Err(trec_error(path, line_number, "invalid run ID"));
        }
        if run_id
            .as_deref()
            .is_some_and(|existing| existing != line_run_id)
        {
            return Err(trec_error(path, line_number, "run ID changes within file"));
        }
        run_id.get_or_insert_with(|| line_run_id.to_owned());
        let target = if is_passage {
            RunTarget::Passage(target_id.to_owned())
        } else {
            RunTarget::Document(target_id.to_owned())
        };
        rows_by_query
            .entry(query_id.to_owned())
            .or_default()
            .push((rank, target, score));
    }

    let mut rows = Vec::new();
    for (query_id, mut query_rows) in rows_by_query {
        query_rows.sort_by_key(|(rank, _, _)| *rank);
        let mut targets = BTreeSet::new();
        for (expected_rank, (rank, target, score)) in
            query_rows.into_iter().enumerate().map(|(index, row)| {
                let expected = u32::try_from(index + 1).unwrap_or(u32::MAX);
                (expected, row)
            })
        {
            if rank != expected_rank {
                return Err(EvalError::data(
                    "TREC",
                    display_path(path),
                    format!("ranks for {query_id} are not contiguous from 1"),
                ));
            }
            if !targets.insert(target.clone()) {
                return Err(EvalError::data(
                    "DUPLICATE_ID",
                    display_path(path),
                    format!("duplicate target for {query_id}"),
                ));
            }
            rows.push(RunRow {
                query_id: query_id.clone(),
                target,
                rank,
                score,
            });
        }
    }
    let run_id = run_id.unwrap_or_else(|| "empty-run".to_owned());
    Ok(Run {
        run_id,
        system_id: "trec-import".to_owned(),
        rows,
    })
}

/// Write a validated homogeneous TREC run atomically.
pub fn write_trec_run(run: &Run, path: &Path) -> Result<()> {
    validate_run(run)?;
    let mut output = String::new();
    let mut sorted = run.rows.clone();
    sorted.sort_by(|left, right| (&left.query_id, left.rank).cmp(&(&right.query_id, right.rank)));
    for row in sorted {
        output.push_str(&format!(
            "{} Q0 {} {} {} {}\n",
            row.query_id,
            row.target.id(),
            row.rank,
            format_score(row.score),
            run.run_id
        ));
    }
    let parent = path.parent().unwrap_or_else(|| Path::new("."));
    std::fs::create_dir_all(parent).map_err(|error| EvalError::io(parent, error))?;
    std::fs::write(path, output).map_err(|error| EvalError::io(path, error))
}

/// Map chunk hits to canonical passages, keeping the best rank per passage.
pub fn map_chunk_run(
    dataset: &Dataset,
    run_id: &str,
    system_id: &str,
    chunks: &[ChunkHit],
    limit: u32,
) -> Result<MappedChunkRun> {
    if !valid_run_id(run_id) {
        return Err(EvalError::data("SCHEMA", "run.run_id", "invalid run ID"));
    }
    let mut mapped: BTreeMap<(QueryId, PassageId), (u32, f64)> = BTreeMap::new();
    let mut unmapped_chunks = 0;
    for chunk in chunks {
        if !dataset.contains_query(&chunk.query_id) {
            return Err(EvalError::data(
                "DANGLING_REFERENCE",
                "chunk",
                "query is not in the selected split",
            ));
        }
        if !(1..=1000).contains(&chunk.rank) || !chunk.score.is_finite() {
            return Err(EvalError::data("SCHEMA", "chunk", "invalid rank or score"));
        }
        if let Some(passage) = dataset.map_chunk_to_passage(
            &chunk.document_id,
            chunk.start_char,
            chunk.end_char,
            chunk.page,
        )? {
            let key = (chunk.query_id.clone(), passage.id.clone());
            mapped
                .entry(key)
                .and_modify(|entry| {
                    if chunk.rank < entry.0 {
                        *entry = (chunk.rank, chunk.score);
                    }
                })
                .or_insert((chunk.rank, chunk.score));
        } else {
            unmapped_chunks += 1;
        }
    }
    let mut by_query: BTreeMap<QueryId, Vec<(u32, PassageId, f64)>> = BTreeMap::new();
    for ((query_id, passage_id), (rank, score)) in mapped {
        by_query
            .entry(query_id)
            .or_default()
            .push((rank, passage_id, score));
    }
    let mut rows = Vec::new();
    for (query_id, mut query_rows) in by_query {
        query_rows.sort_by_key(|(rank, _, _)| *rank);
        for (index, (_, passage_id, score)) in query_rows.into_iter().enumerate() {
            let rank = u32::try_from(index + 1).unwrap_or(u32::MAX);
            if rank > limit {
                break;
            }
            rows.push(RunRow {
                query_id: query_id.clone(),
                target: RunTarget::Passage(passage_id),
                rank,
                score,
            });
        }
    }
    let run = Run {
        run_id: run_id.to_owned(),
        system_id: system_id.to_owned(),
        rows,
    };
    validate_run(&run)?;
    Ok(MappedChunkRun {
        run,
        unmapped_chunks,
    })
}

fn validate_run(run: &Run) -> Result<()> {
    if !valid_run_id(&run.run_id) || run.system_id.trim().is_empty() {
        return Err(EvalError::data(
            "SCHEMA",
            "run",
            "run/system ID is empty or malformed",
        ));
    }
    let mut by_query: BTreeMap<&str, Vec<(&RunRow, RunTarget)>> = BTreeMap::new();
    let mut target_type = None;
    for row in &run.rows {
        if !valid_id(&row.query_id) || !valid_id(row.target.id()) {
            return Err(EvalError::data(
                "SCHEMA",
                "run",
                "invalid query or target ID",
            ));
        }
        if !row.score.is_finite() || !(1..=1000).contains(&row.rank) {
            return Err(EvalError::data(
                "SCHEMA",
                "run",
                "invalid rank or nonfinite score",
            ));
        }
        if target_type.is_some_and(|is_passage| is_passage != row.target.is_passage()) {
            return Err(EvalError::data(
                "SCHEMA",
                "run",
                "run mixes document and passage targets",
            ));
        }
        target_type = Some(row.target.is_passage());
        by_query
            .entry(row.query_id.as_str())
            .or_default()
            .push((row, row.target.clone()));
    }
    for (query_id, rows) in by_query {
        let mut targets = BTreeSet::new();
        let mut ranks: Vec<u32> = rows.iter().map(|(row, _)| row.rank).collect();
        ranks.sort_unstable();
        for (index, rank) in ranks.iter().enumerate() {
            if *rank != u32::try_from(index + 1).unwrap_or(u32::MAX) {
                return Err(EvalError::data(
                    "SCHEMA",
                    "run",
                    format!("ranks for {query_id} are not contiguous"),
                ));
            }
        }
        for (_, target) in rows {
            if !targets.insert(target) {
                return Err(EvalError::data(
                    "DUPLICATE_ID",
                    "run",
                    format!("duplicate target for {query_id}"),
                ));
            }
        }
    }
    Ok(())
}

fn trec_error(path: &Path, line: usize, message: impl Into<String>) -> EvalError {
    EvalError::data("TREC", format!("{}:{line}", display_path(path)), message)
}

fn valid_id(value: &str) -> bool {
    !value.is_empty()
        && !value
            .chars()
            .any(|character| character.is_whitespace() || character.is_control())
}

fn valid_run_id(value: &str) -> bool {
    let mut bytes = value.bytes();
    let Some(first) = bytes.next() else {
        return false;
    };
    if !first.is_ascii_alphanumeric() || value.len() > 64 {
        return false;
    }
    bytes.all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b'-'))
}

fn format_score(score: f64) -> String {
    format!("{score}")
}

#[cfg(test)]
mod tests {
    use std::io::Write as _;

    use tempfile::NamedTempFile;

    use super::*;
    use crate::dataset::{DatasetBuilder, LanguageSlice, QueryCategory, Split};

    fn fixture() -> Dataset {
        DatasetBuilder::new()
            .document("d1", "alpha beta gamma", false)
            .document("d2", "delta epsilon", false)
            .passage("d1:p:1", "d1", "alpha beta", "paragraph")
            .passage("d1:p:2", "d1", "gamma", "paragraph")
            .query(
                "q1",
                "alpha",
                QueryCategory::Conceptual,
                LanguageSlice::En,
                Split::Dev,
                crate::dataset::EvaluationConfiguration::Default,
            )
            .build()
    }

    #[test]
    fn trec_run_round_trip_preserves_rank_and_scores() {
        let dataset = fixture();
        let run = Run {
            run_id: "run-1".to_owned(),
            system_id: "system".to_owned(),
            rows: vec![
                RunRow {
                    query_id: "q1".to_owned(),
                    target: RunTarget::Document("d2".to_owned()),
                    rank: 1,
                    score: 1.25,
                },
                RunRow {
                    query_id: "q1".to_owned(),
                    target: RunTarget::Document("d1".to_owned()),
                    rank: 2,
                    score: 0.5,
                },
            ],
        };
        let mut file = NamedTempFile::new().unwrap();
        let path = file.path().to_path_buf();
        write_trec_run(&run, &path).unwrap();
        let reparsed = read_trec_run(&path, &dataset).unwrap();
        assert_eq!(reparsed.rows.len(), 2);
        assert_eq!(reparsed.rows[0].rank, 1);
        assert_eq!(reparsed.rows[1].score, 0.5);
        file.flush().unwrap();
    }

    #[test]
    fn trec_reader_rejects_duplicates_gaps_nonfinite_and_unknown_ids() {
        let dataset = fixture();
        let cases = [
            "q1 Q0 d1 1 1.0 r\nq1 Q0 d1 2 0.5 r\n",
            "q1 Q0 d1 1 1.0 r\nq1 Q0 d2 3 0.5 r\n",
            "q1 Q0 d1 1 NaN r\n",
            "q-unknown Q0 d1 1 1.0 r\n",
        ];
        for case in cases {
            let mut file = NamedTempFile::new().unwrap();
            file.write_all(case.as_bytes()).unwrap();
            assert!(read_trec_run(file.path(), &dataset).is_err(), "{case}");
        }
    }

    #[test]
    fn duplicate_targets_and_rank_gaps_are_rejected() {
        let dataset = fixture();
        let mut file = NamedTempFile::new().unwrap();
        file.write_all(b"q1 Q0 d1 1 1.0 r\nq1 Q0 d2 2 0.5 r\n")
            .unwrap();
        assert!(read_trec_run(file.path(), &dataset).is_ok());
        let mut gap = NamedTempFile::new().unwrap();
        gap.write_all(b"q1 Q0 d1 1 1.0 r\nq1 Q0 d2 3 0.5 r\n")
            .unwrap();
        assert!(read_trec_run(gap.path(), &dataset).is_err());
    }

    #[test]
    fn trec_rejects_mixed_target_types_and_run_ids() {
        let dataset = fixture();
        let mut mixed_type = NamedTempFile::new().unwrap();
        mixed_type
            .write_all(b"q1 Q0 d1 1 1.0 r\nq1 Q0 d1:p:1 2 0.5 r\n")
            .unwrap();
        assert!(read_trec_run(mixed_type.path(), &dataset).is_err());
        let mut mixed_run = NamedTempFile::new().unwrap();
        mixed_run
            .write_all(b"q1 Q0 d1 1 1.0 r1\nq1 Q0 d2 2 0.5 r2\n")
            .unwrap();
        assert!(read_trec_run(mixed_run.path(), &dataset).is_err());
    }

    #[test]
    fn duplicate_chunks_keep_best_passage_rank() {
        let dataset = fixture();
        let chunks = vec![
            ChunkHit {
                query_id: "q1".to_owned(),
                document_id: "d1".to_owned(),
                start_char: 0,
                end_char: 5,
                page: Some(1),
                rank: 3,
                score: 0.3,
            },
            ChunkHit {
                query_id: "q1".to_owned(),
                document_id: "d1".to_owned(),
                start_char: 0,
                end_char: 6,
                page: Some(1),
                rank: 1,
                score: 1.0,
            },
        ];
        let mapped = map_chunk_run(&dataset, "r", "s", &chunks, 10).unwrap();
        assert_eq!(mapped.run.rows.len(), 1);
        assert_eq!(mapped.run.rows[0].rank, 1);
        assert_eq!(mapped.run.rows[0].score, 1.0);
    }

    #[test]
    fn trec_reader_never_panics_on_arbitrary_bytes() {
        let dataset = fixture();
        let mut state = 0x1357_9bdf_u64;
        for index in 0..64 {
            let mut bytes = vec![b'x'];
            for _ in 0..(index * 11) {
                state = state
                    .wrapping_mul(6_364_136_223_846_793_005)
                    .wrapping_add(1);
                bytes.push((state >> 32) as u8);
            }
            let mut file = NamedTempFile::new().unwrap();
            file.write_all(&bytes).unwrap();
            assert!(read_trec_run(file.path(), &dataset).is_err());
        }
    }

    #[test]
    fn unmapped_chunks_are_counted() {
        let dataset = fixture();
        let chunks = vec![ChunkHit {
            query_id: "q1".to_owned(),
            document_id: "d2".to_owned(),
            start_char: 0,
            end_char: 4,
            page: None,
            rank: 1,
            score: 1.0,
        }];
        let mapped = map_chunk_run(&dataset, "r", "s", &chunks, 10).unwrap();
        assert_eq!(mapped.unmapped_chunks, 1);
        assert!(mapped.run.rows.is_empty());
    }
}
