use anyhow::{Context, Result};
use rusqlite::{params, Connection, OptionalExtension};
use serde::Serialize;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

#[derive(Clone, Debug, Serialize)]
pub struct Root {
    pub id: String,
    pub path: String,
    pub documents: i64,
    pub watch_enabled: bool,
}

#[derive(Clone, Debug)]
pub struct ChunkInput {
    pub text: String,
    pub page: Option<i64>,
    pub start: i64,
    pub end: i64,
    pub embedding: Option<Vec<f32>>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct FileSignature {
    pub size: i64,
    pub modified_ns: i64,
}

impl FileSignature {
    pub fn from_metadata(metadata: &std::fs::Metadata) -> Self {
        let modified_ns = metadata
            .modified()
            .ok()
            .and_then(|time| time.duration_since(UNIX_EPOCH).ok())
            .map(|duration| duration.as_nanos().min(i64::MAX as u128) as i64)
            .unwrap_or(0);
        Self {
            size: metadata.len() as i64,
            modified_ns,
        }
    }
}

#[derive(Clone, Debug, Serialize)]
pub struct ChunkContext {
    pub chunk_id: i64,
    pub doc_id: String,
    pub title: String,
    pub path: String,
    pub ext: String,
    pub text: String,
    pub page: Option<i64>,
    pub start: i64,
    pub end: i64,
}

#[derive(Clone, Debug, Serialize)]
pub struct DocumentView {
    pub id: String,
    pub title: String,
    pub path: String,
    pub ext: String,
    pub size: i64,
    pub modified: i64,
    pub content: String,
}

#[derive(Clone, Debug, Serialize)]
pub struct Counts {
    pub documents: i64,
    pub chunks: i64,
    pub roots: i64,
    pub embeddings: i64,
}

pub fn open(path: &Path) -> Result<Connection> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).ok();
    }
    let conn = Connection::open(path)
        .with_context(|| format!("open sqlite database {}", path.display()))?;
    conn.execute_batch(
        "
        PRAGMA journal_mode=WAL;
        PRAGMA synchronous=NORMAL;
        PRAGMA foreign_keys=ON;
        PRAGMA busy_timeout=5000;
        ",
    )?;
    init_schema(&conn)?;
    Ok(conn)
}

fn init_schema(conn: &Connection) -> Result<()> {
    conn.execute_batch(
        "
        CREATE TABLE IF NOT EXISTS roots (
          id TEXT PRIMARY KEY,
          path TEXT NOT NULL UNIQUE,
          created_at INTEGER NOT NULL,
          watch_enabled INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS documents (
          id TEXT PRIMARY KEY,
          root_id TEXT NOT NULL REFERENCES roots(id) ON DELETE CASCADE,
          path TEXT NOT NULL UNIQUE,
          title TEXT NOT NULL,
          ext TEXT NOT NULL,
          size INTEGER NOT NULL,
          modified INTEGER NOT NULL,
          modified_ns INTEGER NOT NULL DEFAULT 0,
          content TEXT NOT NULL,
          indexed_at INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_documents_root ON documents(root_id);

        CREATE TABLE IF NOT EXISTS chunks (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          doc_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
          ord INTEGER NOT NULL,
          text TEXT NOT NULL,
          page INTEGER,
          start_offset INTEGER NOT NULL,
          end_offset INTEGER NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);

        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
          text,
          content='chunks',
          content_rowid='id',
          tokenize='unicode61 remove_diacritics 2'
        );

        CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
          INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
        END;
        CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
          INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
        END;
        CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE OF text ON chunks BEGIN
          INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
          INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text);
        END;

        CREATE TABLE IF NOT EXISTS embeddings (
          chunk_id INTEGER PRIMARY KEY REFERENCES chunks(id) ON DELETE CASCADE,
          dim INTEGER NOT NULL,
          vector BLOB NOT NULL
        );

        CREATE TABLE IF NOT EXISTS settings (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );
        ",
    )
    .context("create seeky schema")?;

    // Migrations for databases created by the first PoC build.
    ensure_column(
        conn,
        "documents",
        "modified_ns",
        "modified_ns INTEGER NOT NULL DEFAULT 0",
    )?;
    ensure_column(
        conn,
        "roots",
        "watch_enabled",
        "watch_enabled INTEGER NOT NULL DEFAULT 1",
    )?;
    Ok(())
}

