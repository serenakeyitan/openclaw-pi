#!/bin/bash
# Xiaohongshu MCP Installation Verification Script

echo "=========================================="
echo "Xiaohongshu MCP Installation Verification"
echo "=========================================="
echo ""

set -euo pipefail

MCP_URL="${MCP_URL:-http://localhost:18060/mcp}"

# Check 1: Service directory
echo "✓ Checking service directory..."
if [ -d "/root/.openclaw/services/xiaohongshu-mcp" ]; then
  echo "  Service directory exists"
  ls -la /root/.openclaw/services/xiaohongshu-mcp/
else
  echo "  ✗ Service directory missing"
fi
echo ""

# Check 2: Docker container
echo "✓ Checking Docker container..."
if docker ps | grep -q xiaohongshu-mcp; then
  echo "  Container is running:"
  docker ps | grep xiaohongshu-mcp
else
  echo "  ✗ Container not running"
  docker ps -a | grep xiaohongshu-mcp || echo "  ✗ Container not found"
fi
echo ""

# Check 3: SystemD service
echo "✓ Checking SystemD service..."
systemctl status xiaohongshu-mcp.service --no-pager | head -10
echo ""

# Check 4: HTTP endpoint
echo "✓ Checking HTTP endpoint..."
if curl -s -f "$MCP_URL" >/dev/null 2>&1; then
  echo "  HTTP endpoint is accessible at $MCP_URL"
else
  echo "  ✗ HTTP endpoint not accessible"
fi
echo ""

# Check 5: MCP plugin configuration
echo "✓ Checking MCP plugin files..."
if [ -f "/root/.claude/plugins/marketplaces/claude-plugins-official/external_plugins/xiaohongshu/.mcp.json" ]; then
  echo "  .mcp.json exists"
else
  echo "  ✗ .mcp.json missing"
fi

if [ -f "/root/.claude/plugins/marketplaces/claude-plugins-official/external_plugins/xiaohongshu/.claude-plugin/plugin.json" ]; then
  echo "  plugin.json exists"
else
  echo "  ✗ plugin.json missing"
fi
echo ""

# Check 6: Login status
echo "✓ Checking login status..."
/root/.openclaw/services/xiaohongshu-mcp/check-login.sh
echo ""

# Check 7: Available tools (requires initialized session)
echo "✓ Checking available MCP tools..."
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

init_body="$tmpdir/init.json"
init_headers="$tmpdir/init.headers"

curl -sS -D "$init_headers" -o "$init_body" -X POST "$MCP_URL" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"xhs-verify","version":"1.0.0"}},"id":1}'

SID="$(awk 'tolower($1)=="mcp-session-id:"{print $2}' "$init_headers" | tr -d '\r')"
if [ -z "${SID:-}" ]; then
  echo "  ✗ Missing Mcp-Session-Id header from initialize."
  echo "  Initialize response body:"
  cat "$init_body"
  echo ""
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
  echo "  Available tools:"
  echo "$TOOLS" | jq -r '.result.tools[]?.name // empty' | sed 's/^/    - /'
else
  echo "  Could not retrieve tools list"
  echo "$TOOLS"
fi
echo ""

echo "=========================================="
echo "Verification complete!"
echo ""
echo "Next steps:"
echo "1. If not logged in, run: ./login.sh"
echo "2. Restart OpenClaw to load the plugin: systemctl restart openclaw.service"
echo "3. Test via OpenClaw CLI or Discord bot"
echo "=========================================="
