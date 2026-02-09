use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize)]
pub struct WebEvent {
    pub event_type: String,
    pub user_id: String,
    pub session_id: Option<String>,
    pub data: Option<serde_json::Value>,
}

#[derive(Debug, Serialize)]
pub struct WebEventResponse {
    pub success: bool,
    pub event_id: i64,
    pub session_id: Option<String>,
}

#[derive(Debug, Deserialize)]
pub struct CLIEvent {
    pub user_id: String,
    pub session_id: Option<String>,
    pub command: String,
    pub profile: Option<String>,
    pub duration_ms: Option<i64>,
    pub success: Option<bool>,
    pub error_message: Option<String>,
    pub cli_version: Option<String>,
    pub os: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct CLIEventResponse {
    pub success: bool,
}

#[derive(Debug, Serialize)]
pub struct PromptLatestResponse {
    pub version: String,
    pub session_id: String,
    pub content: String,
}

#[derive(Debug, Serialize)]
pub struct PromptVersionItem {
    pub version: String,
    pub is_active: bool,
    pub created_at: String,
}

#[derive(Debug, Serialize)]
pub struct PromptVersionsResponse {
    pub versions: Vec<PromptVersionItem>,
}

#[derive(Debug, Deserialize)]
pub struct PromptCreateRequest {
    pub version: String,
    pub content: String,
    #[serde(default)]
    pub is_active: bool,
}

#[derive(Debug, Deserialize)]
pub struct CorrelateRequest {
    pub session_id: String,
    pub cli_user_id: String,
}

#[derive(Debug, Serialize)]
pub struct CorrelateResponse {
    pub success: bool,
    pub correlated: bool,
    pub web_user_id: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct HealthResponse {
    pub status: String,
    pub version: String,
}
