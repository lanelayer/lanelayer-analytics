use axum::extract::State;
use axum::http::StatusCode;
use axum::Json;
use chrono::Utc;
use sqlx::SqlitePool;

use crate::models::{
    PromptCreateRequest, PromptLatestResponse, PromptVersionItem, PromptVersionsResponse,
};
use crate::utils;

pub async fn get_latest_prompt(
    State(pool): State<SqlitePool>,
) -> Result<Json<PromptLatestResponse>, (StatusCode, String)> {
    let row: Option<(String, String)> = sqlx::query_as(
        "SELECT version, content FROM prompt_versions WHERE is_active = 1 ORDER BY id DESC LIMIT 1",
    )
    .fetch_optional(&pool)
    .await
    .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

    let (version, content) = row.ok_or((
        StatusCode::NOT_FOUND,
        "No active prompt version found".to_string(),
    ))?;

    let session_id = utils::generate_session_id(12);
    let now = Utc::now().to_rfc3339();

    sqlx::query("INSERT INTO sessions (id, prompt_version, created_at) VALUES (?, ?, ?)")
        .bind(&session_id)
        .bind(&version)
        .bind(&now)
        .execute(&pool)
        .await
        .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

    let tagged_content = format!(
        "{}\n\n---\nLaneLayer Prompt {} | Session: {}",
        content, version, session_id
    );

    Ok(Json(PromptLatestResponse {
        version,
        session_id,
        content: tagged_content,
    }))
}

pub async fn list_prompt_versions(
    State(pool): State<SqlitePool>,
) -> Result<Json<PromptVersionsResponse>, (StatusCode, String)> {
    let rows: Vec<(String, bool, String)> = sqlx::query_as(
        "SELECT version, is_active, created_at FROM prompt_versions ORDER BY id DESC",
    )
    .fetch_all(&pool)
    .await
    .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

    let versions = rows
        .into_iter()
        .map(|(version, is_active, created_at)| PromptVersionItem {
            version,
            is_active,
            created_at,
        })
        .collect();

    Ok(Json(PromptVersionsResponse { versions }))
}

pub async fn create_prompt_version(
    State(pool): State<SqlitePool>,
    Json(req): Json<PromptCreateRequest>,
) -> Result<Json<serde_json::Value>, (StatusCode, String)> {
    let now = Utc::now().to_rfc3339();

    sqlx::query(
        "INSERT INTO prompt_versions (version, content, is_active, created_at) VALUES (?, ?, ?, ?)",
    )
    .bind(&req.version)
    .bind(&req.content)
    .bind(req.is_active)
    .bind(&now)
    .execute(&pool)
    .await
    .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

    if req.is_active {
        sqlx::query("UPDATE prompt_versions SET is_active = 0 WHERE version != ?")
            .bind(&req.version)
            .execute(&pool)
            .await
            .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;
    }

    Ok(Json(serde_json::json!({
        "success": true,
        "version": req.version
    })))
}
