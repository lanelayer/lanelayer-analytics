use axum::extract::{Path, Query, State};
use axum::http::StatusCode;
use axum::http::{header, HeaderMap};
use axum::Json;
use chrono::Utc;
use sqlx::SqlitePool;
use serde::Deserialize;

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

pub async fn get_email_from_session_id(
    State(pool): State<SqlitePool>,
    headers: HeaderMap,
    Path(session_id): Path<String>,
    Query(query): Query<GetEmailFromSessionQuery>,
) -> Result<(StatusCode, String), (StatusCode, String)> {
    let bearer_token = headers
        .get(header::AUTHORIZATION)
        .and_then(|h| h.to_str().ok())
        .and_then(|v| v.strip_prefix("Bearer "))
        .map(|s| s.trim().to_string());

    let token = bearer_token.or(query.auth_token);
    let token = match token {
        Some(t) if !t.is_empty() => t,
        _ => return Ok((StatusCode::UNAUTHORIZED, "unauthorized".to_string())),
    };

    let row: Option<(String,)> = sqlx::query_as(
        "SELECT email FROM email_registrations
         WHERE session_id = ?
         ORDER BY (verified_at IS NOT NULL) DESC, created_at DESC
         LIMIT 1",
    )
    .bind(&session_id)
    .bind(&token)
    .fetch_optional(&pool)
    .await
    .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

    match row {
        Some((email,)) => Ok((StatusCode::OK, email)),
        None => Ok((StatusCode::UNAUTHORIZED, "unauthorized".to_string())),
    }
}

#[derive(Debug, Deserialize)]
pub struct GetEmailFromSessionQuery {
    pub auth_token: Option<String>,
}

// ── Test-only endpoint: retrieve pending verification code ──────────
// Gated by the PROMPT_TEST_SECRET env var. CI passes the same value
// in the X-Test-Secret header. If the env var is unset the endpoint
// always returns 404 — it cannot be reached in production.

#[derive(Debug, Deserialize)]
pub struct TestCodeQuery {
    pub session_id: String,
}

pub async fn test_verification_code(
    State(pool): State<SqlitePool>,
    headers: HeaderMap,
    Query(query): Query<TestCodeQuery>,
) -> Result<(StatusCode, String), (StatusCode, String)> {
    let expected_secret = match std::env::var("PROMPT_TEST_SECRET").ok() {
        Some(s) if !s.is_empty() => s,
        _ => return Ok((StatusCode::NOT_FOUND, "not found".into())),
    };

    let provided = headers
        .get("x-test-secret")
        .and_then(|h| h.to_str().ok())
        .unwrap_or("");

    if provided != expected_secret {
        return Ok((StatusCode::NOT_FOUND, "not found".into()));
    }

    let row: Option<(String,)> = sqlx::query_as(
        "SELECT verification_code FROM email_registrations
         WHERE session_id = ? AND verified_at IS NULL
         ORDER BY created_at DESC LIMIT 1",
    )
    .bind(&query.session_id)
    .fetch_optional(&pool)
    .await
    .map_err(|e| (StatusCode::INTERNAL_SERVER_ERROR, e.to_string()))?;

    match row {
        Some((code,)) => Ok((StatusCode::OK, code)),
        None => Ok((StatusCode::NOT_FOUND, "no pending code".into())),
    }
}

