//! Evaluation-only search surface (SPEC-0002 v1.1, section 9).
//!
//! These types are additive: the v1 request, response, and hit shapes are
//! unchanged. They describe evaluation depth, deterministic ordering,
//! in-process telemetry, structured metadata filters, and the query-embedding
//! probe used by `seeky-bench`.

use crate::RootId;
use serde::Serialize;

/// Search semantics. `Interactive` is the v1 product path; `Evaluation` is the
/// v1.1 benchmark path with a wider depth and structured filters.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub enum SearchMode {
    /// v1 semantics, including the 1..=50 depth clamp.
    #[default]
    Interactive,
    /// v1.1 evaluation depth and filters.
    Evaluation,
}

/// Per-request evaluation options. Defaults to v1 behavior.
#[derive(Clone, Debug, Default)]
pub struct SearchOptions {
    /// Requested semantics.
    pub mode: SearchMode,
    /// Structured metadata filter; valid only with `SearchMode::Evaluation`.
    pub filters: Option<MetadataFilter>,
    /// Opt-in in-process stage timings.
    pub telemetry: bool,
}

/// One evaluation search: the v1-shaped response plus diagnostics.
#[derive(Clone, Debug)]
pub struct SearchOutcome {
    /// v1 response shape, unchanged.
    pub response: crate::SearchResponse,
    /// Depth and candidate diagnostics.
    pub depth: DepthReport,
    /// Filter diagnostics when a filter was requested.
    pub filter: Option<FilterReport>,
    /// Stage timings when telemetry was requested.
    pub telemetry: Option<SearchTelemetry>,
}

/// Requested candidate depth per first-stage retriever; 0 means disabled.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize)]
pub struct CandidateDepths {
    /// Filename retriever candidates.
    pub filename: usize,
    /// Lexical (FTS5/BM25) retriever candidates.
    pub lexical: usize,
    /// Dense retriever candidates.
    pub dense: usize,
}

/// How deep the result actually was.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize)]
pub struct DepthReport {
    /// Effective requested depth after mode clamping.
    pub requested_hits: usize,
    /// Hits returned.
    pub returned_hits: usize,
    /// Unique document IDs among the returned hits.
    pub distinct_documents: usize,
    /// Requested candidate depth per retriever.
    pub candidate_depths: CandidateDepths,
    /// True when a retriever hit its candidate cap or the ranked pool was
    /// truncated before the final response.
    pub candidate_cap_reached: bool,
}

/// Structured metadata predicates (SPEC-0002 section 9.4.3).
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct MetadataFilter {
    /// Exact extensions, ORed, lowercase without a leading dot. Empty means no
    /// extension constraint.
    pub extensions: Vec<String>,
    /// Inclusive lower bound on the indexed modified time, UTC nanoseconds.
    pub modified_after_ns: Option<i64>,
    /// Exclusive upper bound on the indexed modified time, UTC nanoseconds.
    pub modified_before_ns: Option<i64>,
    /// Root-scoped, corpus-relative folder prefix.
    pub folder: Option<FolderFilter>,
    /// Inclusive size lower bound in bytes.
    pub min_bytes: Option<u64>,
    /// Inclusive size upper bound in bytes.
    pub max_bytes: Option<u64>,
}

/// Root-scoped folder predicate.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FolderFilter {
    /// Corpus root registered by the harness.
    pub root_id: RootId,
    /// POSIX relative prefix, no leading `/`, trailing `/`.
    pub relative_prefix: String,
}

/// Which predicate a filter application refers to.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd, Serialize)]
pub enum FilterKind {
    /// File extension.
    Extension,
    /// Modified time.
    Modified,
    /// Folder prefix.
    Folder,
    /// File size.
    Size,
}

impl FilterKind {
    /// Canonical order used by reports.
    pub const ORDER: [Self; 4] = [Self::Extension, Self::Modified, Self::Folder, Self::Size];
}

/// How a predicate was applied.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub enum FilterMode {
    /// Applied inside every enabled first-stage retriever before its cap.
    Pushdown,
    /// Applied after candidate generation or fusion.
    Post,
}

/// One predicate's application mode.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct FilterApplication {
    /// Predicate.
    pub kind: FilterKind,
    /// Application mode.
    pub mode: FilterMode,
}

