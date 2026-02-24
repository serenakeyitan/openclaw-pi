#!/bin/bash
# Test Xiaohongshu MCP endpoint

echo "Testing Xiaohongshu MCP Server..."
echo ""

set -euo pipefail

MCP_URL="${MCP_URL:-http://localhost:18060/mcp}"

# Test 1: Check if port is accessible
echo "1. Testing port accessibility..."
if nc -z localhost 18060 2>/dev/null; then
  echo "   ✓ Port 18060 is accessible"
else
  echo "   ✗ Port 18060 is not accessible"
  exit 1
fi
echo ""

# Test 2: MCP protocol handshake + tools/list
echo "2. Testing MCP handshake + tools/list..."
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

init_body="$tmpdir/init.json"
init_headers="$tmpdir/init.headers"

curl -sS -D "$init_headers" -o "$init_body" -X POST "$MCP_URL" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"xhs-test","version":"1.0.0"}},"id":1}'

SID="$(awk 'tolower($1)=="mcp-session-id:"{print $2}' "$init_headers" | tr -d '\r')"
if [ -z "${SID:-}" ]; then
  echo "   ✗ Missing Mcp-Session-Id header."
  echo "Initialize body:"
  cat "$init_body"
  exit 1
fi

curl -sS -o /dev/null -X POST "$MCP_URL" \
  -H "Content-Type: application/json" \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}'

TOOLS=$(curl -sS -X POST "$MCP_URL" \
  -H "Content-Type: application/json" \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","method":"tools/list","params":{},"id":2}')

if echo "$TOOLS" | grep -q '"tools"'; then
  echo "   ✓ tools/list successful"
  echo "$TOOLS" | jq -r '.result.tools[]?.name // empty' 2>/dev/null | sed 's/^/     - /' || true
else
  echo "   ✗ tools/list failed:"
  echo "$TOOLS" | jq -C '.' 2>/dev/null || echo "$TOOLS"
  exit 1
fi
echo ""

echo "3. MCP server appears to be running correctly!"
echo "   - HTTP endpoint is responding"
echo "   - MCP handshake works (initialize + notifications/initialized)"
echo "   - tools/list returned tools"
