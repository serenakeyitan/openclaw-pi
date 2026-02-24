#!/bin/bash
# Check xiaohongshu MCP login status

set -euo pipefail

MCP_URL="${MCP_URL:-http://localhost:18060/mcp}"

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

init_body="$tmpdir/init.json"
init_headers="$tmpdir/init.headers"

# 1) initialize
curl -sS -D "$init_headers" -o "$init_body" -X POST "$MCP_URL" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"xhs-check-login","version":"1.0.0"}},"id":1}'

SESSION_ID="$(awk 'tolower($1)=="mcp-session-id:"{print $2}' "$init_headers" | tr -d '\r')"
if [ -z "${SESSION_ID:-}" ]; then
  echo "Failed to read Mcp-Session-Id from initialize response headers."
  echo "Initialize response body:"
  cat "$init_body"
  exit 1
fi

# 2) notifications/initialized
curl -sS -o /dev/null -X POST "$MCP_URL" \
  -H "Content-Type: application/json" \
  -H "Mcp-Session-Id: $SESSION_ID" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}'

# Check login status
RESPONSE=$(curl -sS -X POST "$MCP_URL" \
  -H "Content-Type: application/json" \
  -H "Mcp-Session-Id: $SESSION_ID" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "check_login_status",
      "arguments": {}
    },
    "id": 2
  }')

if echo "$RESPONSE" | grep -q '"error"'; then
  echo "Login status: ERROR"
  echo "Error: $(echo "$RESPONSE" | jq -r '.error.message // .error // .' 2>/dev/null)"
  exit 2
fi

# Server returns a human-readable text block like:
# "✅ 已登录\n用户名：xxx" or "❌ 未登录 ..."
TEXT="$(echo "$RESPONSE" | jq -r '.result.content[]? | select(.type=="text") | .text' 2>/dev/null || true)"
if echo "$TEXT" | grep -q "已登录"; then
  echo "Login status: OK"
  echo "$TEXT" | sed 's/\r$//'
  exit 0
fi

echo "Login status: NOT LOGGED IN - Authentication required"
[ -n "${TEXT:-}" ] && echo "$TEXT" | sed 's/\r$//'
exit 1
