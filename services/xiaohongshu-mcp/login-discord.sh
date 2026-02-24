#!/bin/bash
# Login helper that sends the QR PNG to Discord via OpenClaw, then polls login status.
#
# Usage:
#   DISCORD_TARGET='channel:1470566790710169661' ./login-discord.sh
#   DISCORD_TARGET='user:YOUR_ID' ./login-discord.sh
#
# Notes:
# - Requires openclaw CLI on PATH
# - Uses MCP tools: get_login_qrcode + check_login_status

set -euo pipefail

MCP_URL="${MCP_URL:-http://localhost:18060/mcp}"
DISCORD_TARGET="${DISCORD_TARGET:-}"
DISCORD_ACCOUNT="${DISCORD_ACCOUNT:-}"
POLL_SECS="${POLL_SECS:-5}"
MAX_WAIT_SECS="${MAX_WAIT_SECS:-300}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
COOKIES_FILE="${SCRIPT_DIR}/data/cookies.json"

if [ -z "$DISCORD_TARGET" ]; then
  echo "DISCORD_TARGET is required. Example: DISCORD_TARGET='channel:1470566790710169661' ./login-discord.sh"
  exit 2
fi

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

init_body="$tmpdir/init.json"
init_headers="$tmpdir/init.headers"

curl -sS -D "$init_headers" -o "$init_body" -X POST "$MCP_URL" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"xhs-login-discord","version":"1.0.0"}},"id":1}'

SID="$(awk 'tolower($1)=="mcp-session-id:"{print $2}' "$init_headers" | tr -d '\r')"
if [ -z "${SID:-}" ]; then
  echo "Failed to read Mcp-Session-Id from initialize response headers."
  cat "$init_body"
  exit 1
fi

curl -sS -o /dev/null -X POST "$MCP_URL" \
  -H "Content-Type: application/json" \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}'

# Request QR code via MCP tool
QR_RESP="$(curl -sS -X POST "$MCP_URL" \
  -H "Content-Type: application/json" \
  -H "Mcp-Session-Id: $SID" \
  -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"get_login_qrcode","arguments":{}},"id":2}')"

if echo "$QR_RESP" | grep -q '"error"'; then
  echo "$QR_RESP" | jq -r '.error.message // .error // .' 2>/dev/null || echo "$QR_RESP"
  exit 1
fi

TEXT="$(echo "$QR_RESP" | jq -r '.result.content[]? | select(.type=="text") | .text' 2>/dev/null || true)"
PNG_B64="$(echo "$QR_RESP" | jq -r '.result.content[]? | select(.type=="image") | .data' 2>/dev/null | head -n 1 || true)"
if [ -z "${PNG_B64:-}" ] || [ "$PNG_B64" = "null" ]; then
  echo "No QR image returned. Raw response:"
  echo "$QR_RESP" | jq -C '.' 2>/dev/null || echo "$QR_RESP"
  exit 1
fi

QR_PNG="$tmpdir/xhs_login_qr.png"
PNG_B64="$PNG_B64" QR_PNG="$QR_PNG" python3 - <<'PY'
import base64, os, sys
raw = base64.b64decode(os.environ["PNG_B64"])
with open(os.environ["QR_PNG"], "wb") as f:
    f.write(raw)
PY

msg="【XHS Login】请用小红书 App 扫码登录。\\n${TEXT}"
send_args=(message send --channel discord --target "$DISCORD_TARGET" --message "$msg" --media "$QR_PNG")
if [ -n "$DISCORD_ACCOUNT" ]; then
  send_args+=(--account "$DISCORD_ACCOUNT")
fi
openclaw "${send_args[@]}" >/dev/null
echo "Sent QR to Discord target: $DISCORD_TARGET"

start="$(date +%s)"
while true; do
  now="$(date +%s)"
  elapsed=$(( now - start ))
  if [ "$elapsed" -ge "$MAX_WAIT_SECS" ]; then
    openclaw message send --channel discord --target "$DISCORD_TARGET" \
      --message "【XHS Login】超时未检测到登录成功（等待 ${MAX_WAIT_SECS}s）。请重新触发登录。 " >/dev/null || true
    echo "Timed out waiting for login."
    exit 1
  fi

  # Avoid hammering the service: check_login_status spins up a fresh browser and can be slow.
  # Prefer waiting for cookies.json to appear in the mounted volume.
  if [ -f "$COOKIES_FILE" ]; then
    STATUS_RESP="$(curl -sS -X POST "$MCP_URL" \
      -H "Content-Type: application/json" \
      -H "Mcp-Session-Id: $SID" \
      -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"check_login_status","arguments":{}},"id":3}')"

    if echo "$STATUS_RESP" | grep -q '"error"'; then
      err="$(echo "$STATUS_RESP" | jq -r '.error.message // .error // .' 2>/dev/null || true)"
      echo "check_login_status error (cookies.json exists): $err"
      sleep "$POLL_SECS"
      continue
    fi

    status_text="$(echo "$STATUS_RESP" | jq -r '.result.content[]? | select(.type=="text") | .text' 2>/dev/null || true)"
    if echo "$status_text" | grep -q "已登录"; then
      openclaw message send --channel discord --target "$DISCORD_TARGET" \
        --message "【XHS Login】登录成功（已写入 cookies.json）。\\n${status_text}" >/dev/null || true
      echo "Login OK."
      exit 0
    fi
  fi

  sleep "$POLL_SECS"
done
