# SQL references

| File | Purpose |
|---|---|
| [`minimal-schema.sql`](minimal-schema.sql) | Research schema for the minimal local-search app |
| [`gety-schema-reference.sql`](gety-schema-reference.sql) | Representative Gety schema observed on disk, for comparison only |

The active Seeky schema and migrations live in
[`apps/seeky/src-tauri/src/db.rs`](../apps/seeky/src-tauri/src/db.rs). Keep these
SQL files aligned when the reference schema is updated.
