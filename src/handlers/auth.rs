use axum::extract::{Query, State};
use axum::http::StatusCode;
use axum::Json;
use chrono::Utc;
use sqlx::SqlitePool;

use crate::email;
use crate::models::{
    AuthStatusQuery, AuthStatusResponse, RegisterRequest, RegisterResponse, VerifyRequest,
    VerifyResponse,
};
use crate::slack;
use crate::utils;

pub async fn register_email(
    State(pool): State<SqlitePool>,
    Json(req): Json<RegisterRequest>,
) -> Result<Json<RegisterResponse>, (StatusCode, String)> {
    if !req.email.contains('@') || !req.email.contains('.') {
        return Ok(Json(RegisterResponse {
            success: false,
            message: "Invalid email address".to_string(),
        }));
    }

    let session_exists: bool = sqlx::query_scalar(
        "SELECT COUNT(*) > 0 FROM sessions WHERE id = ?",
    )
    .bind(&req.session_id)
    .fetch_one(&pool)
    .await
    .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

    if !session_exists {
        return Ok(Json(RegisterResponse {
            success: false,
            message: "Session not found".to_string(),
        }));
    }

    // RFC 2606 reserved test domain — deterministic code for agent simulations
    let code = if req.email.ends_with("@example.com") {
        "123456".to_string()
    } else {
        utils::generate_verification_code()
    };

    let now = Utc::now().to_rfc3339();

    sqlx::query(
        "INSERT INTO email_registrations (email, session_id, verification_code, created_at)
         VALUES (?, ?, ?, ?)
         ON CONFLICT(email, session_id) DO UPDATE SET
           verification_code = excluded.verification_code,
           auth_token = NULL,
           verified_at = NULL,
           created_at = excluded.created_at",
    )
    .bind(&req.email)
    .bind(&req.session_id)
    .bind(&code)
    .bind(&now)
    .execute(&pool)
    .await
    .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

    // Send real verification email (skip for test domains)
    if !req.email.ends_with("@example.com") {
        let email_clone = req.email.clone();
        let code_clone = code.clone();
        tokio::spawn(async move {
            email::send_verification_email(&email_clone, &code_clone).await;
        });
    }

    // Slack notification
    let email_for_slack = req.email.clone();
    let session_for_slack = req.session_id.clone();
    tokio::spawn(async move {
        slack::notify_email_registered(&email_for_slack, &session_for_slack).await;
    });

    Ok(Json(RegisterResponse {
        success: true,
        message: format!("Verification code sent to {}", req.email),
    }))
}

pub async fn verify_email(
    State(pool): State<SqlitePool>,
    Json(req): Json<VerifyRequest>,
) -> Result<Json<VerifyResponse>, (StatusCode, String)> {
    let now = Utc::now().to_rfc3339();
    let auth_token = utils::generate_auth_token(48);

    let result = sqlx::query(
        "UPDATE email_registrations SET verified_at = ?, auth_token = ?
         WHERE session_id = ? AND verification_code = ? AND verified_at IS NULL",
    )
    .bind(&now)
    .bind(&auth_token)
    .bind(&req.session_id)
    .bind(&req.code)
    .execute(&pool)
    .await
    .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

    Ok(Json(VerifyResponse {
        success: true,
        verified: result.rows_affected() > 0,
        auth_token: if result.rows_affected() > 0 {
            Some(auth_token)
        } else {
            None
        },
    }))
}

pub async fn auth_status(
    State(pool): State<SqlitePool>,
    Query(query): Query<AuthStatusQuery>,
) -> Result<Json<AuthStatusResponse>, (StatusCode, String)> {
    let row: Option<(String, Option<String>)> = sqlx::query_as(
        "SELECT email, verified_at FROM email_registrations WHERE session_id = ? LIMIT 1",
    )
    .bind(&query.session)
    .fetch_optional(&pool)
    .await
    .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

    match row {
        Some((email, verified_at)) => Ok(Json(AuthStatusResponse {
            registered: true,
            verified: verified_at.is_some(),
            email: Some(email),
        })),
        None => Ok(Json(AuthStatusResponse {
            registered: false,
            verified: false,
            email: None,
        })),
    }
}

