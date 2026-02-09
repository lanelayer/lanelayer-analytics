use crate::config;
use serde_json::json;
use tracing::warn;

pub async fn send_slack_notification(text: &str, blocks: Option<serde_json::Value>) {
    let url = match config::slack_webhook_url() {
        Some(u) => u,
        None => {
            tracing::warn!("SLACK_WEBHOOK_URL not configured, skipping notification");
            return;
        }
    };

    let mut payload = json!({ "text": text });
    if let Some(b) = blocks {
        payload["blocks"] = b;
    }

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(5))
        .build()
        .unwrap_or_default();

    if let Err(e) = client.post(&url).json(&payload).send().await {
        warn!(error = %e, "Failed to send Slack notification");
    }
}

fn truncate_id(id: &str, max: usize) -> &str {
    if id.len() <= max {
        id
    } else {
        &id[..max]
    }
}

pub async fn notify_prompt_copied(session_id: &str, version: &str, user_id: &str) {
    let blocks = json!([
        { "type": "header", "text": { "type": "plain_text", "text": "Prompt Copied" } },
        {
            "type": "section",
            "fields": [
                { "type": "mrkdwn", "text": format!("*Session:*\n`{}`", session_id) },
                { "type": "mrkdwn", "text": format!("*Version:*\n{}", version) },
                { "type": "mrkdwn", "text": format!("*User:*\n`{}...`", truncate_id(user_id, 16)) },
            ]
        }
    ]);
    send_slack_notification("Prompt Copied", Some(blocks)).await;
}

pub async fn notify_session_correlated(session_id: &str, web_user_id: &str, cli_user_id: &str) {
    let blocks = json!([
        { "type": "header", "text": { "type": "plain_text", "text": "Journey Connected!" } },
        {
            "type": "section",
            "text": { "type": "mrkdwn", "text": "A website visitor has started using the CLI!" }
        },
        {
            "type": "section",
            "fields": [
                { "type": "mrkdwn", "text": format!("*Session:*\n`{}`", session_id) },
                { "type": "mrkdwn", "text": format!("*Web User:*\n`{}...`", truncate_id(web_user_id, 16)) },
                { "type": "mrkdwn", "text": format!("*CLI User:*\n`{}...`", truncate_id(cli_user_id, 16)) },
            ]
        }
    ]);
    send_slack_notification("Journey Connected!", Some(blocks)).await;
}

pub async fn notify_cli_first_run(user_id: &str, command: &str, cli_version: Option<&str>) {
    let blocks = json!([
        { "type": "header", "text": { "type": "plain_text", "text": "New CLI User!" } },
        {
            "type": "section",
            "fields": [
                { "type": "mrkdwn", "text": format!("*User:*\n`{}...`", truncate_id(user_id, 16)) },
                { "type": "mrkdwn", "text": format!("*First Command:*\n`{}`", command) },
                { "type": "mrkdwn", "text": format!("*CLI Version:*\n{}", cli_version.unwrap_or("unknown")) },
            ]
        }
    ]);
    send_slack_notification("New CLI User!", Some(blocks)).await;
}
