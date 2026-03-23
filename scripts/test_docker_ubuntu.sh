#!/usr/bin/env bash
# Run prompt simulations inside an Ubuntu container to validate Ubuntu compatibility.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUNNER_IMAGE="lanelayer-ubuntu-test-runner"

echo "=== Build Ubuntu test runner image ==="
docker build -t "${RUNNER_IMAGE}" -f "${REPO_ROOT}/scripts/Dockerfile.ubuntu-test" "${REPO_ROOT}"

echo "=== Run simulations inside Ubuntu container ==="
docker run --rm \
    -e CODEX_API_KEY="${CODEX_API_KEY:-}" \
    -e CURSOR_API_KEY="${CURSOR_API_KEY:-}" \
    -e API_URL="${API_URL:-https://lanelayer-analytics.fly.dev}" \
    "${RUNNER_IMAGE}"

