#!/usr/bin/env bash
# End-to-end test: build Docker image, start container, run API smoke tests + agent simulations.
# Requires: Docker Desktop, Python 3, codex CLI, agent (Cursor) CLI
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
CONTAINER_NAME="lanelayer-analytics-test"
IMAGE_NAME="lanelayer-analytics:test"
TEST_PORT=18080
API_URL="http://localhost:${TEST_PORT}"
CODEX_SCORE_THRESHOLD=6
CURSOR_SCORE_THRESHOLD=5

cleanup() {
    echo "--- Cleanup ---"
    docker rm -f "${CONTAINER_NAME}" 2>/dev/null || true
}
trap cleanup EXIT

echo "=== Build Docker image ==="
docker build -t "${IMAGE_NAME}" "${REPO_ROOT}"

echo "=== Start container ==="
docker run -d \
    --name "${CONTAINER_NAME}" \
    -p "${TEST_PORT}:8080" \
    -e DATABASE_PATH=/data/analytics.db \
    -e RUST_LOG=info \
    "${IMAGE_NAME}"

echo "=== Wait for healthy ==="
for i in $(seq 1 30); do
    if curl -sf "${API_URL}/health" >/dev/null 2>&1; then
        echo "API healthy after ${i}s"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "FAIL: API did not become healthy within 30s"
        docker logs "${CONTAINER_NAME}"
        exit 1
    fi
    sleep 1
done

echo "=== Run API smoke tests ==="
bash "${REPO_ROOT}/scripts/test_manual.sh" "${API_URL}"

echo "=== Run Codex simulation ==="
CODEX_RESULT=$(bash "${REPO_ROOT}/scripts/simulate_lane_with_codex.sh" --api-url "${API_URL}" 2>&1) || true
CODEX_SCORE=$(echo "${CODEX_RESULT}" | python3 -c "import sys,json; data=json.load(sys.stdin); print(data.get('overall_score', 0))" 2>/dev/null || echo "0")
echo "Codex score: ${CODEX_SCORE}"

echo "=== Run Cursor simulation ==="
CURSOR_RESULT=$(bash "${REPO_ROOT}/scripts/simulate_lane_with_cursor.sh" --api-url "${API_URL}" 2>&1) || true
CURSOR_SCORE=$(echo "${CURSOR_RESULT}" | python3 -c "import sys,json; data=json.load(sys.stdin); print(data.get('overall_score', 0))" 2>/dev/null || echo "0")
echo "Cursor score: ${CURSOR_SCORE}"

echo "=== Validate scores ==="
PASS=true
if (( $(echo "${CODEX_SCORE} < ${CODEX_SCORE_THRESHOLD}" | bc -l) )); then
    echo "FAIL: Codex score ${CODEX_SCORE} below threshold ${CODEX_SCORE_THRESHOLD}"
    PASS=false
fi
if (( $(echo "${CURSOR_SCORE} < ${CURSOR_SCORE_THRESHOLD}" | bc -l) )); then
    echo "FAIL: Cursor score ${CURSOR_SCORE} below threshold ${CURSOR_SCORE_THRESHOLD}"
    PASS=false
fi

if [ "${PASS}" = true ]; then
    echo "=== ALL TESTS PASSED ==="
    exit 0
else
    echo "=== SOME TESTS FAILED ==="
    exit 1
fi

