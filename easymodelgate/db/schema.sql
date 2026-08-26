-- EasyModelGate schema v1（规格 §22-§29、§46）
-- 时间约定：所有时间字段均为 Unix epoch 毫秒（UTC），见 ADR-0002。

CREATE TABLE IF NOT EXISTS users (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    username     TEXT    NOT NULL UNIQUE,
    display_name TEXT,
    enabled      INTEGER NOT NULL DEFAULT 1,
    created_at   INTEGER NOT NULL,
    note         TEXT
);

CREATE TABLE IF NOT EXISTS api_keys (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id),
    name         TEXT,
    key_prefix   TEXT    NOT NULL,
    key_hash     TEXT    NOT NULL UNIQUE,
    enabled      INTEGER NOT NULL DEFAULT 1,
    expires_at   INTEGER,
    rpm_limit    INTEGER,
    token_limit  INTEGER,
    token_used   INTEGER NOT NULL DEFAULT 0,
    created_at   INTEGER NOT NULL,
    last_used_at INTEGER
);

CREATE TABLE IF NOT EXISTS backends (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    type        TEXT    NOT NULL DEFAULT 'llamacpp',
    base_url    TEXT    NOT NULL,
    api_key_ref TEXT,
    enabled     INTEGER NOT NULL DEFAULT 1,
    created_at  INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS request_logs (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id           TEXT    NOT NULL,
    user_id              INTEGER,
    api_key_id           INTEGER,
    backend_id           INTEGER,
    model                TEXT,
    endpoint             TEXT,
    started_at           INTEGER NOT NULL,
    finished_at          INTEGER,
    duration_ms          INTEGER,
    queue_wait_ms        INTEGER,
    upstream_duration_ms INTEGER,
    ttft_ms              INTEGER,
    prompt_tokens        INTEGER,
    completion_tokens    INTEGER,
    total_tokens         INTEGER,
    cached_tokens        INTEGER,
    stream               INTEGER,
    finish_reason        TEXT,
    status_code          INTEGER,
    upstream_status_code INTEGER,
    client_ip            TEXT,
    input_bytes          INTEGER,
    output_bytes         INTEGER,
    error_type           TEXT,
    error_message        TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_rl_started       ON request_logs(started_at);
CREATE INDEX IF NOT EXISTS idx_rl_user_started  ON request_logs(user_id, started_at);
CREATE INDEX IF NOT EXISTS idx_rl_key_started   ON request_logs(api_key_id, started_at);
CREATE INDEX IF NOT EXISTS idx_rl_model_started ON request_logs(model, started_at);