fn ensure_column(
    conn: &Connection,
    table: &str,
    column: &str,
    declaration: &str,
) -> Result<()> {
    let mut stmt = conn.prepare(&format!("PRAGMA table_info({table})"))?;
    let mut rows = stmt.query([])?;
    while let Some(row) = rows.next()? {
        let name: String = row.get(1)?;
        if name.eq_ignore_ascii_case(column) {
            return Ok(());
        }
    }
    conn.execute(&format!("ALTER TABLE {table} ADD COLUMN {declaration}"), [])?;
    Ok(())
}

pub fn now_secs() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs() as i64)
        .unwrap_or(0)
}

fn root_from_row(row: &rusqlite::Row<'_>) -> rusqlite::Result<Root> {
    Ok(Root {
        id: row.get(0)?,
        path: row.get(1)?,
        documents: row.get(2)?,
        watch_enabled: row.get::<_, i64>(3)? != 0,
    })
}

pub fn add_root(conn: &Connection, path: &str) -> Result<Root> {
    let canonical =
        std::fs::canonicalize(path).with_context(|| format!("path does not exist: {path}"))?;
    let path_str = canonical.to_string_lossy().to_string();
    let id = blake3::hash(path_str.as_bytes()).to_hex().to_string();
    conn.execute(
        "INSERT INTO roots(id, path, created_at) VALUES (?1, ?2, ?3)
         ON CONFLICT(path) DO NOTHING",
        params![id, path_str, now_secs()],
    )?;
    get_root_by_path(conn, &path_str)?.ok_or_else(|| anyhow::anyhow!("root not found after insert"))
}

pub fn get_root(conn: &Connection, id: &str) -> Result<Option<Root>> {
    conn.query_row(
        "SELECT r.id, r.path,
                (SELECT COUNT(*) FROM documents d WHERE d.root_id = r.id),
                r.watch_enabled
         FROM roots r WHERE r.id = ?1",
        params![id],
        root_from_row,
    )
    .optional()
    .map_err(Into::into)
}

fn get_root_by_path(conn: &Connection, path: &str) -> Result<Option<Root>> {
    conn.query_row(
        "SELECT r.id, r.path,
                (SELECT COUNT(*) FROM documents d WHERE d.root_id = r.id),
                r.watch_enabled
         FROM roots r WHERE r.path = ?1",
        params![path],
        root_from_row,
    )
    .optional()
    .map_err(Into::into)
}

pub fn list_roots(conn: &Connection) -> Result<Vec<Root>> {
    let mut stmt = conn.prepare(
        "SELECT r.id, r.path,
                (SELECT COUNT(*) FROM documents d WHERE d.root_id = r.id),
                r.watch_enabled
         FROM roots r ORDER BY r.path",
    )?;
    let rows = stmt.query_map([], root_from_row)?;
    Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
}

pub fn set_root_watching(conn: &Connection, id: &str, enabled: bool) -> Result<()> {
    conn.execute(
        "UPDATE roots SET watch_enabled = ?1 WHERE id = ?2",
        params![enabled as i64, id],
    )?;
    Ok(())
}

pub fn remove_root(conn: &Connection, id: &str) -> Result<()> {
    conn.execute("DELETE FROM roots WHERE id = ?1", params![id])?;
    Ok(())
}

pub fn document_signature(conn: &Connection, path: &Path) -> Result<Option<FileSignature>> {
    let path = path.to_string_lossy().to_string();
    conn.query_row(
        "SELECT size, modified_ns FROM documents WHERE path = ?1",
        params![path],
        |row| {
            Ok(FileSignature {
                size: row.get(0)?,
                modified_ns: row.get(1)?,
            })
        },
    )
    .optional()
    .map_err(Into::into)
}

pub fn delete_document_by_path(conn: &Connection, path: &Path) -> Result<usize> {
    let path = path.to_string_lossy().to_string();
    Ok(conn.execute("DELETE FROM documents WHERE path = ?1", params![path])?)
}

pub fn delete_documents_under(conn: &Connection, root_id: &str, path: &Path) -> Result<usize> {
    let mut prefix = path
        .to_string_lossy()
        .trim_end_matches(['\\', '/'])
        .to_string();
    if prefix.is_empty() {
        return Ok(0);
    }
    prefix.push(std::path::MAIN_SEPARATOR);
    Ok(conn.execute(
        "DELETE FROM documents
         WHERE root_id = ?1
           AND (path = ?2 OR substr(path, 1, length(?3)) = ?3)",
        params![root_id, path.to_string_lossy(), prefix],
    )?)
}

