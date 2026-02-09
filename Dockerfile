FROM rust:1-bookworm AS builder
WORKDIR /app

COPY Cargo.toml ./
COPY src ./src

RUN cargo build --release

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y ca-certificates libssl3 && rm -rf /var/lib/apt/lists/*
WORKDIR /app

COPY --from=builder /app/target/release/lanelayer-analytics /app/lanelayer-analytics

ENV RUST_LOG=info
EXPOSE 8080
CMD ["/app/lanelayer-analytics"]
