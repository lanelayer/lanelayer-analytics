use axum::extract::Path;
use axum::http::{HeaderMap, StatusCode};
use axum::response::{IntoResponse, Redirect};

use crate::slack;

const BIZCARD_TARGET: &str = "https://lanelayer.com/#/build";

fn bizcard_person(slug: &str) -> Option<&'static str> {
    match slug {
        "joanne" => Some("Joanne"),
        "nyakio" => Some("Nyakio"),
        "abby" => Some("Abby"),
        _ => None,
    }
}

pub async fn bizcard_redirect(Path(slug): Path<String>, headers: HeaderMap) -> impl IntoResponse {
    let Some(display) = bizcard_person(slug.as_str()) else {
        return StatusCode::NOT_FOUND.into_response();
    };

    let display = display.to_string();
    let user_agent = headers
        .get("user-agent")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("")
        .to_string();
    tokio::spawn(async move {
        slack::notify_bizcard_redirect(&display, &slug, &user_agent).await;
    });

    Redirect::temporary(BIZCARD_TARGET).into_response()
}