pub fn prune_missing(conn: &Connection, root_id: &str, keep: &[PathBuf]) -> Result<usize> {
    let mut stmt = conn.prepare("SELECT path FROM documents WHERE root_id = ?1")?;
    let paths = stmt
        .query_map(params![root_id], |row| row.get::<_, String>(0))?
        .collect::<rusqlite::Result<Vec<_>>>()?;
    drop(stmt);
    let keep: std::collections::HashSet<String> = keep
        .iter()
        .map(|path| path.to_string_lossy().to_string())
        .collect();
    let mut removed = 0;
    for path in paths {
        if !keep.contains(&path) {
            removed += conn.execute("DELETE FROM documents WHERE path = ?1", params![path])?;
        }
    }
    Ok(removed)
}

pub fn counts(conn: &Connection) -> Result<Counts> {
    let documents = conn.query_row("SELECT COUNT(*) FROM documents", [], |row| row.get(0))?;
    let chunks = conn.query_row("SELECT COUNT(*) FROM chunks", [], |row| row.get(0))?;
    let roots = conn.query_row("SELECT COUNT(*) FROM roots", [], |row| row.get(0))?;
    let embeddings = conn.query_row("SELECT COUNT(*) FROM embeddings", [], |row| row.get(0))?;
    Ok(Counts {
        documents,
        chunks,
        roots,
        embeddings,
    })
}

pub fn last_indexed_at(conn: &Connection) -> Result<Option<i64>> {
    conn.query_row("SELECT MAX(indexed_at) FROM documents", [], |row| row.get(0))
        .optional()
        .map(|value| value.flatten())
        .map_err(Into::into)
}

#[allow(clippy::too_many_arguments)]
pub fn upsert_document(
    conn: &mut Connection,
    root_id: &str,
    path: &Path,
    title: &str,
    ext: &str,
    size: i64,
    modified: i64,
    modified_ns: i64,
    content: &str,
    chunks: &[ChunkInput],
) -> Result<usize> {
    let path_str = path.to_string_lossy().to_string();
    let doc_id = blake3::hash(path_str.as_bytes()).to_hex().to_string();
    let tx = conn.transaction()?;
    tx.execute("DELETE FROM documents WHERE path = ?1", params![path_str])?;
    tx.execute(
        "INSERT INTO documents(
            id, root_id, path, title, ext, size, modified, modified_ns, content, indexed_at
         ) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10)",
        params![
            doc_id,
            root_id,
            path_str,
            title,
            ext,
            size,
            modified,
            modified_ns,
            content,
            now_secs()
        ],
    )?;
    for (index, chunk) in chunks.iter().enumerate() {
        tx.execute(
            "INSERT INTO chunks(doc_id, ord, text, page, start_offset, end_offset)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6)",
            params![
                doc_id,
                index as i64,
                chunk.text,
                chunk.page,
                chunk.start,
                chunk.end
            ],
        )?;
        let chunk_id = tx.last_insert_rowid();
        if let Some(vector) = &chunk.embedding {
            let bytes: Vec<u8> = vector.iter().flat_map(|value| value.to_le_bytes()).collect();
            tx.execute(
                "INSERT INTO embeddings(chunk_id, dim, vector) VALUES (?1, ?2, ?3)",
                params![chunk_id, vector.len() as i64, bytes],
            )?;
        }
    }
    tx.commit()?;
    Ok(chunks.len())
}

pub fn all_embeddings(conn: &Connection) -> Result<Vec<(i64, Vec<f32>)>> {
    let mut stmt = conn.prepare("SELECT chunk_id, dim, vector FROM embeddings")?;
    let rows = stmt.query_map([], |row| {
        let id: i64 = row.get(0)?;
        let dim: usize = row.get::<_, i64>(1)? as usize;
        let bytes: Vec<u8> = row.get(2)?;
        let mut vector = Vec::with_capacity(dim);
        for chunk in bytes.chunks_exact(4) {
            vector.push(f32::from_le_bytes([
                chunk[0], chunk[1], chunk[2], chunk[3],
            ]));
        }
        Ok((id, vector))
    })?;
    Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
}

pub fn bm25(conn: &Connection, query: &str, limit: usize) -> Result<Vec<(i64, f64)>> {
    let mut stmt = conn.prepare(
        "SELECT c.id, bm25(chunks_fts)
         FROM chunks_fts
         JOIN chunks c ON c.id = chunks_fts.rowid
         WHERE chunks_fts MATCH ?1
         ORDER BY bm25(chunks_fts)
         LIMIT ?2",
    )?;
    let rows = stmt.query_map(params![query, limit as i64], |row| {
        Ok((row.get(0)?, row.get(1)?))
    })?;
    Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
}