/// Filter diagnostics for one search.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct FilterReport {
    /// `Pushdown` only when every active predicate is pushed down.
    pub mode: FilterMode,
    /// One entry per active predicate, in `FilterKind` order.
    pub applications: Vec<FilterApplication>,
    /// Candidates the filter stage examined before the final limit.
    pub examined: usize,
    /// Candidates satisfying every active predicate before the final limit.
    pub matched: usize,
    /// Hits returned after applying the requested depth.
    pub returned: usize,
    /// True when an eligible lower-ranked hit may have been omitted.
    pub possibly_incomplete: bool,
}

/// Which first-stage retrievers accept a predicate before their cap.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FilterSupport {
    /// Extension predicate.
    pub extension: bool,
    /// Modified-time predicate.
    pub modified: bool,
    /// Folder predicate.
    pub folder: bool,
    /// Size predicate.
    pub size: bool,
}

impl FilterSupport {
    /// Every predicate is pushed down.
    pub const FULL: Self = Self {
        extension: true,
        modified: true,
        folder: true,
        size: true,
    };
    /// Every predicate is applied after fusion.
    pub const NONE: Self = Self {
        extension: false,
        modified: false,
        folder: false,
        size: false,
    };

    /// Whether `kind` is pushed down.
    #[must_use]
    pub const fn supports(self, kind: FilterKind) -> bool {
        match kind {
            FilterKind::Extension => self.extension,
            FilterKind::Modified => self.modified,
            FilterKind::Folder => self.folder,
            FilterKind::Size => self.size,
        }
    }
}

/// A validated filter with the folder root resolved to an absolute path.
///
/// The engine produces this from `MetadataFilter` after validating the request
/// and resolving the folder root. Bytewise prefix semantics are preserved.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct ResolvedFilter {
    /// Exact lowercase extensions.
    pub extensions: Vec<String>,
    /// Inclusive lower bound, UTC nanoseconds.
    pub modified_after_ns: Option<i64>,
    /// Exclusive upper bound, UTC nanoseconds.
    pub modified_before_ns: Option<i64>,
    /// Absolute folder prefix already normalized to `/` and ending in `/`.
    pub folder_absolute_prefix: Option<String>,
    /// Inclusive size lower bound.
    pub min_bytes: Option<u64>,
    /// Inclusive size upper bound.
    pub max_bytes: Option<u64>,
}

impl ResolvedFilter {
    /// Active predicate kinds in canonical order.
    #[must_use]
    pub fn active_kinds(&self) -> Vec<FilterKind> {
        let mut kinds = Vec::new();
        if !self.extensions.is_empty() {
            kinds.push(FilterKind::Extension);
        }
        if self.modified_after_ns.is_some() || self.modified_before_ns.is_some() {
            kinds.push(FilterKind::Modified);
        }
        if self.folder_absolute_prefix.is_some() {
            kinds.push(FilterKind::Folder);
        }
        if self.min_bytes.is_some() || self.max_bytes.is_some() {
            kinds.push(FilterKind::Size);
        }
        kinds
    }

    /// True when no predicate is active.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.active_kinds().is_empty()
    }
}

/// Indexed document metadata used to evaluate a filter predicate.
#[derive(Clone, Copy, Debug)]
pub struct DocumentMetadata<'a> {
    /// Lowercase indexed extension without a leading dot.
    pub ext: &'a str,
    /// Indexed size in bytes.
    pub size: i64,
    /// Indexed modified time in UTC nanoseconds; 0 is the unavailable sentinel.
    pub modified_ns: i64,
    /// Indexed path.
    pub path: &'a str,
}

