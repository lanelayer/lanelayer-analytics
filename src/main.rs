mod config;
mod db;
mod handlers;
mod models;
mod slack;
mod utils;

use axum::routing::{get, post};
use axum::Router;
use std::path::Path;
use tower_http::cors::{AllowOrigin, Any, CorsLayer};
use tracing_subscriber::{layer::SubscriberExt, util::SubscriberInitExt};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    dotenvy::dotenv().ok();

    tracing_subscriber::registry()
        .with(tracing_subscriber::EnvFilter::new(
            std::env::var("RUST_LOG").unwrap_or_else(|_| "info".into()),
        ))
        .with(tracing_subscriber::fmt::layer())
        .init();

    let db_path = config::database_path();
    let pool = db::create_pool(Path::new(&db_path)).await?;
    db::init_db(&pool).await?;
    db::ensure_active_prompt(&pool).await?;

    let origins: Vec<axum::http::HeaderValue> = config::allowed_origins()
        .into_iter()
        .filter_map(|s| s.parse().ok())
        .collect();

    let cors = CorsLayer::new()
        .allow_origin(AllowOrigin::list(origins))
        .allow_methods([axum::http::Method::GET, axum::http::Method::POST])
        .allow_headers(Any);

    let app = Router::new()
        .route("/health", get(handlers::health))
        .route("/api/v1/events", post(handlers::track_event))
        .route("/api/v1/events/cli", post(handlers::track_cli_event))
        .route("/api/v1/prompt/latest", get(handlers::get_latest_prompt))
        .route("/api/v1/prompt/versions", get(handlers::list_prompt_versions))
        .route("/api/v1/prompt/versions", post(handlers::create_prompt_version))
        .route("/api/v1/sessions/correlate", post(handlers::correlate_session))
        .route("/api/v1/docs/:doc_id", get(handlers::track_doc_access))
        .layer(cors)
        .with_state(pool);

    let port: u16 = std::env::var("PORT")
        .ok()
        .and_then(|p| p.parse().ok())
        .unwrap_or(8080);
    let addr = std::net::SocketAddr::from(([0, 0, 0, 0], port));
    tracing::info!("LaneLayer Analytics listening on {}", addr);
    axum::serve(
        tokio::net::TcpListener::bind(addr).await?,
        app,
    )
    .await?;

    Ok(())
}
