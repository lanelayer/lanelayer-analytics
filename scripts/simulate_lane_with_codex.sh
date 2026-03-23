#!/usr/bin/env bash

# Owners-only: run the automated multi-turn lane prompt simulation (Codex engine).
#
# Prereqs:
# - Codex CLI installed so `codex` is on PATH
# - Auth configured for `codex exec` (often via saved login or CODEX_API_KEY in CI)
#
# Usage:
#   export CODEX_API_KEY=...
#   ./scripts/simulate_lane_with_codex.sh --api-url https://analytics.lanelayer.com/ > lane-sim-codex.json

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"
python3 prompt-tests/run_codex_sim.py "$@"

