use axum::extract::{Query, State};
use axum::response::{IntoResponse, Redirect};
use axum::http::{header, StatusCode};
use chrono::Utc;
use serde::Deserialize;
use sqlx::SqlitePool;

const DOC_BASE_URL: &str = "https://lanelayer.com";

// Agent guidance docs: served from backend (scripts folder). Content embedded at compile time.
static INTERVIEW_GUIDE: &str = include_str!("../../scripts/interview-guide.txt");
static GITHUB_FLOW: &str = include_str!("../../scripts/github-flow.txt");
static DEVELOPER_WORKFLOW: &str = include_str!("../../scripts/developer-workflow.txt");

// Public site docs: backend redirects to lanelayer.com for tracking.
const DOC_REDIRECTS: &[(&str, &str)] = &[
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
) -> impl IntoResponse {
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

    // Serve agent guidance from embedded scripts content
    let body = match doc_id.as_str() {
        "interview-guide" => INTERVIEW_GUIDE,
        "github-flow" => GITHUB_FLOW,
        "developer-workflow" => DEVELOPER_WORKFLOW,
        _ => {
            let path = DOC_REDIRECTS
                .iter()
                .find(|(id, _)| *id == doc_id)
                .map(|(_, path)| *path)
                .unwrap_or("/");
            return Redirect::temporary(&format!("{}{}", DOC_BASE_URL, path)).into_response();
        }
    };

    (
        StatusCode::OK,
        [(header::CONTENT_TYPE, "text/plain; charset=utf-8")],
        body.to_string(),
    )
        .into_response()
}
