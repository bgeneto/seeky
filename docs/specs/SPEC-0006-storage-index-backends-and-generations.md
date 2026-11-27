# SPEC-0006 — Storage, index backends, index generations, and embedding channels

| Field | Value |
|---|---|
| Status | Draft |
| Version | 0.1 |
| Owner | Maintainer |
| Phase / work packages | Phase 2 — WP-2.4, WP-2.5, WP-2.13 (storage side; SPEC-0005 owns the manifest and `Embedder` side); Phase 3 — WP-3.7 |
| Crates touched | `seeky-core` (IDs, index traits, generation and channel types, `IndexError`), `seeky-store` (schema, migrations, writer actor, reader pool, as-built backends, generations, embedding-cache table), `seeky-search` (retrieval through the traits; fusion over N rankings), `seeky-engine` (generation manager, wiring) |
| Governing docs | [vision](../product/vision.md) P3, P4, P7, P8 and §5.3, §6; [ADR-0015](../adr/0015-engine-first-architecture.md); [ADR-0018](../adr/0018-lexical-first-availability.md); [ADR-0019](../adr/0019-single-inference-engine.md) decisions 6–7; [ADR-0020](../adr/0020-pluggable-index-backends.md); [ADR-0023](../adr/0023-multimodal-ready-engine.md) decision 1; [ADR-0024](../adr/0024-source-code-indexing-opt-in.md); [ADR-0025](../adr/0025-automatic-provider-opt-in-gpu-tier-full-speed.md) items 6–7; [architecture/overview](../architecture/overview.md) §4–§5; [architecture/indexing](../architecture/indexing.md) §2.5–§4; [architecture/inference-and-models](../architecture/inference-and-models.md) §6–§8; [SPEC-0001](SPEC-0001-workspace-and-crate-boundaries.md) §4.2, §4.4; [SPEC-0002](SPEC-0002-engine-api.md) §5.2, §5.5, §9 |
| Benchmark gates | S1, S2, S5, I1, R3, R4, R5 (from `docs/benchmarks/methodology.md` §5); V4 when a visual channel exists (§5.6) |

## 1. Problem and goal

The PoC store is one SQLite file opened through one mutex-guarded connection
(`crates/seeky-store/src/db.rs`). Its schema is created by `CREATE TABLE IF NOT
EXISTS` plus ad hoc `ensure_column` calls, with no schema version. Lexical
(FTS5), filename (`instr` over title and path), and vector (f32 BLOBs, exact
scan of every vector on every query) retrieval are free functions behind a
`SearchStore` trait that lives in `seeky-store` and returns SQLite-shaped data.
Vectors carry only their length: vectors from different backends and precisions
mix in one table (audit A5), the dense path skips query vectors whose length is
not the hardcoded `DIM` (audit, ADR-0019), and search waits for indexing writes
on the shared mutex (audit A7). Nothing records which model produced a vector,
so a model change cannot be made without mixing spaces or taking search down.

This spec defines the storage contract the rest of the engine builds on: a
versioned schema with transactional migrations from the PoC database; one
store-writer actor and a pool of WAL readers so that search never waits for
indexing; swappable lexical, filename, and vector index backends behind traits
in `seeky-core`, with the as-built implementations behind them first and the
winners chosen later by bake-off (P7); and **index generations** grouped by
**embedding channel**, so a model, revision, dimension, recipe, or backend
change builds a new generation in the background and is promoted atomically,
vectors from different spaces are never mixed, and raw scores from different
modalities are never compared (ADR-0019 decision 7, ADR-0023 decision 1).

Done means: the PoC database opens and migrates without data loss and with
identical lexical and filename results; a search runs to completion while the
writer is mid-transaction and while a new generation is being built; a model
swap happens with no search downtime; a crash at any point leaves a store that
reopens consistent; storage failures surface as typed errors that never carry
document text, file names, or paths; and every derived index can be rebuilt
from SQLite plus the embedding cache (ADR-0020).

## 2. Scope

- **In:**
  - Storage layout under the data directory; schema v2 DDL; schema versioning;
    forward-only transactional migrations, including PoC → v2 (WP-2.4).
  - The store-writer actor, the WAL reader pool, read snapshots, and the lock
    rules that keep search independent of indexing (WP-2.4).
  - Typed storage errors, crash consistency between SQLite and external index
    files, corruption detection, disk-full behavior, disk accounting and
    pre-flight hooks, and log/error privacy (WP-2.4, WP-3.7).
  - `LexicalIndex`, `FilenameIndex`, `VectorIndex` traits and their writer
    counterparts in `seeky-core`; the guarantees every backend must meet; the
    as-built FTS5, SQL filename, and exact-f32 adapters; retrieval in
    `seeky-search` only through the traits (WP-2.5).
  - Embedding channels, retrieval-unit modality and locators, the
    `visual_units` table, per-modality vector instances, and fusion over N
    tagged rankings, with text-only behavior unchanged (WP-2.13, storage and
    retrieval side).
  - Index generations: recipe, space key, build keys, lifecycle (building,
    active, retired, abandoned), background rebuild, catch-up, atomic
    promotion, garbage collection, and query-time space checks (WP-3.7).
  - The `embedding_cache` table, its key, and its garbage collection by space.
  - Schema skeletons for `jobs` and `models` (WP-2.4 deliverable).
- **Out:**
  - Model manifest, `space` ID declaration, ONNX variants, parity vectors and
    parity groups, the image capability on `Embedder`, and vision-session
    residency → SPEC-0005 (WP-2.1, WP-2.13) and SPEC-0012 (parity-on-load).
  - Job-queue semantics, two-speed lane scheduling, embedding-cache hit/miss
    and rename/copy behavior (gate I5), reconcile, the governor → SPEC-0007.
  - Extraction, chunking rules and chunker versions, language ID, the
    source-code extension list → SPEC-0008.
  - Choice of the lexical engine and analyzers (WP-2.7), filename index
    structure (WP-2.8), vector store, ANN, and vector quantization including
    whether the cache keeps full-precision vectors (WP-2.9), chunking (WP-2.10):
    bake-offs with their own reports and ADRs. This spec fixes only the
    contracts those winners must satisfy.
  - Ranking, fusion function and weights, calibration, document layer →
    SPEC-0010 (fusion bake-off WP-4.7). Visual-unit selection, visual fusion,
    image queries → SPEC-0016.
  - Public `Engine` API for model selection, generation status, and rebuild
    progress → SPEC-0002 v2 (§7 Q9); UI → SPEC-0014.
  - Idle maintenance (vacuum, compaction, full integrity checks) and soak
    testing → WP-8.2. The opt-in GPU quality tier → post-1.0 (ADR-0025 item 8);
    this spec only leaves room for a retained generation.

## 3. Requirements (EARS)

Requirements are grouped by work package; the WP is named in the ID's group
heading row so an implementer can pick the rows of one WP.

