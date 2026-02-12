#!/usr/bin/env bash
# Seeds the analytics server with the default prompt ({{API_URL}}, {{SESSION_ID}}, {{USER_ID}} in content).
# Usage: ./scripts/seed-prompt.sh [API_URL]
# Example: ./scripts/seed-prompt.sh https://lanelayer-analytics.fly.dev

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Where the analytics API is deployed (used in prompt doc links and as POST target)
API_URL="${1:-https://lanelayer-analytics.fly.dev}"
API_URL="${API_URL%/}"
PROMPT_FILE="${SCRIPT_DIR}/default-prompt.txt"

if [ ! -f "$PROMPT_FILE" ]; then
  echo "Missing $PROMPT_FILE"
  exit 1
fi

VERSION="${2:-1.0}"
PAYLOAD_FILE=$(mktemp)
trap 'rm -f "$PAYLOAD_FILE"' EXIT
python3 -c "
import json, sys
with open(sys.argv[1]) as f:
    content = f.read()
# Substitute {{API_URL}} with the deployed API base URL
content = content.replace('{{API_URL}}', sys.argv[4])
with open(sys.argv[3], 'w') as out:
    json.dump({'version': sys.argv[2], 'content': content, 'is_active': True}, out)
" "$PROMPT_FILE" "$VERSION" "$PAYLOAD_FILE" "$API_URL"

echo "Posting prompt version $VERSION to $API_URL/api/v1/prompt/versions"
RESP=$(curl -s -w "\n%{http_code}" -X POST "$API_URL/api/v1/prompt/versions" \
  -H "Content-Type: application/json" \
  -d @"$PAYLOAD_FILE")
HTTP_CODE=$(echo "$RESP" | tail -n1)
BODY=$(echo "$RESP" | sed '$d')
if [ "$HTTP_CODE" != "200" ]; then
  echo "HTTP $HTTP_CODE"
  echo "$BODY"
  exit 1
fi
echo "$BODY" | python3 -m json.tool 2>/dev/null || echo "$BODY"
