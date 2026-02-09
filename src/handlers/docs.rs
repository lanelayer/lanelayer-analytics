use axum::extract::{Query, State};
use axum::response::Redirect;
use chrono::Utc;
use serde::Deserialize;
use sqlx::SqlitePool;

const DOC_BASE_URL: &str = "https://lanelayer.com";

const DOC_ROUTES: &[(&str, &str)] = &[
    ("guide", "/guide-reference.html"),
    ("quickstart", "/build-first-lane.html"),
    ("kv-api", "/guide-reference.html#step-4-understanding-the-kv-api"),
    ("deployment", "/guide-reference.html#step-7-deploy-to-flyio"),
    ("terminology", "/terminology.html"),
];

#[derive(Debug, Deserialize)]
pub struct DocQuery {
    #[serde(rename = "session")]
    pub session: Option<String>,
    #[serde(rename = "user")]
    pub user: Option<String>,
}

pub async fn track_doc_access(
    State(pool): State<SqlitePool>,
    axum::extract::Path(doc_id): axum::extract::Path<String>,
    Query(query): Query<DocQuery>,
) -> Redirect {
    let now = Utc::now().to_rfc3339();
    let data = serde_json::json!({ "doc_id": doc_id }).to_string();

    let _ = sqlx::query(
        "INSERT INTO events (event_type, user_id, session_id, data, created_at) VALUES (?, ?, ?, ?, ?)",
    )
    .bind("doc_access")
    .bind(query.user.as_deref())
    .bind(query.session.as_deref())
    .bind(&data)
    .bind(&now)
    .execute(&pool)
    .await;

    let path = DOC_ROUTES
        .iter()
        .find(|(id, _)| *id == doc_id)
        .map(|(_, path)| *path)
        .unwrap_or("/");

    Redirect::temporary(&format!("{}{}", DOC_BASE_URL, path))
}