pub fn filename_chunks(conn: &Connection, query: &str, limit: usize) -> Result<Vec<i64>> {
    let mut terms: Vec<String> = Vec::new();
    for token in query.split(|character: char| !character.is_alphanumeric()) {
        let term = token.trim().to_lowercase();
        if term.chars().count() >= 2 && !terms.contains(&term) {
            terms.push(term);
        }
    }
    if terms.is_empty() {
        return Ok(Vec::new());
    }

    let mut sql = String::from(
        "SELECT c.id
         FROM chunks c
         JOIN documents d ON d.id = c.doc_id
         WHERE c.ord = 0 AND (",
    );
    for (index, _) in terms.iter().enumerate() {
        if index > 0 {
            sql.push_str(" OR ");
        }
        sql.push_str("(instr(lower(d.title), ?) > 0 OR instr(lower(d.path), ?) > 0)");
    }
    sql.push_str(&format!(
        ") ORDER BY d.modified DESC, d.title LIMIT {}",
        limit.clamp(1, 200)
    ));

    let mut values = Vec::with_capacity(terms.len() * 2);
    for term in &terms {
        values.push(term.clone());
        values.push(term.clone());
    }

    let mut stmt = conn.prepare(&sql)?;
    let rows = stmt.query_map(rusqlite::params_from_iter(values.iter()), |row| row.get(0))?;
    Ok(rows.collect::<rusqlite::Result<Vec<_>>>()?)
}

pub fn chunk_contexts(conn: &Connection, ids: &[i64]) -> Result<Vec<ChunkContext>> {
    if ids.is_empty() {
        return Ok(Vec::new());
    }
    let placeholders = ids
        .iter()
        .map(|_| "?")
        .collect::<Vec<_>>()
        .join(",");
    let sql = format!(
        "SELECT c.id, c.doc_id, d.title, d.path, d.ext, c.text, c.page,
                c.start_offset, c.end_offset
         FROM chunks c JOIN documents d ON d.id = c.doc_id
         WHERE c.id IN ({placeholders})"
    );
    let mut stmt = conn.prepare(&sql)?;
    let params: Vec<&dyn rusqlite::ToSql> = ids
        .iter()
        .map(|id| id as &dyn rusqlite::ToSql)
        .collect();
    let rows = stmt.query_map(params.as_slice(), |row| {
        Ok(ChunkContext {
            chunk_id: row.get(0)?,
            doc_id: row.get(1)?,
            title: row.get(2)?,
            path: row.get(3)?,
            ext: row.get(4)?,
            text: row.get(5)?,
            page: row.get(6)?,
            start: row.get(7)?,
            end: row.get(8)?,
        })
    })?;
    let mut result = rows.collect::<rusqlite::Result<Vec<_>>>()?;
    // Preserve input order for deterministic fusion.
    result.sort_by_key(|context| {
        ids.iter()
            .position(|id| *id == context.chunk_id)
            .unwrap_or(usize::MAX)
    });
    Ok(result)
}

pub fn get_document(conn: &Connection, id: &str) -> Result<Option<DocumentView>> {
    conn.query_row(
        "SELECT id, title, path, ext, size, modified, content FROM documents WHERE id = ?1",
        params![id],
        |row| {
            Ok(DocumentView {
                id: row.get(0)?,
                title: row.get(1)?,
                path: row.get(2)?,
                ext: row.get(3)?,
                size: row.get(4)?,
                modified: row.get(5)?,
                content: row.get(6)?,
            })
        },
    )
    .optional()
    .map_err(Into::into)
}

pub fn set_setting(conn: &Connection, key: &str, value: &str) -> Result<()> {
    conn.execute(
        "INSERT INTO settings(key, value) VALUES (?1, ?2)
         ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        params![key, value],
    )?;
    Ok(())
}

pub fn get_setting(conn: &Connection, key: &str) -> Result<Option<String>> {
    conn.query_row(
        "SELECT value FROM settings WHERE key = ?1",
        params![key],
        |row| row.get(0),
    )
    .optional()
    .map_err(Into::into)
}

#[allow(dead_code)]
pub fn db_path_for_display(path: &Path) -> String {
    path.canonicalize()
        .unwrap_or_else(|_| PathBuf::from(path))
        .to_string_lossy()
        .to_string()
}
