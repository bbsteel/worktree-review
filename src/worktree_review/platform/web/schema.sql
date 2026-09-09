CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS repositories (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    canonical_root TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS provider_profiles (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    provider TEXT NOT NULL,
    endpoint TEXT,
    credential_reference TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trusted_review_policies (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    version_semver TEXT NOT NULL,
    version_sha256 TEXT NOT NULL,
    registered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS trusted_compute_policies (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    version_semver TEXT NOT NULL,
    version_sha256 TEXT NOT NULL,
    registered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS review_runs (
    attempt_id TEXT PRIMARY KEY,
    run_status TEXT NOT NULL,
    gate_state TEXT,
    created_at TEXT NOT NULL,
    cost_usd TEXT,
    cost_unknown INTEGER NOT NULL DEFAULT 0,
    interrupted INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS review_events (
    attempt_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    event_json TEXT NOT NULL,
    PRIMARY KEY (attempt_id, sequence)
);

CREATE TABLE IF NOT EXISTS review_results (
    attempt_id TEXT PRIMARY KEY,
    result_json TEXT NOT NULL,
    saved_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS idempotency_records (
    idempotency_key TEXT PRIMARY KEY,
    request_digest TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS integration_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
