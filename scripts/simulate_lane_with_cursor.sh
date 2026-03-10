#!/usr/bin/env bash

# Owners-only: run the automated multi-turn lane prompt simulation (Cursor engine).
#
# Prereqs:
# - Cursor CLI installed so `agent` is on PATH
# - `CURSOR_API_KEY` set (CI secret)
#
# Usage:
#   export CURSOR_API_KEY=...
#   ./scripts/simulate_lane_with_cursor.sh --api-url https://lanelayer-analytics.fly.dev > lane-sim-cursor.json

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"
python3 prompt-tests/run_cursor_sim.py "$@"

