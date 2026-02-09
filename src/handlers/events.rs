use axum::extract::State;
use axum::Json;
use chrono::Utc;
use sqlx::SqlitePool;

use crate::config;
use crate::models::{CLIEvent, CLIEventResponse, WebEvent, WebEventResponse};
use crate::slack;

pub async fn health() -> Json<crate::models::HealthResponse> {
    Json(crate::models::HealthResponse {
        status: "ok".to_string(),
        version: config::APP_VERSION.to_string(),
    })
}

pub async fn track_event(
    State(pool): State<SqlitePool>,
    Json(event): Json<WebEvent>,
) -> Json<WebEventResponse> {
    let now = Utc::now().to_rfc3339();
    let user_type = if event.user_id.starts_with("web_") {
        "web"
    } else {
        "cli"
    };
    let data_json = event
        .data
        .as_ref()
        .map(|d| d.to_string())
        .unwrap_or_default();

    sqlx::query(
        r#"INSERT INTO users (id, type, created_at, last_seen_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET last_seen_at = ?"#,
    )
    .bind(&event.user_id)
    .bind(user_type)
    .bind(&now)
    .bind(&now)
    .bind(&now)
    .execute(&pool)
    .await
    .ok();

    let row = sqlx::query(
        r#"INSERT INTO events (event_type, user_id, session_id, data, created_at)
           VALUES (?, ?, ?, ?, ?)"#,
    )
    .bind(&event.event_type)
    .bind(&event.user_id)
    .bind(event.session_id.as_deref())
    .bind(if data_json.is_empty() { None::<String> } else { Some(data_json) })
    .bind(&now)
    .execute(&pool)
    .await
    .expect("insert event");

    let event_id = row.last_insert_rowid();

    if event.event_type == "copy_prompt" {
        let version = event
            .data
            .as_ref()
            .and_then(|d| d.get("prompt_version"))
            .and_then(|v| v.as_str())
            .unwrap_or("unknown")
            .to_string();
        let session_id = event.session_id.clone().unwrap_or_else(|| "none".to_string());
        let user_id = event.user_id.clone();
        tokio::spawn(async move {
            slack::notify_prompt_copied(&session_id, &version, &user_id).await;
        });
    }

    Json(WebEventResponse {
        success: true,
        event_id,
        session_id: event.session_id,
    })
}

pub async fn track_cli_event(
    State(pool): State<SqlitePool>,
    Json(event): Json<CLIEvent>,
) -> Json<CLIEventResponse> {
    let now = Utc::now().to_rfc3339();

    let is_new_user: bool = sqlx::query_scalar::<_, String>("SELECT id FROM users WHERE id = ?")
        .bind(&event.user_id)
        .fetch_optional(&pool)
        .await
        .ok()
        .flatten()
        .is_none();

    sqlx::query(
        r#"INSERT INTO users (id, type, created_at, last_seen_at)
           VALUES (?, 'cli', ?, ?)
           ON CONFLICT(id) DO UPDATE SET last_seen_at = ?"#,
    )
    .bind(&event.user_id)
    .bind(&now)
    .bind(&now)
    .bind(&now)
    .execute(&pool)
    .await
    .ok();

    sqlx::query(
        r#"INSERT INTO cli_events
           (user_id, session_id, command, profile, duration_ms, success, error_message, cli_version, os, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"#,
    )
    .bind(&event.user_id)
    .bind(event.session_id.as_deref())
    .bind(&event.command)
    .bind(event.profile.as_deref())
    .bind(event.duration_ms)
    .bind(event.success)
    .bind(event.error_message.as_deref())
    .bind(event.cli_version.as_deref())
    .bind(event.os.as_deref())
    .bind(&now)
    .execute(&pool)
    .await
    .expect("insert cli_event");

    if is_new_user {
        let user_id = event.user_id.clone();
        let command = event.command.clone();
        let cli_version = event.cli_version.clone();
        tokio::spawn(async move {
            slack::notify_cli_first_run(&user_id, &command, cli_version.as_deref()).await;
        });
    }

    Json(CLIEventResponse { success: true })
}
