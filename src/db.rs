use chrono::Utc;
use sqlx::sqlite::{SqliteConnectOptions, SqlitePool};
use std::path::Path;
use std::str::FromStr;

use crate::config;

/// Embedded default prompt: scripts/default-prompt.txt. Upserted into DB at startup so
/// the active prompt in the database is always the one shipped with this build.
static DEFAULT_PROMPT: &str = include_str!("../scripts/default-prompt.txt");

const SCHEMA: &str = r#"
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL CHECK(type IN ('web', 'cli')),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    web_user_id TEXT,
    cli_user_id TEXT,
    prompt_version TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    correlated_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    user_id TEXT,
    session_id TEXT,
    data TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS prompt_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    version TEXT UNIQUE NOT NULL,
    content TEXT NOT NULL,
    is_active BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cli_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    session_id TEXT,
    command TEXT NOT NULL,
    profile TEXT,
    duration_ms INTEGER,
    success BOOLEAN,
    error_message TEXT,
    cli_version TEXT,
    os TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_events_user_id ON events(user_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_created ON events(created_at);
CREATE INDEX IF NOT EXISTS idx_sessions_web_user ON sessions(web_user_id);
CREATE INDEX IF NOT EXISTS idx_cli_events_command ON cli_events(command);
"#;

pub async fn create_pool(path: &Path) -> Result<SqlitePool, sqlx::Error> {
    let parent = path.parent().unwrap_or(Path::new("."));
    if !parent.as_os_str().is_empty() {
        std::fs::create_dir_all(parent).ok();
    }
    let opts = SqliteConnectOptions::from_str(&format!("sqlite:{}", path.display()))?
        .create_if_missing(true);
    let pool = SqlitePool::connect_with(opts).await?;
    Ok(pool)
}

pub async fn init_db(pool: &SqlitePool) -> Result<(), sqlx::Error> {
    for statement in SCHEMA.split(';').filter(|s| !s.trim().is_empty()) {
        sqlx::query(statement.trim()).execute(pool).await?;
    }
    Ok(())
}

/// Upsert the embedded default prompt into prompt_versions and set it active. Called at
/// startup so the database always has the current prompt from the code; /api/v1/prompt/latest
/// serves from the DB.
pub async fn ensure_active_prompt(pool: &SqlitePool) -> Result<(), sqlx::Error> {
    let version = config::APP_VERSION.to_string();
    let base_url = config::public_base_url();
    let content = DEFAULT_PROMPT.replace("{{API_URL}}", &base_url);
    let now = Utc::now().to_rfc3339();

    sqlx::query(
        "INSERT INTO prompt_versions (version, content, is_active, created_at) VALUES (?, ?, 1, ?)
         ON CONFLICT(version) DO UPDATE SET content = excluded.content, is_active = 1, created_at = excluded.created_at",
    )
    .bind(&version)
    .bind(&content)
    .bind(&now)
    .execute(pool)
    .await?;

    sqlx::query("UPDATE prompt_versions SET is_active = 0 WHERE version != ?")
        .bind(&version)
        .execute(pool)
        .await?;

    Ok(())
}
