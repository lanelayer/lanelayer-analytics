#!/bin/bash
# Manual testing script for LaneLayer Analytics API
set -e

BASE_URL="${1:-http://localhost:8080}"

echo "=== LaneLayer Analytics API Tests ==="
echo "Base URL: $BASE_URL"
echo ""

echo "1. Health Check"
curl -s "$BASE_URL/health" | python3 -m json.tool
echo ""

echo "2. Create Prompt Version"
curl -s -X POST "$BASE_URL/api/v1/prompt/versions" \
  -H "Content-Type: application/json" \
  -d '{
    "version": "2.1",
    "content": "# Build My Lane\nThis is the full prompt content.",
    "is_active": true
  }' | python3 -m json.tool
echo ""

echo "3. Get Latest Prompt"
PROMPT_RESPONSE=$(curl -s "$BASE_URL/api/v1/prompt/latest")
echo "$PROMPT_RESPONSE" | python3 -m json.tool
SESSION_ID=$(echo "$PROMPT_RESPONSE" | python3 -c "import sys,json;print(json.load(sys.stdin)['session_id'])")
echo "Session ID: $SESSION_ID"
echo ""

echo "4. Track Copy Prompt Event"
curl -s -X POST "$BASE_URL/api/v1/events" \
  -H "Content-Type: application/json" \
  -d "{
    \"event_type\": \"copy_prompt\",
    \"user_id\": \"web_test_$(date +%s)\",
    \"session_id\": \"$SESSION_ID\",
    \"data\": {\"prompt_version\": \"2.1\", \"source\": \"manual_test\"}
  }" | python3 -m json.tool
echo ""

echo "5. Track CLI Event"
curl -s -X POST "$BASE_URL/api/v1/events/cli" \
  -H "Content-Type: application/json" \
  -d "{
    \"user_id\": \"cli_test_$(date +%s)\",
    \"session_id\": \"$SESSION_ID\",
    \"command\": \"up\",
    \"profile\": \"dev\",
    \"success\": true,
    \"duration_ms\": 5420,
    \"cli_version\": \"0.4.9\",
    \"os\": \"darwin\"
  }" | python3 -m json.tool
echo ""

echo "6. Correlate Session"
curl -s -X POST "$BASE_URL/api/v1/sessions/correlate" \
  -H "Content-Type: application/json" \
  -d "{
    \"session_id\": \"$SESSION_ID\",
    \"cli_user_id\": \"cli_test_correlate\"
  }" | python3 -m json.tool
echo ""

echo "7. List Prompt Versions"
curl -s "$BASE_URL/api/v1/prompt/versions" | python3 -m json.tool
echo ""

echo "=== All Tests Complete ==="
