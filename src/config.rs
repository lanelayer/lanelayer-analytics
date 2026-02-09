use std::path::PathBuf;

pub fn database_path() -> PathBuf {
    std::env::var("DATABASE_PATH")
        .unwrap_or_else(|_| "/data/analytics.db".to_string())
        .into()
}

pub fn slack_webhook_url() -> Option<String> {
    let u = std::env::var("SLACK_WEBHOOK_URL").ok()?;
    if u.is_empty() {
        return None;
    }
    Some(u)
}

pub fn allowed_origins() -> Vec<String> {
    vec![
        "https://lanelayer.github.io".to_string(),
        "https://lanelayer.com".to_string(),
        "https://www.lanelayer.com".to_string(),
        "http://localhost:4000".to_string(),
    ]
}

pub const APP_VERSION: &str = "1.0.0";
