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

/// Public base URL of this analytics service (used in embedded prompt for {{API_URL}}).
pub fn public_base_url() -> String {
    std::env::var("PUBLIC_BASE_URL")
        .unwrap_or_else(|_| "https://analytics.lanelayer.com".to_string())
}

pub fn allowed_origins() -> Vec<String> {
    vec![
        "https://lanelayer.github.io".to_string(),
        "https://lanelayer.com".to_string(),
        "https://www.lanelayer.com".to_string(),
        "http://localhost:4000".to_string(),
    ]
}

pub fn resend_api_key() -> Option<String> {
    let k = std::env::var("RESEND_API_KEY").ok()?;
    if k.is_empty() {
        return None;
    }
    Some(k)
}

pub fn from_email() -> String {
    let raw = std::env::var("FROM_EMAIL")
        .unwrap_or_else(|_| "LaneLayer <noreply@updates.lanelayer.com>".to_string());
    // Accept accidentally quoted env values, e.g. "\"Name <email@domain>\"".
    raw.trim()
        .trim_matches('"')
        .trim_matches('\'')
        .to_string()
}

pub const APP_VERSION: &str = "1.2.0";
