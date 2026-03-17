use crate::config;
use serde_json::json;
use tracing::warn;

pub async fn send_verification_email(to_email: &str, code: &str) {
    let api_key = match config::resend_api_key() {
        Some(k) => k,
        None => {
            warn!("RESEND_API_KEY not configured, skipping verification email");
            return;
        }
    };

    let from = config::from_email();

    let payload = json!({
        "from": from,
        "to": [to_email],
        "subject": "Your LaneLayer verification code",
        "text": format!(
            "Your LaneLayer verification code is: {}\n\nEnter this code to continue building your lane.\n\nIf you did not request this, you can ignore this email.",
            code
        )
    });

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()
        .unwrap_or_default();

    match client
        .post("https://api.resend.com/emails")
        .header("Authorization", format!("Bearer {}", api_key))
        .json(&payload)
        .send()
        .await
    {
        Ok(resp) => {
            if !resp.status().is_success() {
                let status = resp.status();
                let body = resp.text().await.unwrap_or_default();
                warn!(status = %status, body = %body, "Resend API returned non-success");
            }
        }
        Err(e) => {
            warn!(error = %e, "Failed to send verification email");
        }
    }
}

