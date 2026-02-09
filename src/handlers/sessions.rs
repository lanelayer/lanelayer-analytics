use axum::extract::State;
use axum::Json;
use chrono::Utc;
use sqlx::SqlitePool;

use crate::models::{CorrelateRequest, CorrelateResponse};
use crate::slack;

pub async fn correlate_session(
    State(pool): State<SqlitePool>,
    Json(req): Json<CorrelateRequest>,
) -> Json<CorrelateResponse> {
    let row: Option<(Option<String>,)> =
        sqlx::query_as("SELECT web_user_id FROM sessions WHERE id = ?")
            .bind(&req.session_id)
            .fetch_optional(&pool)
            .await
            .ok()
            .flatten();

    let (success, correlated, web_user_id) = match row {
        None => (false, false, None),
        Some((db_web_user_id,)) => {
            let now = Utc::now().to_rfc3339();
            sqlx::query("UPDATE sessions SET cli_user_id = ?, correlated_at = ? WHERE id = ?")
                .bind(&req.cli_user_id)
                .bind(&now)
                .bind(&req.session_id)
                .execute(&pool)
                .await
                .ok();

            if db_web_user_id.as_ref().map_or(false, |s| !s.is_empty()) {
                let session_id = req.session_id.clone();
                let wid = db_web_user_id.clone().unwrap();
                let cli_user_id = req.cli_user_id.clone();
                tokio::spawn(async move {
                    slack::notify_session_correlated(&session_id, &wid, &cli_user_id).await;
                });
            }

            (true, true, db_web_user_id)
        }
    };

    Json(CorrelateResponse {
        success,
        correlated,
        web_user_id,
    })
}