/// Evaluate every active predicate against one document.
///
/// The caller is responsible for failing closed when a predicate is active but
/// the document lacks the required metadata (SPEC-0002 R23).
#[must_use]
pub fn document_matches(filter: &ResolvedFilter, document: &DocumentMetadata<'_>) -> bool {
    if !filter.extensions.is_empty()
        && !filter
            .extensions
            .iter()
            .any(|extension| document.ext.eq_ignore_ascii_case(extension))
    {
        return false;
    }
    if let Some(after) = filter.modified_after_ns
        && document.modified_ns < after
    {
        return false;
    }
    if let Some(before) = filter.modified_before_ns
        && document.modified_ns >= before
    {
        return false;
    }
    if let Some(prefix) = &filter.folder_absolute_prefix {
        let normalized = document.path.replace('\\', "/");
        if !normalized.as_bytes().starts_with(prefix.as_bytes()) {
            return false;
        }
    }
    if let Some(minimum) = filter.min_bytes
        && (document.size < 0 || (document.size as u64) < minimum)
    {
        return false;
    }
    if let Some(maximum) = filter.max_bytes
        && (document.size < 0 || (document.size as u64) > maximum)
    {
        return false;
    }
    true
}

/// Static filter validation failures. The engine maps these to
/// `EngineError::InvalidInput`.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FilterValidationError {
    /// No predicate is present.
    Empty,
    /// An extension token is malformed.
    Extension(String),
    /// The modified-time bounds are inverted.
    DateRange,
    /// The size bounds are inverted or out of range.
    SizeRange,
    /// A folder prefix is malformed.
    Folder(String),
}

impl std::fmt::Display for FilterValidationError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Empty => formatter.write_str("filter has no predicate"),
            Self::Extension(token) => write!(formatter, "invalid extension: {token}"),
            Self::DateRange => {
                formatter.write_str("modified_after_ns must precede modified_before_ns")
            }
            Self::SizeRange => formatter.write_str("size bounds are inverted or out of range"),
            Self::Folder(prefix) => write!(formatter, "invalid folder prefix: {prefix}"),
        }
    }
}

impl MetadataFilter {
    /// Validate the request contract and resolve the folder root path.
    ///
    /// `folder_root` must be the canonical indexed root path when `folder` is
    /// present; the engine resolves the root ID before calling this.
    pub fn resolve(
        &self,
        folder_root: Option<&str>,
    ) -> Result<ResolvedFilter, FilterValidationError> {
        let mut extensions = Vec::with_capacity(self.extensions.len());
        for raw in &self.extensions {
            let lowered = raw.to_ascii_lowercase();
            let valid = !lowered.is_empty()
                && lowered.len() <= 24
                && lowered.bytes().all(|byte| {
                    byte.is_ascii_lowercase()
                        || byte.is_ascii_digit()
                        || matches!(byte, b'+' | b'_' | b'-')
                });
            if !valid {
                return Err(FilterValidationError::Extension(raw.clone()));
            }
            extensions.push(lowered);
        }
        extensions.sort();
        extensions.dedup();

        if let (Some(after), Some(before)) = (self.modified_after_ns, self.modified_before_ns)
            && after >= before
        {
            return Err(FilterValidationError::DateRange);
        }

        if let (Some(minimum), Some(maximum)) = (self.min_bytes, self.max_bytes)
            && minimum > maximum
        {
            return Err(FilterValidationError::SizeRange);
        }
        if self
            .min_bytes
            .into_iter()
            .chain(self.max_bytes)
            .any(|value| i64::try_from(value).is_err())
        {
            return Err(FilterValidationError::SizeRange);
        }

        let folder_absolute_prefix = match &self.folder {
            Some(folder) => {
                let prefix = folder.relative_prefix.as_str();
                validate_folder_prefix(prefix)
                    .map_err(|()| FilterValidationError::Folder(prefix.to_string()))?;
                let root =
                    folder_root.ok_or_else(|| FilterValidationError::Folder(prefix.to_string()))?;
                let normalized_root = root.replace('\\', "/");
                let normalized_root = normalized_root.trim_end_matches('/');
                Some(format!("{normalized_root}/{prefix}"))
            }
            None => None,
        };

        let resolved = ResolvedFilter {
            extensions,
            modified_after_ns: self.modified_after_ns,
            modified_before_ns: self.modified_before_ns,
            folder_absolute_prefix,
            min_bytes: self.min_bytes,
            max_bytes: self.max_bytes,
        };
        if resolved.is_empty() {
            return Err(FilterValidationError::Empty);
        }
        Ok(resolved)
    }
}

