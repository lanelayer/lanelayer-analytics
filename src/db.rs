use sqlx::sqlite::{SqliteConnectOptions, SqlitePool};
use std::path::Path;
use std::str::FromStr;

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
