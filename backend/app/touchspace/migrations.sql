-- Feature-local migration 1. Package binaries live in file storage; only metadata is in SQLite.
CREATE TABLE IF NOT EXISTS touchspace_maps (
    map_id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    visibility TEXT NOT NULL CHECK(visibility IN ('private', 'public')),
    schema_version INTEGER NOT NULL,
    manifest_json TEXT NOT NULL,
    checksum TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    storage_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    published_at TEXT,
    warnings_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS touchspace_maps_visibility ON touchspace_maps(visibility, created_at);
CREATE TABLE IF NOT EXISTS touchspace_sessions (
    scope TEXT NOT NULL,
    map_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    target_id TEXT,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY(scope, map_id, session_id)
);
PRAGMA user_version = 1;