fn validate_folder_prefix(prefix: &str) -> Result<(), ()> {
    if prefix.is_empty()
        || !prefix.ends_with('/')
        || prefix.starts_with('/')
        || prefix.contains('\\')
        || prefix.contains('\0')
    {
        return Err(());
    }
    let mut segments = prefix.split('/').peekable();
    while let Some(segment) = segments.next() {
        if segment.is_empty() {
            // The trailing slash produces one empty final segment.
            if segments.peek().is_none() {
                continue;
            }
            return Err(());
        }
        if segment == "." || segment == ".." {
            return Err(());
        }
    }
    Ok(())
}

/// Delivery stage of a v1.1 search; only `Single` is emitted.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub enum DeliveryStage {
    /// One blocking result list.
    Single,
}

/// Executed pipeline stages, in canonical order.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub enum SearchStage {
    /// Filename and path matching.
    Filename,
    /// FTS5/BM25 lexical retrieval.
    Lexical,
    /// Dense vector retrieval.
    Dense,
    /// Reciprocal rank fusion.
    Fuse,
    /// Snippet construction.
    Snippets,
}

/// One stage timing.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub struct StageTiming {
    /// Stage.
    pub stage: SearchStage,
    /// Monotonic duration in nanoseconds.
    pub duration_ns: u64,
    /// Candidates entering the stage.
    pub items_in: Option<u64>,
    /// Candidates leaving the stage.
    pub items_out: Option<u64>,
}

/// Public model identity; never a filesystem path.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct ModelIdentity {
    /// `embedder`, `reranker`, ...
    pub task: String,
    /// Public model identifier.
    pub id: String,
    /// Public model revision.
    pub revision: String,
    /// Deployed precision/provider variant.
    pub variant: String,
    /// Output dimension when known.
    pub dimension: Option<u32>,
}

/// Query-embedding timing for one search.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct QueryEmbeddingTiming {
    /// Duration in nanoseconds.
    pub duration_ns: u64,
    /// True when served from a query cache.
    pub cache_hit: bool,
    /// Public model identity.
    pub model: Option<ModelIdentity>,
}

/// In-process diagnostic data; nothing is persisted, logged, or sent.
#[derive(Clone, Debug, PartialEq, Eq, Serialize)]
pub struct SearchTelemetry {
    /// Telemetry schema version.
    pub schema_version: u16,
    /// Delivery stage.
    pub delivery_stage: DeliveryStage,
    /// Total request duration in nanoseconds.
    pub total_ns: u64,
    /// Query-embedding timing when the semantic channel ran.
    pub query_embedding: Option<QueryEmbeddingTiming>,
    /// One record per executed stage, canonical order.
    pub stages: Vec<StageTiming>,
    /// Effective requested depth.
    pub results_requested: usize,
    /// Returned hits.
    pub results_returned: usize,
}

impl SearchTelemetry {
    /// Current telemetry schema version.
    pub const SCHEMA_VERSION: u16 = 1;
}

/// Result of the uncached batch-1 query-embedding probe.
#[derive(Clone, Debug)]
pub enum QueryEmbeddingProbe {
    /// A semantic model is available.
    Available {
        /// Public model identity.
        model: ModelIdentity,
        /// Batch-1 embedding duration in nanoseconds.
        duration_ns: u64,
    },
    /// No semantic model is active; not an error.
    Unavailable,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn folder(relative_prefix: &str) -> MetadataFilter {
        MetadataFilter {
            folder: Some(FolderFilter {
                root_id: "root".into(),
                relative_prefix: relative_prefix.into(),
            }),
            ..MetadataFilter::default()
        }
    }

    #[test]
    fn filter_validation_normalizes_extensions() {
        // SPEC-0002-R21
        let filter = MetadataFilter {
            extensions: vec!["TXT".into(), "pdf".into(), "txt".into()],
            ..MetadataFilter::default()
        };
        let resolved = filter.resolve(None).expect("valid filter");
        assert_eq!(
            resolved.extensions,
            vec!["pdf".to_string(), "txt".to_string()]
        );
    }

