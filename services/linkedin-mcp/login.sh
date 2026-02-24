#!/usr/bin/env bash
# LinkedIn MCP - Login helper
#
# Usage:
#   bash login.sh browser           # Opens Chromium on local display for login (recommended)
#   bash login.sh web               # Phone-friendly: opens a web form for cookie paste
#   bash login.sh cookie <value>    # Direct: paste li_at cookie value
set -euo pipefail

cd "$(dirname "$0")"

IMAGE="stickerdaniel/linkedin-mcp-server:3.0.1"
TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "localhost")
WEB_PORT=8899

browser_login() {
    echo "Stopping LinkedIn MCP service..."
    docker compose down 2>/dev/null || true

    # Allow Docker to access the X display
    xhost +local:docker 2>/dev/null || true

    echo ""
    echo "=========================================="
    echo "  Opening Chromium for LinkedIn login"
    echo "  You have 5 minutes to log in."
    echo "  Handles 2FA, captcha, etc."
    echo "=========================================="
    echo ""

    docker run --rm \
        -v "$(pwd)/data/profile:/home/pwuser/.linkedin-mcp/profile" \
        -e DISPLAY="${DISPLAY:-:0}" \
        -v /tmp/.X11-unix:/tmp/.X11-unix \
        "$IMAGE" \
        --get-session --no-headless --log-level INFO

    echo ""
    echo "Verifying session..."
    docker run --rm \
        -v "$(pwd)/data/profile:/home/pwuser/.linkedin-mcp/profile" \
        "$IMAGE" \
        --session-info

    echo ""
    echo "Starting LinkedIn MCP service..."
    docker compose up -d
    echo "Done!"
}

inject_cookie() {
    local cookie_val="$1"
    echo "Injecting li_at cookie into LinkedIn MCP profile..."
    docker compose down 2>/dev/null || true

    docker run --rm \
        -v "$(pwd)/data/profile:/home/pwuser/.linkedin-mcp/profile" \
        -v "$(pwd)/inject_cookie.py:/tmp/inject_cookie.py:ro" \
        --entrypoint python3 \
        "$IMAGE" \
        /tmp/inject_cookie.py "$cookie_val"

    echo ""
    echo "Starting LinkedIn MCP service..."
    docker compose up -d
    echo "Done!"
}

start_web() {
    docker compose down 2>/dev/null || true
    echo ""
    echo "=========================================="
    echo "  Open this URL on your phone:"
    echo ""
    echo "  http://${TAILSCALE_IP}:${WEB_PORT}"
    echo ""
    echo "=========================================="
    echo ""
    echo "Paste your li_at cookie there and hit Submit."
    echo "Press Ctrl+C when done."
    echo ""
    python3 "$(pwd)/web_login.py" "${WEB_PORT}" || true
}

case "${1:-}" in
    browser)
        browser_login
        ;;
    cookie)
        if [ -z "${2:-}" ]; then
            echo "Usage: bash login.sh cookie <li_at_cookie_value>"
            exit 1
        fi
        inject_cookie "$2"
        ;;
    web)
        start_web
        ;;
    *)
        echo "LinkedIn MCP Login Helper"
        echo ""
        echo "Usage:"
        echo "  bash login.sh browser           # Opens Chromium on display for login (recommended)"
        echo "  bash login.sh web               # Phone-friendly: web form for cookie paste"
        echo "  bash login.sh cookie <value>    # Direct: paste li_at cookie value"
        echo ""
        echo "Recommended: bash login.sh browser"
        ;;
esac
