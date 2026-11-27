use crate::db::{ChunkInput, FileSignature, Root};
use crate::extract;
use anyhow::{anyhow, Result};
use serde::Serialize;
use std::path::{Path, PathBuf};
use std::time::UNIX_EPOCH;
use walkdir::WalkDir;

#[derive(Clone, Debug, Serialize)]
pub struct IndexProgress {
    pub phase: String,
    pub current: usize,
    pub total: usize,
    pub file: String,
    pub message: String,
}

#[derive(Clone, Debug, Serialize, Default)]
pub struct IndexSummary {
    pub scanned: usize,
    pub files: usize,
    pub chunks: usize,
    pub unchanged: usize,
    pub skipped: usize,
    pub errors: usize,
    pub removed: usize,
    pub cancelled: bool,
    pub details: Vec<String>,
}

#[derive(Clone, Debug)]
pub struct PreparedFile {
    pub path: PathBuf,
    pub title: String,
    pub ext: String,
    pub size: i64,
    pub modified: i64,
    pub modified_ns: i64,
    pub content: String,
    pub chunks: Vec<(String, usize, usize)>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum FileOutcome {
    Updated { chunks: usize },
    Unchanged,
    Skipped { reason: String },
    Missing,
}

pub trait IndexContext {
    fn signature(&mut self, root_id: &str, path: &Path) -> Result<Option<FileSignature>>;
    fn embed(&mut self, texts: &[String]) -> Result<Vec<Vec<f32>>>;
    fn store(
        &mut self,
        root_id: &str,
        prepared: &PreparedFile,
        chunks: &[ChunkInput],
    ) -> Result<usize>;
    fn prune_missing(&mut self, root_id: &str, keep: &[PathBuf]) -> Result<usize>;
    fn cancelled(&self) -> bool {
        false
    }
}

const MAX_FILE_BYTES: u64 = 25 * 1024 * 1024;
const CHUNK_CHARS: usize = 1_200;
const OVERLAP_CHARS: usize = 200;
const MAX_DETAILS: usize = 50;

pub fn scan_root(root_path: &Path) -> Vec<PathBuf> {
    let mut files = Vec::new();
    for entry in WalkDir::new(root_path)
        .follow_links(false)
        .into_iter()
        .filter_entry(|entry| entry.depth() == 0 || !is_ignored(entry.path()))
    {
        let entry = match entry {
            Ok(entry) => entry,
            Err(_) => continue,
        };
        if !entry.file_type().is_file() {
            continue;
        }
        let path = entry.path();
        if is_supported_file(path) {
            files.push(path.to_path_buf());
        }
    }
    files
}

pub fn index_root(
    context: &mut dyn IndexContext,
    root: &Root,
    pdfium: &Path,
    progress: &mut dyn FnMut(IndexProgress),
) -> Result<IndexSummary> {
    let files = scan_root(Path::new(&root.path));
    let total = files.len();
    let mut summary = IndexSummary {
        scanned: total,
        ..IndexSummary::default()
    };

    for (index, path) in files.iter().enumerate() {
        if context.cancelled() {
            summary.cancelled = true;
            break;
        }
        progress(IndexProgress {
            phase: "extract".into(),
            current: index + 1,
            total,
            file: path.to_string_lossy().to_string(),
            message: format!(
                "Indexing {}",
                path.file_name().unwrap_or_default().to_string_lossy()
            ),
        });
        match index_file(context, root, path, pdfium) {
            Ok(FileOutcome::Updated { chunks }) => {
                summary.files += 1;
                summary.chunks += chunks;
            }
            Ok(FileOutcome::Unchanged) => summary.unchanged += 1,
            Ok(FileOutcome::Skipped { reason }) => {
                summary.skipped += 1;
                push_detail(&mut summary.details, format!("{}: {reason}", path.display()));
            }
            Ok(FileOutcome::Missing) => {
                summary.skipped += 1;
                push_detail(
                    &mut summary.details,
                    format!("{}: disappeared during scan", path.display()),
                );
            }
            Err(err) => {
                summary.errors += 1;
                push_detail(&mut summary.details, format!("{}: {err:#}", path.display()));
            }
        }
    }

    let removed = if summary.cancelled {
        0
    } else {
        context.prune_missing(&root.id, &files)?
    };
    summary.removed = removed;
    progress(IndexProgress {
        phase: "done".into(),
        current: total,
        total,
        file: String::new(),
        message: if summary.cancelled {
            format!(
                "Index cancelled after {} files / {} chunks",
                summary.files, summary.chunks
            )
        } else {
            format!(
                "Indexed {} files / {} unchanged / {} chunks / {} skipped / {} removed",
                summary.files, summary.unchanged, summary.chunks, summary.skipped, summary.removed
            )
        },
    });
    Ok(summary)
}

pub fn index_file(
    context: &mut dyn IndexContext,
    root: &Root,
    path: &Path,
    pdfium: &Path,
) -> Result<FileOutcome> {
    if is_ignored(path) || !is_supported_file(path) {
        return Ok(FileOutcome::Skipped {
            reason: "unsupported file".into(),
        });
    }
    let metadata = match std::fs::metadata(path) {
        Ok(metadata) if metadata.is_file() => metadata,
        Ok(_) => return Ok(FileOutcome::Missing),
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => return Ok(FileOutcome::Missing),
        Err(err) => return Err(err.into()),
    };
    if metadata.len() > MAX_FILE_BYTES {
        return Ok(FileOutcome::Skipped {
            reason: "file exceeds 25 MB limit".into(),
        });
    }

    let signature = FileSignature::from_metadata(&metadata);
    if context.signature(&root.id, path)? == Some(signature) {
        return Ok(FileOutcome::Unchanged);
    }

    let prepared = match prepare_file(path, pdfium, &metadata) {
        Ok(prepared) => prepared,
        Err(err) => {
            return Ok(FileOutcome::Skipped {
                reason: format!("{err:#}"),
            });
        }
    };
    let texts: Vec<String> = prepared
        .chunks
        .iter()
        .map(|(text, _, _)| text.clone())
        .collect();
    let vectors = context.embed(&texts)?;
    if vectors.len() != prepared.chunks.len() {
        return Err(anyhow!(
            "embedding count mismatch for {}: {} vectors for {} chunks",
            path.display(),
            vectors.len(),
            prepared.chunks.len()
        ));
    }
    let chunks: Vec<ChunkInput> = prepared
        .chunks
        .iter()
        .cloned()
        .zip(vectors)
        .map(|((text, start, end), embedding)| ChunkInput {
            text,
            page: None,
            start: start as i64,
            end: end as i64,
            embedding: Some(embedding),
        })
        .collect();
    let stored = context.store(&root.id, &prepared, &chunks)?;
    Ok(FileOutcome::Updated { chunks: stored })
}

fn prepare_file(
    path: &Path,
    pdfium: &Path,
    metadata: &std::fs::Metadata,
) -> Result<PreparedFile> {
    let text = extract::extract(path, pdfium)?;
    let text = text.trim().to_string();
    if text.chars().count() < 20 {
        return Err(anyhow!("extracted text too short"));
    }
    let chunks = chunk_text(&text);
    if chunks.is_empty() {
        return Err(anyhow!("no chunks produced"));
    }
    let duration = metadata
        .modified()
        .ok()
        .and_then(|time| time.duration_since(UNIX_EPOCH).ok());
    let modified = duration.map(|value| value.as_secs() as i64).unwrap_or(0);
    let modified_ns = duration
        .map(|value| value.as_nanos().min(i64::MAX as u128) as i64)
        .unwrap_or(0);
    let title = path
        .file_stem()
        .and_then(|stem| stem.to_str())
        .unwrap_or("Untitled")
        .to_string();
    let ext = path
        .extension()
        .and_then(|extension| extension.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    Ok(PreparedFile {
        path: path.to_path_buf(),
        title,
        ext,
        size: metadata.len() as i64,
        modified,
        modified_ns,
        content: text,
        chunks,
    })
}

fn push_detail(details: &mut Vec<String>, detail: String) {
    if details.len() < MAX_DETAILS {
        details.push(detail);
    }
}

pub fn is_supported_file(path: &Path) -> bool {
    let ext = path
        .extension()
        .and_then(|extension| extension.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    extract::supported_ext(&ext)
}

pub fn is_ignored(path: &Path) -> bool {
    let name = path
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("")
        .to_ascii_lowercase();
    matches!(
        name.as_str(),
        ".git"
            | ".hg"
            | ".svn"
            | ".idea"
            | ".vscode"
            | "node_modules"
            | "target"
            | "__pycache__"
            | ".venv"
            | "venv"
            | ".tox"
            | ".next"
            | ".nuxt"
            | "$recycle.bin"
            | "system volume information"
    ) || name.starts_with(".cache")
}

pub fn is_ignored_under(root: &Path, path: &Path) -> bool {
    let relative = path.strip_prefix(root).unwrap_or(path);
    relative.components().any(|component| {
        is_ignored(Path::new(component.as_os_str()))
    })
}

fn chunk_text(text: &str) -> Vec<(String, usize, usize)> {
    let chars: Vec<char> = text.chars().collect();
    if chars.is_empty() {
        return Vec::new();
    }
    let mut chunks = Vec::new();
    let mut start = 0usize;
    while start < chars.len() {
        let mut end = (start + CHUNK_CHARS).min(chars.len());
        if end < chars.len() {
            // Prefer a paragraph/sentence/whitespace boundary near the end.
            let window_start = end.saturating_sub(180);
            if let Some(position) = (window_start..end)
                .rev()
                .find(|index| matches!(chars[*index], '\n' | '.' | '!' | '?' | ';' | ' '))
            {
                end = position + 1;
            }
        }
        let chunk: String = chars[start..end].iter().collect();
        let trimmed = chunk.trim();
        if trimmed.chars().count() >= 40 {
            let leading = chunk.chars().take_while(|character| character.is_whitespace()).count();
            let trailing = chunk
                .chars()
                .rev()
                .take_while(|character| character.is_whitespace())
                .count();
            chunks.push((trimmed.to_string(), start + leading, end - trailing));
        }
        if end >= chars.len() {
            break;
        }
        start = end.saturating_sub(OVERLAP_CHARS);
    }
    chunks
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::db;
    use crate::inference::{find_gety_model_root, resolve_npu_dir, Backend, Engine};
    use crate::search;
    use rusqlite::Connection;

    struct DirectContext<'a> {
        conn: &'a mut Connection,
        engine: &'a mut Engine,
    }

    impl IndexContext for DirectContext<'_> {
        fn signature(&mut self, _root_id: &str, path: &Path) -> Result<Option<FileSignature>> {
            db::document_signature(self.conn, path)
        }

        fn embed(&mut self, texts: &[String]) -> Result<Vec<Vec<f32>>> {
            self.engine.embed(texts)
        }

        fn store(
            &mut self,
            root_id: &str,
            prepared: &PreparedFile,
            chunks: &[ChunkInput],
        ) -> Result<usize> {
            db::upsert_document(
                self.conn,
                root_id,
                &prepared.path,
                &prepared.title,
                &prepared.ext,
                prepared.size,
                prepared.modified,
                prepared.modified_ns,
                &prepared.content,
                chunks,
            )
        }

        fn prune_missing(&mut self, root_id: &str, keep: &[PathBuf]) -> Result<usize> {
            db::prune_missing(self.conn, root_id, keep)
        }
    }

    #[test]
    fn index_and_search_roundtrip() {
        let dir = std::env::temp_dir().join(format!("seeky-test-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(
            dir.join("renewal.txt"),
            "The contract renewal term is twelve months. Either party may give written notice at least thirty days before the anniversary date.",
        )
        .unwrap();
        std::fs::write(
            dir.join("budget.md"),
            "# Budget\n\nThe finance team approved the annual budget for local search infrastructure.",
        )
        .unwrap();
        std::fs::write(
            dir.join("atlas-notes.txt"),
            "Unrelated meeting minutes about coffee, parking, and the next team lunch.",
        )
        .unwrap();
        std::fs::copy(
            PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/renewal.pdf"),
            dir.join("renewal.pdf"),
        )
        .unwrap();
        std::fs::copy(
            PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/sample.docx"),
            dir.join("sample.docx"),
        )
        .unwrap();

        let model_root = find_gety_model_root().expect("model");
        let npu_dir = resolve_npu_dir(None);
        let mut engine = Engine::create(Backend::Cpu, &model_root, &npu_dir).expect("engine");
        let db_path = dir.join("seeky.db");
        let mut conn = crate::db::open(&db_path).expect("db");
        let root = crate::db::add_root(&conn, dir.to_str().unwrap()).expect("root");
        let pdfium = PathBuf::from(std::env::var("LOCALAPPDATA").unwrap())
            .join("Gety")
            .join("lib")
            .join("pdfium.dll");
        let mut progress = |_| {};

        let summary = {
            let mut context = DirectContext {
                conn: &mut conn,
                engine: &mut engine,
            };
            index_root(&mut context, &root, &pdfium, &mut progress).expect("index")
        };
        assert_eq!(summary.files, 5, "summary={summary:?}");
        assert!(summary.chunks >= 5, "summary={summary:?}");
        assert_eq!(crate::db::counts(&conn).unwrap().documents, 5);

        // A second scan skips every unchanged file.
        let summary2 = {
            let mut context = DirectContext {
                conn: &mut conn,
                engine: &mut engine,
            };
            index_root(&mut context, &root, &pdfium, &mut progress).expect("reindex")
        };
        assert_eq!(summary2.files, 0, "summary2={summary2:?}");
        assert!(summary2.unchanged >= 5, "summary2={summary2:?}");

        // Changed content is picked up by size/mtime and replaces the old document.
        std::fs::write(
            dir.join("budget.md"),
            "# Budget\n\nThe quarterly forecast was revised after the planning meeting.",
        )
        .unwrap();
        let summary3 = {
            let mut context = DirectContext {
                conn: &mut conn,
                engine: &mut engine,
            };
            index_root(&mut context, &root, &pdfium, &mut progress).expect("reindex after edit")
        };
        assert_eq!(summary3.files, 1, "summary3={summary3:?}");
        assert!(summary3.unchanged >= 4, "summary3={summary3:?}");

        // Filename/path matching is part of hybrid retrieval.
        let query_vector = engine
            .embed(&["atlas".to_string()])
            .expect("embed query")
            .pop()
            .expect("vector");
        let hits = search::search(&conn, "atlas", Some(&query_vector), 10).expect("search");
        assert!(
            hits.iter()
                .any(|hit| hit.title == "atlas-notes" && hit.matched.iter().any(|m| m == "filename")),
            "hits={hits:?}"
        );

        // Rename: remove the old path and index the new one.
        std::fs::rename(dir.join("atlas-notes.txt"), dir.join("atlas-renamed.txt")).unwrap();
        crate::db::delete_document_by_path(&conn, &dir.join("atlas-notes.txt")).unwrap();
        let summary4 = {
            let mut context = DirectContext {
                conn: &mut conn,
                engine: &mut engine,
            };
            index_root(&mut context, &root, &pdfium, &mut progress).expect("reindex after rename")
        };
        assert_eq!(summary4.files, 1, "summary4={summary4:?}");
        assert_eq!(crate::db::counts(&conn).unwrap().documents, 5);

        // Delete: a full reindex prunes the missing document.
        std::fs::remove_file(dir.join("atlas-renamed.txt")).unwrap();
        let summary5 = {
            let mut context = DirectContext {
                conn: &mut conn,
                engine: &mut engine,
            };
            index_root(&mut context, &root, &pdfium, &mut progress).expect("reindex after delete")
        };
        assert_eq!(summary5.removed, 1, "summary5={summary5:?}");
        assert_eq!(crate::db::counts(&conn).unwrap().documents, 4);

        let _ = std::fs::remove_dir_all(&dir);
    }
}
