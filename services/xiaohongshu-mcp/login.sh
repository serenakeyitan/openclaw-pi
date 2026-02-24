#!/bin/bash
# Xiaohongshu MCP Login Helper
# This script retrieves the login QR code from the MCP server.
#
# Important: MCP over HTTP requires:
# 1) initialize (capture Mcp-Session-Id header)
# 2) notifications/initialized (with same Mcp-Session-Id)
# 3) tools/call

echo "Requesting login QR code from Xiaohongshu MCP..."
echo ""

set -euo pipefail

MCP_URL="${MCP_URL:-http://localhost:18060/mcp}"

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

init_body="$tmpdir/init.json"
init_headers="$tmpdir/init.headers"

# 1) initialize: capture session id from response header
curl -sS -D "$init_headers" -o "$init_body" -X POST "$MCP_URL" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"xhs-login","version":"1.0.0"}},"id":1}'

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

# Get login QR code
RESPONSE=$(curl -sS -X POST "$MCP_URL" \
  -H "Content-Type: application/json" \
  -H "Mcp-Session-Id: $SESSION_ID" \
  -d '{
    "jsonrpc": "2.0",
    "method": "tools/call",
    "params": {
      "name": "get_login_qrcode",
      "arguments": {}
    },
    "id": 2
  }')

# Check for errors
if echo "$RESPONSE" | grep -q '"error"'; then
  echo "Error getting QR code:"
  echo "$RESPONSE" | jq -r '.error.message // .error // .'
  exit 1
fi

# Extract and display QR instructions text (if present)
TEXT="$(echo "$RESPONSE" | jq -r '.result.content[]? | select(.type=="text") | .text' 2>/dev/null || true)"
[ -n "${TEXT:-}" ] && echo "$TEXT"

# Extract QR image (base64 PNG), write to a file for easy viewing/scanning
PNG_B64="$(echo "$RESPONSE" | jq -r '.result.content[]? | select(.type=="image") | .data' 2>/dev/null | head -n 1 || true)"
if [ -n "${PNG_B64:-}" ] && [ "$PNG_B64" != "null" ]; then
  QR_PNG="${QR_PNG:-/tmp/xhs_login_qr.png}"
  PNG_B64="$PNG_B64" QR_PNG="$QR_PNG" python3 - <<'PY'
import base64, os, sys
png_b64 = os.environ.get("PNG_B64","")
out = os.environ.get("QR_PNG","/tmp/xhs_login_qr.png")
try:
    raw = base64.b64decode(png_b64, validate=False)
except Exception as e:
    print(f"Failed to decode QR PNG base64: {e}", file=sys.stderr)
    sys.exit(2)
with open(out, "wb") as f:
    f.write(raw)
print(f"Saved QR PNG to: {out}")
PY
  # Render a terminal-friendly block QR (optional convenience)
  QR_PNG="$QR_PNG" python3 - <<'PY' || true
import os
from PIL import Image

path = os.environ.get("QR_PNG", "/tmp/xhs_login_qr.png")
im = Image.open(path).convert("L")
# Upscale for terminal readability without blurring edges
scale = 2
im = im.resize((im.size[0]*scale, im.size[1]*scale), Image.NEAREST)
# Threshold
im = im.point(lambda p: 0 if p < 128 else 255)
px = im.load()
w, h = im.size

lines = []
for y in range(0, h, 2):
    row = []
    for x in range(w):
        top = px[x, y] == 0
        bot = px[x, y+1] == 0 if y+1 < h else False
        if top and bot:
            row.append("█")
        elif top and not bot:
            row.append("▀")
        elif (not top) and bot:
            row.append("▄")
        else:
            row.append(" ")
    lines.append("".join(row))

border = " " * 2
print("\nQR (terminal render):")
for ln in lines:
    print(border + ln + border)
PY
else
  echo "No QR image returned (unexpected). Raw response:"
  echo "$RESPONSE" | jq -C '.' 2>/dev/null || echo "$RESPONSE"
  exit 1
fi

echo ""
echo "======================================================================"
echo "Please scan the QR code above with your Xiaohongshu mobile app"
echo "After scanning, wait a moment and then run ./check-login.sh to verify"
echo "======================================================================"
