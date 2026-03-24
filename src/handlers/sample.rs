use axum::extract::{Query, State};
use axum::http::{header, StatusCode};
use axum::response::IntoResponse;
use chrono::Utc;
use serde::Deserialize;
use sqlx::SqlitePool;
use std::io::Cursor;

// Embed sample-python template files at compile time
static SAMPLE_FILES: &[(&str, &[u8])] = &[
    ("app.py", include_bytes!("../../samples/python/app.py")),
    (
        ".dockerignore",
        include_bytes!("../../samples/python/.dockerignore"),
    ),
    ("Dockerfile", include_bytes!("../../samples/python/Dockerfile")),
    (
        "package.json",
        include_bytes!("../../samples/python/package.json"),
    ),
];

#[derive(Debug, Deserialize)]
pub struct SampleQuery {
    pub session_id: Option<String>,
}

pub async fn serve_sample_tar(
    State(pool): State<SqlitePool>,
    Query(query): Query<SampleQuery>,
) -> impl IntoResponse {
    // Log the sample archive access event
    let now = Utc::now().to_rfc3339();
    let data = serde_json::json!({ "action": "download_sample_tar" }).to_string();
    let _ = sqlx::query(
        "INSERT INTO events (event_type, user_id, session_id, data, created_at) VALUES (?, ?, ?, ?, ?)",
    )
    .bind("sample_download")
    .bind::<Option<&str>>(None)
    .bind(query.session_id.as_deref())
    .bind(&data)
    .bind(&now)
    .execute(&pool)
    .await;

    // Build tar archive in memory
    let buffer = Cursor::new(Vec::new());
    let mut archive = tar::Builder::new(buffer);

    for (filename, content) in SAMPLE_FILES {
        let mut file_header = tar::Header::new_gnu();
        file_header.set_size(content.len() as u64);
        file_header.set_mode(0o644);
        file_header.set_cksum();
        if let Err(e) = archive.append_data(&mut file_header, filename, *content) {
            tracing::error!("Failed to append {} to tar: {}", filename, e);
            return (StatusCode::INTERNAL_SERVER_ERROR, "Failed to build archive").into_response();
        }
    }

    let buffer = match archive.into_inner() {
        Ok(b) => b.into_inner(),
        Err(e) => {
            tracing::error!("Failed to finalize tar: {}", e);
            return (StatusCode::INTERNAL_SERVER_ERROR, "Failed to build archive").into_response();
        }
    };

    (
        StatusCode::OK,
        [
            (header::CONTENT_TYPE, "application/x-tar"),
            (
                header::CONTENT_DISPOSITION,
                "attachment; filename=\"sample.tar\"",
            ),
        ],
        buffer,
    )
        .into_response()
}
