PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'business_user', 'guest')),
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS auth_sessions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    revoked_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_token_hash
ON auth_sessions(token_hash);

CREATE INDEX IF NOT EXISTS idx_auth_sessions_user_id
ON auth_sessions(user_id);

CREATE TABLE IF NOT EXISTS document_registry (
    document_id TEXT PRIMARY KEY,
    document_number TEXT,
    title TEXT,
    source_system TEXT,
    source_url TEXT,
    sector TEXT,
    domain TEXT,
    issuing_body TEXT,
    signer_title TEXT,
    signer_name TEXT,
    document_type TEXT,
    issued_date TEXT,
    effective_date TEXT,
    expiry_date TEXT,
    validity_status TEXT,
    raw_metadata_json TEXT,
    active_version INTEGER,
    is_published INTEGER NOT NULL DEFAULT 0 CHECK (is_published IN (0, 1)),
    is_deleted INTEGER NOT NULL DEFAULT 0 CHECK (is_deleted IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_document_registry_document_number
ON document_registry(document_number);

CREATE INDEX IF NOT EXISTS idx_document_registry_validity_status
ON document_registry(validity_status);

CREATE TABLE IF NOT EXISTS document_versions (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    import_batch_id TEXT,
    raw_docx_path TEXT,
    preprocessed_text_path TEXT,
    chunk_json_path TEXT,
    metadata_json TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (document_id, version),
    FOREIGN KEY (document_id) REFERENCES document_registry(document_id)
);

CREATE INDEX IF NOT EXISTS idx_document_versions_document_id
ON document_versions(document_id);

CREATE INDEX IF NOT EXISTS idx_document_versions_import_batch_id
ON document_versions(import_batch_id);

CREATE TABLE IF NOT EXISTS document_relations (
    id TEXT PRIMARY KEY,
    source_document_id TEXT NOT NULL,
    target_document_id TEXT,
    target_document_number TEXT,
    relation_type TEXT NOT NULL,
    source_text TEXT,
    import_batch_id TEXT,
    is_published INTEGER NOT NULL DEFAULT 0 CHECK (is_published IN (0, 1)),
    created_at TEXT NOT NULL,
    FOREIGN KEY (source_document_id) REFERENCES document_registry(document_id)
);

CREATE INDEX IF NOT EXISTS idx_document_relations_source_document_id
ON document_relations(source_document_id);

CREATE INDEX IF NOT EXISTS idx_document_relations_import_batch_id
ON document_relations(import_batch_id);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id TEXT PRIMARY KEY,
    pipeline_type TEXT NOT NULL,
    requested_by_user_id TEXT,
    input_json TEXT,
    status TEXT NOT NULL,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (requested_by_user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status
ON pipeline_runs(status);

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_type
ON pipeline_runs(pipeline_type);

CREATE TABLE IF NOT EXISTS pipeline_events (
    id TEXT PRIMARY KEY,
    pipeline_run_id TEXT NOT NULL,
    state TEXT NOT NULL,
    message TEXT,
    payload_json TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (pipeline_run_id) REFERENCES pipeline_runs(id)
);

CREATE INDEX IF NOT EXISTS idx_pipeline_events_pipeline_run_id
ON pipeline_events(pipeline_run_id);