    #[test]
    fn filter_validation_rejects_malformed_predicates() {
        // SPEC-0002-R23
        for token in [".pdf", "a/b", "two words", "", "with.dot"] {
            let filter = MetadataFilter {
                extensions: vec![token.into()],
                ..MetadataFilter::default()
            };
            assert_eq!(
                filter.resolve(None),
                Err(FilterValidationError::Extension(token.into()))
            );
        }
        assert_eq!(
            MetadataFilter::default().resolve(None),
            Err(FilterValidationError::Empty)
        );
        assert_eq!(
            MetadataFilter {
                modified_after_ns: Some(10),
                modified_before_ns: Some(10),
                ..MetadataFilter::default()
            }
            .resolve(None),
            Err(FilterValidationError::DateRange)
        );
        assert_eq!(
            MetadataFilter {
                min_bytes: Some(10),
                max_bytes: Some(9),
                ..MetadataFilter::default()
            }
            .resolve(None),
            Err(FilterValidationError::SizeRange)
        );
        assert_eq!(
            MetadataFilter {
                max_bytes: Some(u64::MAX),
                ..MetadataFilter::default()
            }
            .resolve(None),
            Err(FilterValidationError::SizeRange)
        );
    }

    #[test]
    fn folder_prefix_validation_rejects_malformed_segments() {
        // SPEC-0002-R23
        for prefix in ["", "/a/", "a", "a//b/", "a/./b/", "a/../b/", "a\\b/"] {
            assert_eq!(
                folder(prefix).resolve(Some("C:/corpus")),
                Err(FilterValidationError::Folder(prefix.into())),
                "prefix={prefix:?}"
            );
        }
        let resolved = folder("a/b/")
            .resolve(Some("C:\\corpus\\"))
            .expect("valid folder");
        assert_eq!(
            resolved.folder_absolute_prefix.as_deref(),
            Some("C:/corpus/a/b/")
        );
    }

    #[test]
    fn document_matches_applies_exact_predicates() {
        // SPEC-0002-R21
        let document = DocumentMetadata {
            ext: "txt",
            size: 100,
            modified_ns: 1_000,
            path: "C:\\corpus\\a\\b\\c.txt",
        };
        assert!(document_matches(&ResolvedFilter::default(), &document));
        let extension = ResolvedFilter {
            extensions: vec!["txt".into()],
            ..ResolvedFilter::default()
        };
        assert!(document_matches(&extension, &document));
        let other = ResolvedFilter {
            extensions: vec!["pdf".into()],
            ..ResolvedFilter::default()
        };
        assert!(!document_matches(&other, &document));
        // Inclusive after, exclusive before.
        let after = ResolvedFilter {
            modified_after_ns: Some(1_000),
            ..ResolvedFilter::default()
        };
        assert!(document_matches(&after, &document));
        let after_later = ResolvedFilter {
            modified_after_ns: Some(1_001),
            ..ResolvedFilter::default()
        };
        assert!(!document_matches(&after_later, &document));
        let before = ResolvedFilter {
            modified_before_ns: Some(1_000),
            ..ResolvedFilter::default()
        };
        assert!(!document_matches(&before, &document));
        let before_later = ResolvedFilter {
            modified_before_ns: Some(1_001),
            ..ResolvedFilter::default()
        };
        assert!(document_matches(&before_later, &document));
        // Complete-segment folder matching.
        let prefix = folder("a/b/")
            .resolve(Some("C:/corpus"))
            .expect("valid folder");
        assert!(document_matches(&prefix, &document));
        let sibling = folder("a/b/c/")
            .resolve(Some("C:/corpus"))
            .expect("valid folder");
        assert!(!document_matches(&sibling, &document));
        // Inclusive size bounds.
        let size = ResolvedFilter {
            min_bytes: Some(100),
            max_bytes: Some(100),
            ..ResolvedFilter::default()
        };
        assert!(document_matches(&size, &document));
        let larger = ResolvedFilter {
            min_bytes: Some(101),
            ..ResolvedFilter::default()
        };
        assert!(!document_matches(&larger, &document));
    }

    #[test]
    fn active_kinds_are_in_canonical_order() {
        // SPEC-0002-R22
        let resolved = MetadataFilter {
            extensions: vec!["txt".into()],
            modified_after_ns: Some(1),
            folder: Some(FolderFilter {
                root_id: "root".into(),
                relative_prefix: "a/".into(),
            }),
            min_bytes: Some(1),
            ..MetadataFilter::default()
        }
        .resolve(Some("C:/corpus"))
        .expect("valid filter");
        assert_eq!(resolved.active_kinds(), FilterKind::ORDER.to_vec());
    }
}