| ID | Requirement | Verification | Status |
|---|---|---|---|
| | **Storage layout, schema, migrations (WP-2.4)** | | |
| SPEC-0006-R1 | The store shall keep all of its files under the data directory given in `StoreConfig` (`seeky.db` and its WAL/SHM files, `index/`, `cache/`, `quarantine/`, §4.1), shall record locations inside the database only as paths relative to that directory, and shall never create, modify, or delete a file outside it. | unit `store_writes_only_under_data_dir`; unit `db_records_relative_locations_only`; fault test `gc_refuses_paths_outside_index_dir` | Open |
| SPEC-0006-R2 | The store shall record its schema version in `PRAGMA user_version`; when it opens an empty database it shall create the latest schema, and when it opens a database already at the latest version it shall execute no DDL. | unit `empty_db_gets_latest_schema`; unit `current_db_open_runs_no_ddl` | Open |
| SPEC-0006-R3 | When the store opens a database at an older supported version, it shall apply each forward migration step in its own `IMMEDIATE` transaction that also sets `user_version`; if a step fails, then the database shall remain at the previous version with its previous contents and the store shall return `StoreError::MigrationFailed { from, to }`. | unit `each_migration_step_is_one_transaction`; fault test `failed_migration_leaves_db_at_previous_version` (fail point inside step) | Open |
| SPEC-0006-R4 | When the store opens a PoC database (`user_version` 0 with the PoC table fingerprint, treated as schema 1), it shall migrate it to v2 preserving every root (ID, path, watch state), document (as a file with its existing `DocId`), chunk (as a passage under the `poc-v1` chunking with its text, page, and offsets), document text, and setting; it shall create the text channel and one active lexical-only text generation; and lexical and filename retrieval on the migrated database shall return the same ranked units and scores as before migration. | integration `poc_db_migrates_without_loss` (fixture built from the frozen PoC DDL); integration `poc_migration_preserves_lexical_and_filename_results` | Open |
| SPEC-0006-R5 | The PoC migration shall not carry PoC embedding vectors into any generation, because their space and precision are unknown (audit A5); it shall drop them, and the engine shall re-embed under a recorded recipe. | integration `poc_vectors_are_not_imported`; see §7 Q1 | Open |
| SPEC-0006-R6 | If the database's `user_version` is newer than the binary supports, then the store shall return `StoreError::SchemaTooNew { found, supported }`; if the database is non-empty but matches no known schema fingerprint, then it shall return `StoreError::UnrecognizedSchema`; in both cases it shall not write to the database. | unit `newer_schema_is_refused_without_writes`; unit `unknown_schema_is_refused_without_writes` (file hash unchanged) | Open |
| | **Writer, readers, and concurrency (WP-2.4)** | | |
| SPEC-0006-R7 | The store shall perform every write to SQLite and to every index instance through one store-writer actor; all other connections shall be opened read-only (`query_only`), so that a write attempted on a reader connection fails. | unit `reader_connections_reject_writes`; inspection: one constructor of the write connection, owned by the writer thread | Open |
| SPEC-0006-R8 | The writer shall group submitted write commands into transactions bounded by `store.writer.max_batch_units` and `store.writer.max_batch_ms`, and shall resolve each submission with the `ChangeSeq` at which it became durable (or a typed error); after that resolution, every new read snapshot shall observe the write. | unit `writer_batches_respect_unit_and_time_bounds` (fake clock); unit `committed_write_visible_to_next_snapshot` | Open |
| SPEC-0006-R9 | While the writer holds an open write transaction, a read snapshot shall open and a lexical, filename, and vector query shall complete against the last committed state without waiting for the writer. | integration `search_completes_while_writer_txn_is_open` (writer parked on a barrier inside the transaction; no sleeps) | Open |
| SPEC-0006-R10 | The store shall not hold any store lock, SQLite transaction, or read snapshot across inference or user-file I/O: the writer shall accept only prepared data, and its thread shall never call an `Embedder`, an extractor, or a filesystem API on a user file. | inspection (SPEC-0001 §4.4 matrix: `seeky-store` depends on neither `seeky-infer` nor `seeky-extract`); unit `writer_api_takes_prepared_data_only` (compile-level: no callback parameters) | Open |
| SPEC-0006-R11 | Each search shall read through one `ReadSnapshot` that pins one committed SQLite read transaction and one `GenerationSnapshot` per channel, and shall release it when the search ends; units returned by an index but absent from SQLite in that snapshot shall be dropped during hydration and counted, never returned and never an error. | unit `snapshot_pins_one_committed_state`; unit `hydration_drops_units_deleted_after_index_read` | Open |
| | **Errors, privacy, disk, crash safety, corruption (WP-2.4; generation parts WP-3.7)** | | |
| SPEC-0006-R12 | The store shall report failures only through the typed variants of `StoreError` and `IndexError` (§4.6), shall not panic on malformed database content or index files, and shall have no free-text catch-all variant. | unit `malformed_rows_yield_typed_errors`; fuzz-style property `corrupt_index_bytes_never_panic`; inspection of the enums | Open |
| SPEC-0006-R13 | No `StoreError` or `IndexError` `Display` text, `Debug` text, or `tracing` span field or event emitted by `seeky-store` shall contain passage or document text, query text, a file name, a root or file path, or the data-directory path; fields are limited to IDs, kinds, counts, sizes, sequence numbers, and durations. | unit `store_errors_contain_no_sentinels` (fixtures seeded with sentinel text, names, and paths; every variant constructed); unit `store_spans_contain_no_sentinels` (capturing `tracing-subscriber` layer) | Open |
| SPEC-0006-R14 | The store shall expose `storage_report()` returning bytes per component (SQLite main file, WAL, each index instance, embedding cache) and unit counts per generation, computed without reading user files. | unit `storage_report_sums_components`; consumed by `seeky-bench perf` (SPEC-0003-R27) | Open |
| SPEC-0006-R15 | If a write fails because the disk is full, then the writer shall roll back that transaction, resolve the affected submissions with `StoreError::DiskFull`, emit a typed `StorageEvent::DiskFull`, and reject further writes with `DiskFull` until `resume_writes()` is called, while read snapshots and searches continue to work. | fault test `disk_full_rolls_back_and_pauses_writer` (fail point returning `SQLITE_FULL`); integration `search_works_while_writer_paused` | Open |
| SPEC-0006-R16 | If the process is killed at any point of a writer commit or an index-instance commit, then on reopen the store shall be consistent: every submission resolved as durable is present, every unresolved submission is either fully present or fully absent, and no index instance contains a unit that SQLite does not. | crash test `kill_during_commit_is_atomic` (child process killed at each fail point, then reopened) | Open |
| SPEC-0006-R17 | The writer shall commit a change to SQLite, together with its outbox rows, before applying it to any index instance stored outside SQLite; on open, the store shall replay outbox entries above each external instance's `applied_through` idempotently, and shall prune outbox rows that every live external instance has applied. | unit `external_apply_follows_sqlite_commit`; crash test `outbox_replay_after_kill_converges`; property `replay_is_idempotent` | Open |
| SPEC-0006-R18 | If SQLite reports the database as corrupt or not a database when opening, then the store shall return `StoreError::Corrupt { component: Database }` without modifying or deleting any file; it shall move the database aside (into `quarantine/`) and create a fresh one only when the caller invokes `quarantine_and_recreate()`. | fault test `corrupt_db_is_reported_and_untouched`; unit `quarantine_moves_inside_data_dir_only` | Open |
| SPEC-0006-R19 | If an index instance is missing, fails its `GENERATION.json` checksum, or records an `applied_through` greater than the database's `commit_seq`, then the store shall mark it `invalid`, report its retriever unavailable in the generation snapshot, and let the engine rebuild it from SQLite and the embedding cache, while the other retrievers keep serving. | fault tests `missing_instance_is_marked_invalid`, `instance_ahead_of_db_is_invalid`, `checksum_mismatch_is_invalid`; integration `lexical_serves_while_vector_instance_rebuilds` | Open |
| | **Index backend traits (WP-2.5)** | | |
| SPEC-0006-R20 | `seeky-core` shall define the `LexicalIndex`, `FilenameIndex`, and `VectorIndex` read traits and their writer traits (§4.4) using only `seeky-core` types; `seeky-search` shall perform first-stage retrieval only through these traits and shall contain no SQL and no `rusqlite` type; the PoC `SearchStore` trait shall be removed. | inspection; `cargo tree -p seeky-search -e normal` shows no `rusqlite`; build fails if `SearchStore` is referenced | Open |
| SPEC-0006-R21 | Every backend shall return at most `limit` hits, each with a finite score where higher is better, ordered by score descending and then by unit ID ascending, containing only units committed at or before its snapshot and not deleted in it, and identical output for identical snapshot and input. | generic conformance suite `backend_conformance::*` instantiated for every backend (§6.1); property `results_sorted_bounded_finite_deterministic` | Open |
| SPEC-0006-R22 | Where a backend declares `supports_pushdown`, it shall apply a `UnitFilter` during retrieval so its hits are the top `limit` among allowed units only; where it does not, the caller shall post-filter and report the filter application as `Post` (SPEC-0002 §9.4.4), never as `Pushdown`. | conformance `pushdown_returns_top_k_of_allowed_units`; unit in `seeky-search` `non_pushdown_backend_reports_post` | Open |
| SPEC-0006-R23 | The as-built backends (FTS5 lexical with `unicode61 remove_diacritics 2`, SQL filename matching, exact f32 scan) shall sit behind the traits with no behavior change: the SPEC-0002 golden tests shall pass with the committed snapshot unchanged. | `golden_lexical`; `golden_hybrid_cpu` (`hw-tests`); conformance suite | Open |
| SPEC-0006-R24 | A vector instance shall take its dimension, element encoding, metric, modality, and space key from its `VectorSpace` (recorded with the generation), never from a constant; if a vector to insert or a query vector has another length or contains a non-finite value, then the instance shall return `IndexError::DimensionMismatch` or `IndexError::NonFiniteVector` and change nothing. | property `vector_index_accepts_any_recorded_dimension` (1..=4096); unit `wrong_length_vector_is_rejected`; unit `non_finite_vector_is_rejected`; inspection: no dimension constant in `seeky-store`, `seeky-search`, `seeky-core` | Open |
| | **Embedding channels and modality (WP-2.13)** | | |
| SPEC-0006-R25 | The store shall always contain the `text` channel; every retrieval unit shall carry a modality (`text` for passages, `image` for visual units) and a locator; the `visual_units` table shall exist in schema v2 and stay empty unless a channel declaring the `image` modality exists. | unit `text_channel_always_exists`; unit `visual_units_empty_without_image_channel` | Open |
| SPEC-0006-R26 | Each generation shall belong to exactly one channel; a channel shall have at most one `active` and at most one `building` generation; the text channel's generations shall own the lexical, filename, and text-vector components, and any other channel's generations shall own only vector components. | unit `one_active_and_one_building_per_channel` (partial unique indexes); unit `non_text_generation_rejects_lexical_component` | Open |
| SPEC-0006-R27 | Vector instances shall be partitioned by generation and modality; a vector query shall target exactly one instance and return units of one modality; no store or trait API shall merge, compare, or sum scores from two instances, and `seeky-search` shall receive one tagged ranking per instance. | unit `vector_hits_never_mix_modalities`; inspection of trait signatures (§4.4) | Open |
| SPEC-0006-R28 | While serving a text query, the store shall not open, map, or load any instance whose modality is not `text`, whether or not a visual channel exists. | unit with counting backend factory `text_query_opens_no_image_instance` | Open |
| SPEC-0006-R29 | When a generation of one channel is created, built, promoted, abandoned, or garbage-collected, the store shall not write to, invalidate, or rebuild any generation of another channel. | integration `rebuilding_text_channel_leaves_visual_channel_untouched` and the converse | Open |
| SPEC-0006-R30 | `seeky-search` shall fuse a variable-length list of first-stage rankings, each tagged with its retriever kind, channel, and modality, using ranks only; with exactly the as-built filename, lexical, and dense rankings it shall produce the golden output unchanged. | property `fusion_uses_ranks_not_raw_scores` (rescaling one ranking's scores changes nothing); `golden_lexical`, `golden_hybrid_cpu` | Open |
| | **Index generations (WP-3.7)** | | |
| SPEC-0006-R31 | Every generation shall record a canonical recipe (§4.3) from which the store derives its `space_key` (embedding-space elements) and one `build_key` per component; any change to a recipe element shall create a new generation, and an existing generation's recipe shall never change. | unit `recipe_change_creates_new_generation`; unit `generation_recipe_is_immutable`; property `space_key_ignores_build_only_elements` | Open |
| SPEC-0006-R32 | The writer shall reject a vector whose `space_key` or `parity_group` differs from the target instance's with `IndexError::SpaceMismatch`, and the embedding cache shall be keyed by `(space_key, embed_key)`, so vectors from different spaces are never stored in, read from, or compared within one instance. | unit `foreign_space_vector_is_rejected`; unit `cache_lookup_is_scoped_by_space` | Open |
| SPEC-0006-R33 | If a query vector's `space_key` differs from the active vector instance's, then the dense retriever shall return `IndexError::SpaceMismatch` and the search shall continue with the other retrievers, never silently skipping by length. | unit `query_in_foreign_space_is_typed_error`; integration `lexical_results_survive_space_mismatch` | Open |
| SPEC-0006-R34 | While a channel has a `building` generation, the active generation shall serve every search of that channel, and the writer shall apply each committed file, passage, and deletion change to every live chunking and to every live instance of both generations. | integration `active_serves_during_build`; integration `changes_during_build_reach_both_generations` | Open |
| SPEC-0006-R35 | When the engine requests promotion, the store shall promote the building generation only if its instances have applied every change up to the current `commit_seq`, its integrity checks pass, and its unit count per component is at least the active generation's; it shall make the switch in one SQLite transaction and publish the new `GenerationSnapshot` atomically, so every snapshot sees either the old or the new generation for all components, never a mix. | unit `promotion_refused_until_caught_up`; unit `promotion_refused_below_active_coverage`; concurrency test `readers_never_observe_mixed_generations` (many reader threads, barrier-driven promotion) | Open |
| SPEC-0006-R36 | While a generation is being built or promoted, no search shall fail, block on generation work, or return results from a retired generation after its snapshot was released; interference shall stay within S5. | integration `search_continues_through_model_swap` (fake `Embedder` gated by barriers); benchmark gate S5 during rebuild | Open |
| SPEC-0006-R37 | After promotion, the store shall mark the previous generation `retired` and garbage-collect it once no live snapshot references it: delete its exclusive instances and directories, its outbox rows, and the embedding-cache entries of any space no longer referenced by a non-collected or retained generation; garbage collection shall be resumable after a crash, shall delete only inside `index/` and `cache/`, and shall never touch a `retained` generation. | unit `gc_waits_for_snapshot_release`; crash test `gc_resumes_after_kill`; unit `gc_keeps_shared_and_retained_components` | Open |
| SPEC-0006-R38 | When the engine restarts with a `building` generation, it shall resume the build without re-embedding units whose vectors are committed or cached; when the engine requests a different recipe for the same channel, the store shall mark the current building generation `abandoned` and collect it. | integration `build_resumes_after_restart_without_reembedding` (counting fake `Embedder`); unit `new_request_abandons_building_generation` | Open |
| SPEC-0006-R39 | Before a build starts, the store shall estimate the bytes it needs from the recipe and current unit counts; if free space minus the estimate is below `store.disk.min_free_bytes`, then it shall refuse with `StoreError::InsufficientDisk { needed, available }` and leave the active generation serving; if free space falls below the threshold during a build, then it shall pause the build (not search) and emit `StorageEvent::LowDisk`. | unit with fake `DiskSpace` `build_refused_when_disk_insufficient`; unit `build_pauses_on_low_disk` | Open |
| SPEC-0006-R40 | The store shall expose per-channel `GenerationStatus` (active and building generation IDs, recipe summary without paths, per-component unit counts, coverage, state) for the engine; the engine shall start a generation only on an explicit recipe change and never because of detected hardware or a provider change inside one parity group (ADR-0025). | unit `generation_status_has_no_paths`; unit in `seeky-engine` `provider_change_in_parity_group_keeps_generation`; inspection | Open |

Status: `Open` → `Implemented` (code and its test merged; the WP is named, for
example `Implemented (WP-2.4)`) → `Verified` (benchmark gate passed; report
linked). The commit that implements or verifies a requirement updates its row;
the header status and the [specs index](README.md#index) follow (README rule 6).

## 4. Interfaces

Signatures are normative in shape; names of private helpers are not. All new
public types live in `seeky-core` unless stated. `seeky-core` keeps its
dependency limit (SPEC-0001-R14): only `serde` and `thiserror`.

### 4.1 Storage layout

```text
<data-dir>/                          passed in StoreConfig by seeky-engine (PoC location kept, SPEC-0002-R16)
  seeky.db, seeky.db-wal, seeky.db-shm
  index/
    gen-<generation-id>/             components built by this generation
      lexical/                       present only for a non-SQLite lexical backend
      filename/                      present only for a non-SQLite filename backend
      vectors-<modality>/            present only for a non-SQLite vector backend
      GENERATION.json                written last; see below
  cache/
    embeddings/                      only if WP-2.9 moves the cache out of SQLite
  quarantine/
    <utc-timestamp>-seeky.db         only after quarantine_and_recreate (R18)
```

- As-built backends store everything inside `seeky.db` (location `sqlite`);
  such a generation still gets a `GENERATION.json` (with no component
  directories) so that layout and recovery have one code path.
- **Shared components.** Two generations whose components have equal build
  keys share one instance; the instance lives in the directory of the
  generation that built it, and the other generation's `GENERATION.json`
  references it (`"built_by": "gen-3"`). Ownership stays logical per
  generation (glossary, ADR-0023); the physical instance is collected when no
  live generation references it (R37). See §7 Q3.
- `GENERATION.json`: `{ "format": 1, "generation_id", "channel", "recipe_key",
  "space_key", "components": [{ "kind", "modality", "backend",
  "backend_version", "build_key", "built_by", "applied_through", "files":
  [{ "name", "bytes", "blake3" }] }] }` — names are relative to the generation
  directory; no absolute path, no user path, no content. It is written to a
  temporary name, flushed, and renamed after the component files are flushed.

### 4.2 Schema v2 (SQLite DDL)

`PRAGMA journal_mode=WAL; synchronous=NORMAL; foreign_keys=ON; busy_timeout`
as built. `user_version`: 0 = empty or PoC (distinguished by fingerprint),
1 = PoC schema (logical), 2 = this schema. Later specs add columns and tables
only through numbered migrations (R3).

```sql
CREATE TABLE store_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL) WITHOUT ROWID;
-- keys: 'commit_seq' (monotonic u64 as text), 'schema_created_by' (app version)

CREATE TABLE roots (
  id TEXT PRIMARY KEY,                    -- PoC IDs kept
  path TEXT NOT NULL UNIQUE,              -- canonical absolute path (needed to watch)
  created_at INTEGER NOT NULL,
  watch_enabled INTEGER NOT NULL DEFAULT 1,
  exclusions TEXT                         -- JSON, SPEC-0007/SPEC-0008 own the content
);

CREATE TABLE files (
  id INTEGER PRIMARY KEY,                 -- internal FileId, stable across renames
  doc_id TEXT NOT NULL UNIQUE,            -- public opaque DocId (PoC IDs kept on migration)
  root_id TEXT NOT NULL REFERENCES roots(id) ON DELETE CASCADE,
  rel_path TEXT NOT NULL,                 -- root-relative, '/' separators (SPEC-0002 §9.5.5)
  path TEXT NOT NULL UNIQUE,              -- absolute, OS form
  title TEXT NOT NULL,
  ext TEXT NOT NULL,                      -- lowercase, no dot
  file_class TEXT,                        -- 'document' | 'code' | NULL (unclassified), ADR-0024
  size INTEGER NOT NULL,
  modified INTEGER NOT NULL,
  modified_ns INTEGER NOT NULL DEFAULT 0, -- 0 = unknown (legacy sentinel)
  file_key TEXT,                          -- OS file identity, SPEC-0007
  content_hash BLOB, simhash INTEGER, language TEXT,   -- filled by SPEC-0007/0008/0010 WPs
  status TEXT NOT NULL DEFAULT 'indexed',
  indexed_at INTEGER NOT NULL,
  UNIQUE (root_id, rel_path)
);
CREATE INDEX idx_files_root ON files(root_id);
CREATE INDEX idx_files_ext ON files(ext);
CREATE INDEX idx_files_modified ON files(modified_ns);
CREATE INDEX idx_files_size ON files(size);

CREATE TABLE file_contents (file_id INTEGER PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE,
                            text TEXT NOT NULL);           -- document view; §7 Q8

CREATE TABLE chunkings (id INTEGER PRIMARY KEY, chunking_key TEXT NOT NULL UNIQUE,
                        recipe TEXT NOT NULL);              -- canonical JSON; 'poc-v1' on migration

CREATE TABLE passages (
  id INTEGER PRIMARY KEY,                 -- PassageId (PoC chunk IDs kept on migration)
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  chunking_id INTEGER NOT NULL REFERENCES chunkings(id),
  ordinal INTEGER NOT NULL,
  text TEXT NOT NULL,
  start_offset INTEGER NOT NULL, end_offset INTEGER NOT NULL,
  page INTEGER,
  locator TEXT,                           -- JSON {page|slide|sheet,row,col|line}
  heading_path TEXT, token_len INTEGER,
  text_hash BLOB,                         -- blake3 of passage text
  source TEXT NOT NULL DEFAULT 'extracted', -- 'extracted' | 'ocr'
  UNIQUE (file_id, chunking_id, ordinal)
);
CREATE INDEX idx_passages_chunking ON passages(chunking_id, file_id);

CREATE TABLE visual_units (               -- empty unless an image-modality channel exists (R25)
  id INTEGER PRIMARY KEY,
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  ordinal INTEGER NOT NULL,
  kind TEXT NOT NULL,                     -- 'image' | 'slide' | 'figure' | 'page_region'
  locator TEXT NOT NULL, width INTEGER, height INTEGER,
  content_hash BLOB NOT NULL,
  UNIQUE (file_id, ordinal)
);

CREATE TABLE channels (id TEXT PRIMARY KEY,       -- 'text' always; e.g. 'visual'
                       modalities TEXT NOT NULL,  -- JSON array, e.g. ["text"] or ["text","image"]
                       created_at INTEGER NOT NULL);

CREATE TABLE generations (
  id INTEGER PRIMARY KEY,
  channel_id TEXT NOT NULL REFERENCES channels(id),
  state TEXT NOT NULL,                    -- 'building'|'active'|'retired'|'abandoned'|'collected'
  recipe TEXT NOT NULL, recipe_key TEXT NOT NULL,
  space_key TEXT,                         -- NULL for a lexical-only text generation
  chunking_id INTEGER REFERENCES chunkings(id), -- text channel only
  retained INTEGER NOT NULL DEFAULT 0,    -- ADR-0025 item 6 room; never collected while 1
  created_at INTEGER NOT NULL, promoted_at INTEGER, retired_at INTEGER
);
CREATE UNIQUE INDEX one_active_per_channel ON generations(channel_id) WHERE state = 'active';
CREATE UNIQUE INDEX one_building_per_channel ON generations(channel_id) WHERE state = 'building';

CREATE TABLE index_instances (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,                     -- 'lexical' | 'filename' | 'vector'
  modality TEXT,                          -- vector only
  backend TEXT NOT NULL, backend_version INTEGER NOT NULL,
  build_key TEXT NOT NULL UNIQUE,
  space_key TEXT, parity_group TEXT, dimension INTEGER, encoding TEXT, metric TEXT, -- vector only
  location TEXT NOT NULL,                 -- 'sqlite' or 'index/gen-<id>/<dir>' (relative)
  state TEXT NOT NULL,                    -- 'building' | 'ready' | 'invalid'
  applied_through INTEGER NOT NULL DEFAULT 0,
  units INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE generation_components (
  generation_id INTEGER NOT NULL REFERENCES generations(id),
  instance_id INTEGER NOT NULL REFERENCES index_instances(id),
  PRIMARY KEY (generation_id, instance_id)
) WITHOUT ROWID;

-- As-built lexical instance: one external-content FTS5 table per instance,
-- maintained by the writer (no triggers), named lexical_fts_<instance_id>:
--   CREATE VIRTUAL TABLE lexical_fts_<n> USING fts5(text, content='passages',
--     content_rowid='id', tokenize='unicode61 remove_diacritics 2');
-- As-built vector instance: unit → cache-key mapping; vector bytes live once,
-- in embedding_cache (no duplicate copy, R4 budget; WP-2.9 may change this).
CREATE TABLE vector_entries (
  instance_id INTEGER NOT NULL REFERENCES index_instances(id),
  unit_kind TEXT NOT NULL,                -- 'passage' | 'visual'
  unit_id INTEGER NOT NULL,
  embed_key BLOB NOT NULL,
  PRIMARY KEY (instance_id, unit_kind, unit_id)
) WITHOUT ROWID;

CREATE TABLE embedding_cache (
  space_key TEXT NOT NULL,
  embed_key BLOB NOT NULL,                -- blake3 of the embedding input recipe output
  encoding TEXT NOT NULL,                 -- 'f32le' as built; others by WP-2.9
  dimension INTEGER NOT NULL,
  vector BLOB NOT NULL,
  created_at INTEGER NOT NULL,
  PRIMARY KEY (space_key, embed_key)
) WITHOUT ROWID;

CREATE TABLE index_outbox (               -- only for instances stored outside SQLite (R17)
  seq INTEGER NOT NULL, instance_id INTEGER NOT NULL,
  unit_kind TEXT NOT NULL, unit_id INTEGER NOT NULL, op TEXT NOT NULL, -- 'upsert'|'delete'
  PRIMARY KEY (instance_id, seq, unit_kind, unit_id)
) WITHOUT ROWID;

CREATE TABLE jobs (                        -- skeleton; semantics in SPEC-0007
  id INTEGER PRIMARY KEY, root_id TEXT NOT NULL REFERENCES roots(id) ON DELETE CASCADE,
  rel_path TEXT NOT NULL, kind TEXT NOT NULL, priority INTEGER NOT NULL,
  attempts INTEGER NOT NULL DEFAULT 0, not_before INTEGER, last_error_kind TEXT,
  UNIQUE (root_id, rel_path)
);

CREATE TABLE models (                      -- skeleton; semantics in SPEC-0005
  id TEXT NOT NULL, revision TEXT NOT NULL, manifest TEXT NOT NULL,
  state TEXT NOT NULL, verified_at INTEGER,
  PRIMARY KEY (id, revision)
) WITHOUT ROWID;

CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
```

PoC → v2 mapping (R4, R5): `roots` → `roots`; `documents` → `files`
(`doc_id` = old `id`, `rel_path` computed from the root path, `file_class`
NULL until reconcile classifies it) and `file_contents`; `chunks` →
`passages` (IDs kept) under chunking `poc-v1`; `chunks_fts` and its triggers →
dropped and rebuilt as `lexical_fts_<n>` with the FTS5 `rebuild` command;
`embeddings` → dropped; `settings` → `settings`. The migration creates channel
`text`, one lexical instance, one filename instance (`location = 'sqlite'`, no
data of its own), and generation 1 (`active`, `space_key` NULL, chunking
`poc-v1`). When a model is configured, the engine then starts generation 2
with the same chunking, which shares both instances and is promotable at once
(§5.4).

### 4.3 Generation recipe and keys

```rust
pub struct ChannelId(pub String);            // "text" always exists
pub struct GenerationId(pub i64);
pub struct ChangeSeq(pub u64);
pub enum Modality { Text, Image }

pub struct GenerationRecipe {                // canonical JSON (sorted keys, compact), versioned
    pub format: u16,                         // 1
    pub channel: ChannelId,
    pub space: Option<SpaceRecipe>,          // None = lexical-only text generation
    pub chunking_key: Option<String>,        // text channel only; from SPEC-0008
    pub lexical: Option<BackendChoice>,      // text channel only; analyzer config inside
    pub filename: Option<BackendChoice>,     // text channel only
    pub vectors: Vec<VectorChoice>,          // one per modality the channel embeds
}
pub struct SpaceRecipe {                     // the embedding-space elements (ADR-0019 decision 7)
    pub space_id: String,                    // manifest `space` (SPEC-0005)
    pub model_id: String, pub revision: String,
    pub dimension: u32,                      // incl. Matryoshka truncation
    pub tokenizer_revision: String,
    pub input_recipe_version: u32,           // heading path + text; never filename/path
    pub parity_group: String,                // variants/providers that passed parity share it
    pub image_preprocessing: Option<String>, // recipe ID; image modality only
}
pub struct BackendChoice { pub backend: String, pub backend_version: u32, pub config: String /* canonical JSON */ }
pub struct VectorChoice { pub modality: Modality, pub backend: BackendChoice, pub encoding: String, pub metric: Metric }
pub enum Metric { Dot, Cosine }
```

- `recipe_key = blake3(canonical recipe)`; `space_key = blake3(canonical
  SpaceRecipe)`; component `build_key = blake3(kind, inputs)` where the
  inputs are: lexical → (`chunking_key`, `lexical`); filename → (`filename`);
  vector → (`space_key`, `chunking_key` for text or visual-unit rules version
  for image, the `VectorChoice`). Keys are computed in `seeky-store` (which
  already depends on `blake3`) and carried in `seeky-core` as lowercase hex
  strings.
- Precision: the variant used to embed is not part of `space_key`; its
  `parity_group` is. A variant or provider that has not passed parity against
  the group's reference has no parity group and cannot write (R32; parity
  itself is SPEC-0005/SPEC-0012). This is how ADR-0019 decision 7 ("share a
  generation only when they pass the vector-parity threshold") is applied.
- Vector storage quantization (int8, binary) is part of the `VectorChoice`,
  hence of the vector build key but not of the space key.

### 4.4 Index traits (in `seeky-core`)

```rust
pub struct FileId(pub i64);
pub struct PassageId(pub i64);
pub struct VisualUnitId(pub i64);
pub enum UnitRef { Passage(PassageId), Visual(VisualUnitId) }

pub struct Scored<U> { pub unit: U, pub score: f32 }  // finite; higher is better

pub enum UnitFilter<'a> { All, Files(&'a FileSet) }   // FileSet: sorted, deduplicated FileIds
                                                      // built by the store from SPEC-0002 filters

pub struct BackendDescriptor {
    pub kind: IndexKind,                     // Lexical | Filename | Vector
    pub backend: &'static str,               // e.g. "fts5", "sql-filename", "exact-f32"
    pub backend_version: u32,
    pub build_key: String,
    pub supports_pushdown: bool,
}
pub struct VectorSpace {
    pub space_key: String, pub parity_group: String,
    pub modality: Modality, pub dimension: u32, pub encoding: String, pub metric: Metric,
}

pub struct LexicalQuery { pub text: String /* normalized; never logged */ }
pub struct FilenameQuery { pub text: String }

pub trait LexicalIndex: Send + Sync {
    fn descriptor(&self) -> &BackendDescriptor;
    fn search(&self, q: &LexicalQuery, filter: UnitFilter<'_>, limit: usize)
        -> Result<Vec<Scored<PassageId>>, IndexError>;
}
pub trait FilenameIndex: Send + Sync {
    fn descriptor(&self) -> &BackendDescriptor;
    fn search(&self, q: &FilenameQuery, filter: UnitFilter<'_>, limit: usize)
        -> Result<Vec<Scored<FileId>>, IndexError>;
}
pub trait VectorIndex: Send + Sync {
    fn descriptor(&self) -> &BackendDescriptor;
    fn space(&self) -> &VectorSpace;
    fn search(&self, query: &QueryVector<'_>, filter: UnitFilter<'_>, limit: usize)
        -> Result<Vec<Scored<UnitRef>>, IndexError>;
}
pub struct QueryVector<'a> { pub space_key: &'a str, pub values: &'a [f32] }

// Writer side: owned and driven only by the store-writer actor (R7).
pub enum PassageChange<'a> { Upsert { id: PassageId, file: FileId, text: &'a str }, Delete { id: PassageId } }
pub enum FileChange<'a>    { Upsert { id: FileId, title: &'a str, rel_path: &'a str }, Delete { id: FileId } }
pub enum VectorChange<'a>  { Upsert { unit: UnitRef, space_key: &'a str, parity_group: &'a str,
                                      values: &'a [f32] }, Delete { unit: UnitRef } }

pub trait LexicalIndexWriter: Send {
    fn apply(&mut self, changes: &[PassageChange<'_>]) -> Result<(), IndexError>;
    fn commit(&mut self, through: ChangeSeq) -> Result<(), IndexError>; // durable, records applied_through
    fn applied_through(&self) -> ChangeSeq;
}
// FilenameIndexWriter (FileChange) and VectorIndexWriter (VectorChange) have the same shape.
```

- `FilenameIndex` returns files; the as-built mapping of a file hit to its
  ordinal-0 passage (PoC `filename_chunks`) moves into `seeky-search` so the
  golden output is unchanged (R23).
- In-SQLite backends implement the writer by executing inside the writer's
  open transaction (their `commit` is a no-op that the transaction makes
  durable); external backends implement it with their own durable commit
  after the SQLite commit (R17).
- Backend factories and the `IndexBackends` registry (backend name →
  constructor) live in `seeky-store`; `seeky-core` holds only the traits.

### 4.5 Store API (in `seeky-store`)

```rust
pub struct StoreConfig {
    pub data_dir: PathBuf,
    pub reader_pool_size: usize,     // store.readers.pool_size; default 4; owner WP-1.6/S5
    pub max_batch_units: usize,      // store.writer.max_batch_units; default 512; owner WP-3.2 (I1)
    pub max_batch_ms: u64,           // store.writer.max_batch_ms; default 500 (indexing.md §2.5)
    pub writer_queue: usize,         // store.writer.queue_capacity; default 1024 (backpressure)
    pub min_free_bytes: u64,         // store.disk.min_free_bytes; default open, §7 Q5
    pub backends: BackendDefaults,   // store.backends.{lexical,filename,vector}; as-built until WP-2.7–2.9 ADRs
}

pub struct Store { /* Arc<inner>; Clone + Send + Sync */ }
impl Store {
    pub fn open(config: StoreConfig, disk: Arc<dyn DiskSpace>) -> Result<Store, StoreError>;
    pub fn writer(&self) -> WriterHandle;                       // cheap clone; submits to the actor
    pub fn read(&self) -> Result<ReadSnapshot, StoreError>;     // R11
    pub fn generation_status(&self) -> Result<Vec<GenerationStatus>, StoreError>; // R40
    pub fn storage_report(&self) -> Result<StorageReport, StoreError>;           // R14
    pub fn resume_writes(&self) -> Result<(), StoreError>;                       // R15
    pub fn quarantine_and_recreate(config: &StoreConfig) -> Result<(), StoreError>; // R18
    pub fn subscribe(&self) -> StorageEventReceiver;           // typed StorageEvent
    pub fn shutdown(self) -> Result<(), StoreError>;           // drains the writer queue
}

impl WriterHandle {
    pub fn submit(&self, cmd: WriteCommand) -> Result<Pending<ChangeSeq>, StoreError>; // blocks only on a full queue
}
pub enum WriteCommand {
    UpsertFile(FileRecord, Vec<PassageRecord>),   // fast-lane commit, all live chunkings
    DeleteFile(FileId), RenameFile { id: FileId, rel_path: String, path: String },
    PutVectors { generation: GenerationId, entries: Vec<VectorRecord> }, // semantic lane
    PutCache(Vec<CacheRecord>),
    BeginGeneration(GenerationRecipe), Promote(GenerationId), Abandon(GenerationId),
    CollectGarbage, Settings(Vec<(String, String)>), /* roots, jobs, models: per SPEC-0007/0005 */
}

pub struct ReadSnapshot { /* one read txn + Arc<GenerationSnapshot> per channel */ }
impl ReadSnapshot {
    pub fn channel(&self, id: &ChannelId) -> Option<&GenerationSnapshot>;
    pub fn filter_files(&self, filter: &MetadataFilter) -> Result<FileSet, StoreError>; // SPEC-0002 §9.4.3
    pub fn hydrate_passages(&self, ids: &[PassageId]) -> Result<Hydrated<PassageView>, StoreError>;
    pub fn hydrate_files(&self, ids: &[FileId]) -> Result<Hydrated<FileView>, StoreError>;
}
pub struct GenerationSnapshot {
    pub generation: GenerationId, pub channel: ChannelId,
    pub lexical: Retriever<Arc<dyn LexicalIndex>>,      // text channel only
    pub filename: Retriever<Arc<dyn FilenameIndex>>,    // text channel only
    pub vectors: Vec<(Modality, Retriever<Arc<dyn VectorIndex>>)>, // opened lazily per modality (R28)
}
pub enum Retriever<T> { Ready(T), Unavailable(UnavailableReason), Absent }
pub trait DiskSpace: Send + Sync { fn free_bytes(&self) -> std::io::Result<u64>; } // real + fake (tests)
```

The store API is synchronous. The search pipeline takes its `ReadSnapshot`
after the query embedding is computed and drops it before returning, so no
snapshot spans inference (R10).

### 4.6 Errors and events

```rust
// seeky-core
#[derive(Debug, thiserror::Error)]
pub enum IndexError {
    #[error("vector dimension mismatch: expected {expected}, got {got}")] DimensionMismatch { expected: u32, got: u32 },
    #[error("vector contains a non-finite value")]                     NonFiniteVector,
    #[error("embedding space mismatch")]                               SpaceMismatch,
    #[error("index component {kind:?} is corrupt")]                    Corrupt { kind: IndexKind },
    #[error("index component {kind:?} is unavailable")]                Unavailable { kind: IndexKind },
    #[error("disk full")]                                              DiskFull,
    #[error("index I/O error: {0:?}")]                                 Io(std::io::ErrorKind),
    #[error("backend {backend} error code {code}")]                    Backend { backend: &'static str, code: i32 },
}

// seeky-store (replaces Error::Message(String))
#[derive(Debug, thiserror::Error)]
pub enum StoreError {
    #[error("database schema {found} is newer than supported {supported}")] SchemaTooNew { found: u32, supported: u32 },
    #[error("database schema not recognized")]                  UnrecognizedSchema,
    #[error("migration from {from} to {to} failed")]            MigrationFailed { from: u32, to: u32 },
    #[error("{component:?} is corrupt")]                        Corrupt { component: StoreComponent },
    #[error("disk full")]                                       DiskFull,
    #[error("insufficient disk: need {needed} bytes, {available} available")] InsufficientDisk { needed: u64, available: u64 },
    #[error("writer stopped")]                                  WriterClosed,
    #[error("writes paused")]                                   WritesPaused,
    #[error("generation conflict: {0:?}")]                      GenerationConflict(GenerationConflict),
    #[error("not found: {0:?}")]                                NotFound(EntityKind),
    #[error("sqlite error code {0}")]                           Sqlite(i32),     // extended result code only
    #[error("io error: {0:?}")]                                 Io(std::io::ErrorKind),
    #[error(transparent)]                                       Index(#[from] IndexError),
}

pub enum StorageEvent { DiskFull, LowDisk { available: u64 }, InstanceInvalid { generation: GenerationId, kind: IndexKind },
                        GenerationStateChanged { channel: ChannelId, generation: GenerationId, state: GenerationState } }
```

`EngineError::Storage(#[from] seeky_store::Error)` (SPEC-0002 §4.3) is kept;
`seeky_store::Error` becomes an alias of `StoreError`. Message texts may change;
the conditions that produced a PoC error still produce an error.

## 5. Behavior details

### 5.1 Writer actor

- One OS thread owns the only write connection and every index writer. It
  receives `WriteCommand`s over a bounded channel (`writer_queue`); a full
  queue is the indexing pipeline's backpressure signal (overview §4 rule 4).
- Loop: take the first command, keep taking until `max_batch_units` units or
  `max_batch_ms` elapsed (fake clock in tests), `BEGIN IMMEDIATE`, apply all
  commands, bump `commit_seq`, write outbox rows for external instances,
  `COMMIT`, then apply to external instances and commit them, then resolve
  each `Pending` with the `commit_seq`. A command that fails validation (for
  example `DimensionMismatch`) fails alone: the batch is retried without it.
- `UpsertFile` writes the file row and passages for every chunking referenced
  by a live (`active` or `building`) text generation (R34); the chunker output
  for each chunking is prepared by the caller. Before deleting or replacing a
  passage the writer removes it from each in-SQLite FTS5 instance (external
  content tables need the old text).
- Shutdown drains the queue, commits, and joins the thread (SPEC-0002-R14).

### 5.2 Readers and snapshots

- A pool of `reader_pool_size` connections opened with `query_only=ON`. A
  `ReadSnapshot` starts a deferred read transaction and clones the current
  `Arc<GenerationSnapshot>` per channel. The published snapshot pointer is
  replaced under a `std::sync::RwLock<Arc<…>>` held only for the pointer swap
  or clone, never across I/O (no new dependency).
- Hydration is authoritative: an index hit whose unit is not in the read
  transaction is dropped and counted in `Hydrated::dropped`, which feeds
  search telemetry. Deleted files are therefore never shown (vision §6).
- Read transactions are short (one search); long reads would starve WAL
  checkpoints. Checkpointing stays SQLite's automatic one until WP-8.2 measures
  otherwise.

### 5.3 Generation state machine

```text
  BeginGeneration ─► building ──Promote(ok)──► active ──(next promotion)──► retired ──GC──► collected
                        │                                                       ▲
                        └── new recipe for channel / user cancel ──► abandoned ─┘ (GC)
```

- `BeginGeneration` computes keys, reuses every instance whose build key
  already exists (shared component), creates `building` instances for the
  rest, and returns the generation ID. A second request for the same channel
  abandons the current `building` one (R38).
- The engine's generation manager (`seeky-engine`) drives the build: it reads
  passages and the embedding cache through read snapshots, embeds misses with
  the indexing-pool embedder (no store lock held, R10), and submits
  `PutVectors`/`PutCache`. Priority relative to the active generation's
  semantic backlog is SPEC-0007's; this spec requires only that the active
  generation keeps serving (R34, R36).
- **Promotion rule** (R35): caught up (`applied_through = commit_seq` for every
  building instance), integrity checks (unit counts match SQLite; external
  instance files match `GENERATION.json` checksums), and coverage per
  component ≥ the active generation's. In the steady state the active
  generation is complete, so this means full coverage (indexing.md §3). When
  the active text generation is lexical-only (first model after install or
  after PoC migration) the candidate shares the lexical and filename instances
  and its vector coverage starts at 0 ≥ 0, so it is promoted at once and
  semantic coverage grows in place, as ADR-0018 requires. See §7 Q2.
- Promotion: one transaction sets old `active` → `retired`, new → `active`,
  `promoted_at`; after commit the writer publishes the new snapshot pointer.
  Readers holding the old `Arc` finish on the old generation.
- GC (R37) runs as a writer command when the retired generation's
  `Arc` strong count reaches one (only the registry's): it marks rows, deletes
  directories under `index/` (path checked to be inside it), deletes
  `vector_entries`, FTS tables, and outbox rows of exclusive instances, then
  deletes cache rows whose `space_key` no live or retained generation uses.
  Every step is idempotent; on open, the store finishes any generation in
  `retired`/`abandoned` whose files or rows still exist.
- A `retained` generation (ADR-0025 item 6, post-1.0) is never collected and
  never served; re-promoting it is out of scope for v0.1.

### 5.4 Space safety

- The query embedder for a channel is chosen from the active generation's
  `SpaceRecipe` (engine/infer); the query vector carries its `space_key`; the
  vector instance compares keys and returns `SpaceMismatch` otherwise (R33).
  This replaces the PoC `seeky_infer::DIM` length check.
- A unified multimodal model is one channel with modalities `["text","image"]`
  and two vector instances (one per modality) sharing one `space_key`. They
  are still queried separately and fused by rank (R27, ADR-0023 decision 1.5).
- Changing provider or precision inside a parity group writes into the same
  generation; outside it, the engine must either fall back to a variant in the
  group (ADR-0025 item 1) or request a new recipe explicitly (R40). This closes
  audit A5 together with SPEC-0005.

### 5.5 Crash consistency and recovery on open

1. Open SQLite; check `user_version` and fingerprint (R2, R6); migrate (R3).
   A SQLite corruption code → `Corrupt { Database }` (R18). No full
   `integrity_check` on open (R5 cold start); `quick_check` is WP-8.2's call.
2. For each live generation's instances: verify presence and
   `GENERATION.json` checksums (external only) and `applied_through ≤
   commit_seq`; mark failures `invalid` (R19).
3. Replay outbox entries above each external instance's `applied_through`
   (R17), then prune.
4. Finish interrupted GC (R37). Delete `index/gen-*` directories that no
   generation row references (only names matching the pattern, only inside
   `index/`).
5. Publish snapshots. The engine schedules rebuilds of invalid instances and
   resumes `building` generations (R38).

`synchronous=NORMAL` (as built) means a power loss can roll back the last
committed transactions; the store stays consistent and durable jobs replay
(SPEC-0007). See §7 Q14.

### 5.6 Disk

- `storage_report()` sums file sizes under the data directory by component
  and SQLite page counts per table (`dbstat` when compiled in, otherwise file
  totals only, reported as such).
- Build estimate: `units × bytes_per_unit(encoding, dimension)` for each new
  vector instance + lexical/filename estimate from the current instance sizes
  when they are not shared + 10 % slack. The estimate formula is provisional
  and checked against measured R4 numbers in the WP-3.7 report.
- `DiskSpace` is a trait so tests inject free-space values; the production
  implementation queries the volume of the data directory.

### 5.7 Privacy

- `tracing` spans: `store.open`, `store.migrate`, `store.write_batch`,
  `store.read`, `store.hydrate`, `store.gc`, `generation.begin`,
  `generation.promote`, `index.<kind>.search`. Fields: IDs, counts, sizes,
  `commit_seq`, durations, backend name, error kind.
- `rusqlite` errors are converted to their extended result code; SQL text,
  bound parameters, and paths are never placed in an error (R13).
- `GENERATION.json`, `generation_status()`, and `storage_report()` contain no
  path, file name, or content.

## 6. Acceptance

### 6.1 Tests

Written first, hardware-free unless marked; fixtures are synthetic and live in
`crates/seeky-store/tests/fixtures/` (including the frozen PoC DDL as SQL).
Crash tests run a child process (the test binary re-invoked with an
environment variable selecting a fail point) and kill it; they are integration
tests in `crates/seeky-store/tests/` and say so in their doc comment.

| Test | Layer | Requirements |
|---|---|---|
| `store_writes_only_under_data_dir`, `db_records_relative_locations_only`, `gc_refuses_paths_outside_index_dir` | unit / fault | R1, R37 |
| `empty_db_gets_latest_schema`, `current_db_open_runs_no_ddl` | unit | R2 |
| `each_migration_step_is_one_transaction`, `failed_migration_leaves_db_at_previous_version` | unit / fault | R3 |
| `poc_db_migrates_without_loss`, `poc_migration_preserves_lexical_and_filename_results`, `poc_vectors_are_not_imported` | integration | R4, R5 |
| `newer_schema_is_refused_without_writes`, `unknown_schema_is_refused_without_writes` | unit | R6 |
| `reader_connections_reject_writes` | unit | R7 |
| `writer_batches_respect_unit_and_time_bounds`, `committed_write_visible_to_next_snapshot` | unit | R8 |
| `search_completes_while_writer_txn_is_open` | integration | R9 |
| `writer_api_takes_prepared_data_only` + inspection | unit | R10 |
| `snapshot_pins_one_committed_state`, `hydration_drops_units_deleted_after_index_read` | unit | R11 |
| `malformed_rows_yield_typed_errors`, `corrupt_index_bytes_never_panic` (proptest) | unit / property | R12 |
| `store_errors_contain_no_sentinels`, `store_spans_contain_no_sentinels` | unit | R13 |
| `storage_report_sums_components` | unit | R14 |
| `disk_full_rolls_back_and_pauses_writer`, `search_works_while_writer_paused` | fault / integration | R15 |
| `kill_during_commit_is_atomic` | crash | R16 |
| `external_apply_follows_sqlite_commit`, `outbox_replay_after_kill_converges`, `replay_is_idempotent` | unit / crash / property | R17 (with a fake external backend in tests) |
| `corrupt_db_is_reported_and_untouched`, `quarantine_moves_inside_data_dir_only` | fault / unit | R18 |
| `missing_instance_is_marked_invalid`, `instance_ahead_of_db_is_invalid`, `checksum_mismatch_is_invalid`, `lexical_serves_while_vector_instance_rebuilds` | fault / integration | R19 |
| inspection + `cargo tree` check | inspection | R20 |
| `backend_conformance::*` (sorted, bounded, finite, deterministic, tie order, deleted units absent, snapshot isolation), `results_sorted_bounded_finite_deterministic` | unit / property, instantiated per backend | R21 |
| `pushdown_returns_top_k_of_allowed_units`, `non_pushdown_backend_reports_post` | unit | R22 |
| `golden_lexical`, `golden_hybrid_cpu` (`hw-tests`), unchanged snapshot | integration | R23, R30 |
| `vector_index_accepts_any_recorded_dimension`, `wrong_length_vector_is_rejected`, `non_finite_vector_is_rejected` | property / unit | R24 |
| `text_channel_always_exists`, `visual_units_empty_without_image_channel` | unit | R25 |
| `one_active_and_one_building_per_channel`, `non_text_generation_rejects_lexical_component` | unit | R26 |
| `vector_hits_never_mix_modalities` | unit | R27 |
| `text_query_opens_no_image_instance` | unit | R28 |
| `rebuilding_text_channel_leaves_visual_channel_untouched` (+ converse) | integration | R29 |
| `fusion_uses_ranks_not_raw_scores` | property (`seeky-search`) | R30 |
| `recipe_change_creates_new_generation`, `generation_recipe_is_immutable`, `space_key_ignores_build_only_elements` | unit / property | R31 |
| `foreign_space_vector_is_rejected`, `cache_lookup_is_scoped_by_space` | unit | R32 |
| `query_in_foreign_space_is_typed_error`, `lexical_results_survive_space_mismatch` | unit / integration | R33 |
| `active_serves_during_build`, `changes_during_build_reach_both_generations` | integration | R34 |
| `promotion_refused_until_caught_up`, `promotion_refused_below_active_coverage`, `readers_never_observe_mixed_generations` | unit / concurrency | R35 |
| `search_continues_through_model_swap` | integration (`seeky-engine`, fake `Embedder`) | R36 |
| `gc_waits_for_snapshot_release`, `gc_resumes_after_kill`, `gc_keeps_shared_and_retained_components` | unit / crash | R37 |
| `build_resumes_after_restart_without_reembedding`, `new_request_abandons_building_generation` | integration / unit | R38 |
| `build_refused_when_disk_insufficient`, `build_pauses_on_low_disk` | unit | R39 |
| `generation_status_has_no_paths`, `provider_change_in_parity_group_keeps_generation` | unit | R40 |

Concurrency tests synchronize with barriers and channels, never sleeps
(AGENTS.md §6 Tests). Unit tests never assert ranking quality.

### 6.2 Benchmark gates

Budgets are provisional until the "Locked budgets v1" ADR (WP-1.7); until
then the gate is "no regression outside the CI versus the B0 report".

| Gate | Dataset/split | Tier | Threshold | Baseline report |
|---|---|---|---|---|
| S1, S2 (WP-2.4/2.5: store v2 + traits) | `sdc-s` | T1 CPU-only | no regression vs B0 outside CI; then the locked budget | B0 (WP-1.7) |
| I1 (writer batching) | `sdc-s` | T1 CPU-only | ≤ 2 s p95 | B0 |
| S5 during a generation rebuild (WP-3.7) | `sdc-s` | T1 CPU-only | ≤ 1.5 | B1/B2 |
| R3 peak RSS during a model swap (two embedders resident) | `sdc-m` | T1 CPU-only | ≤ 1.5 GB | B2 |
| R4 disk per 1M passages, steady state; transient peak during rebuild reported | `sdc-m` | T1 | ≤ 2.5 GB steady state | WP-2.9 report |
| R5 cold start to Instant-capable, including schema check and recovery steps | `sdc-s` | T1 | ≤ 1.5 s | B0 |
| V4 (only when a visual channel exists) | `sdc-s` visual slice | T1 CPU-only | S2 still met | Phase 10 |

The WP-2.4 PR also reports the PoC → v2 migration duration on an `sdc-s`-sized
PoC database (no budget; §7 Q11).

### 6.3 Inspection

- `seeky-core` depends only on `serde` and `thiserror`; `seeky-search` has no
  `rusqlite` dependency and no SQL; `seeky-store` depends on neither
  `seeky-infer` nor `seeky-extract` (SPEC-0001 §4.4).
- No dimension, model ID, tensor name, or path constant in `seeky-store`,
  `seeky-search`, or `seeky-core` (P8).
- No code path starts a generation from hardware detection, provider change
  within a parity group, or a governor mode change (ADR-0025, SPEC-0007-R7).
- Exactly one place constructs the write connection.
- No `unwrap`/`expect` on database or index I/O paths.

## 7. Risks and open questions

| # | Question or risk | Proposed default in this draft | Who decides / when | Blocking acceptance? |
|---|---|---|---|---|
| Q1 | PoC vectors on migration: drop them (R5) or import them into a `poc-legacy` generation when every vector has one length? Import cannot rule out the mixed-backend problem (A5). | Drop; re-embed in the background; lexical search works immediately | Maintainer, at H7 | Yes |
| Q2 | Promotion rule "coverage ≥ active per component" refines indexing.md §3 "full coverage" so the first model after a lexical-only start activates progressively (ADR-0018). Accept the refinement, or require full coverage always and treat the lexical-only case as a special in-place attach? | Coverage ≥ active (§5.3) | Maintainer, at H7 | Yes |
| Q3 | Physical sharing of instances across generations by build key, with `GENERATION.json` references (§4.1), versus strictly separate `gen-<id>/` contents per generation (overview §5). Sharing avoids rebuilding FTS5 on every model swap. | Share | Maintainer, at H7 | Yes |
| Q4 | Doc conflict: overview §5 and indexing.md §2.6 key the embedding cache by "(unit hash, generation)", while indexing.md §3, ADR-0023 decision 1.2, and the glossary require reuse across generations of one space. This draft keys by `(space_key, embed_key)`. | Correct overview §5 and indexing.md §2.6 in a docs commit | Orchestrator (docs fix) | No |
| Q5 | Default `store.disk.min_free_bytes` and the build-estimate formula. | Provisional 1 GiB or 5 % of the volume, whichever is smaller; measured in WP-3.7 | Maintainer; WP-3.7 report | No |
| Q6 | Keep embedding-cache entries of a retired space for a while (fast rollback) or delete at GC (disk, R4)? | Delete at GC unless `retained` | Maintainer, WP-3.7 | No |
| Q7 | Chunking depends on the embedding model's tokenizer (indexing.md §2.4). A lexical-only generation has no model tokenizer, so the first model may change the chunking key and force a full re-chunk and lexical rebuild. | Raise with SPEC-0008 / WP-2.10 (a model-independent chunking key would avoid it) | SPEC-0008 author | No |
| Q8 | Full document text (`file_contents`) doubles passage text on disk; compression would need a new dependency (ADR-0022 review). | Keep uncompressed in WP-2.4; measure in the R4 report | Maintainer; WP-2.9/WP-8.1 | No |
| Q9 | Public API for model selection, rebuild progress, and generation status (needed by WP-7.6 diagnostics) belongs to SPEC-0002 v2; WP-3.7 tests use the engine-internal generation manager. | Defer to SPEC-0002 v2 (WP-4.3) | Maintainer | No |
| Q10 | After `quarantine_and_recreate`, roots are lost unless they can be read from the corrupt file. Keep a small roots sidecar (`roots.json`, paths only, local) or ask the user to re-add folders? | Ask the user (SPEC-0014 flow); no sidecar | Maintainer | No |
| Q11 | PoC → v2 migration time on a large PoC database (FTS5 rebuild) is unbudgeted and runs at open. | Report it in WP-2.4; show progress if > R5 | Maintainer | No |
| Q12 | The `jobs` and `models` tables are skeletons; SPEC-0007 and SPEC-0005 may change them through later migrations. | Accept skeletons | Spec authors | No |
| Q13 | Lexical analyzer changes (WP-3.9 language analyzers) create a new text generation because the lexical build key changes, even with the same model. | Accept; vectors are shared by build key, so only the lexical instance is rebuilt | Maintainer | No |
| Q14 | `synchronous=NORMAL` (as built) versus `FULL`: NORMAL may lose the last transactions on power loss (never corrupts). | Keep NORMAL; durable jobs replay | Maintainer; WP-8.2 crash tests | No |
| R-a | Two embedders resident during a model swap (old for queries, new for indexing) may exceed R3 on `sdc-m`. | Measure in WP-3.7; the governor's memory ceiling (SPEC-0007) may serialize | WP-3.7 | No |
| R-b | External backends (Tantivy, USearch) chosen by WP-2.7/2.9 must implement `applied_through` and idempotent replay; a backend that cannot is ineligible. | Add to the bake-off eligibility checklist | WP-2.7, WP-2.9 owners | No |

Document conflicts found while drafting (none blocks a coherent draft):
Q4 (cache key); indexing.md §3 and inference-and-models §6 list embedding
precision in the recipe, while ADR-0019 decision 7 lets parity-passing
variants share a generation — this draft follows the ADR (`parity_group`,
§4.3); overview §5's per-generation directories versus sharing (Q3); the
generation recipe in the glossary and indexing.md §3 omits lexical, filename,
and vector backend choices even though the text generation owns those indexes
(this draft adds build keys, §4.3); "full coverage" promotion versus ADR-0018
progressive activation (Q2).

## 8. Changelog

| Version | Date | Change |
|---|---|---|
| 0.1 | 2026-11-27 | Initial draft (Lane N): storage layout and schema v2, PoC migration, writer actor and WAL readers, typed errors and privacy, backend traits and as-built adapters, embedding channels and modality, index generations with promotion and GC |
