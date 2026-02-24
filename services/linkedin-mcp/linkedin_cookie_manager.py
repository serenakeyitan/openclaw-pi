#!/usr/bin/env python3
"""LinkedIn MCP Cookie Manager & Health Check.

Monitors LinkedIn session health, sends Discord alerts on failure,
and provides easy cookie replacement that updates docker-compose.yml.

Commands:
    check           Quick health check (container + logs)
    update <cookie> Update cookie in docker-compose.yml, clear profile, restart
    status          Show current health state
    notify-expired  Send Discord alert about expired session
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

WORK_DIR = Path("/root/.openclaw/services/linkedin-mcp")
COMPOSE_FILE = WORK_DIR / "docker-compose.yml"
STATE_FILE = WORK_DIR / "data" / "health_state.json"
DISCORD_CHANNEL = "1470566790710169661"
WEB_LOGIN_PORT = 8899

AUTH_ERROR_PATTERNS = [
    "AuthenticationError",
    "Session expired or invalid",
    "authentication_failed",
    "ERR_TOO_MANY_REDIRECTS",
    "CredentialsNotFoundError",
    "No authentication found",
]


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {
            "last_check": None,
            "last_healthy": None,
            "last_alert_sent": None,
            "consecutive_failures": 0,
            "cookie_updated_at": None,
        }


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def get_tailscale_ip():
    try:
        r = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True, text=True, timeout=5,
        )
        return r.stdout.strip() or "localhost"
    except Exception:
        return "localhost"


def get_current_cookie():
    """Read li_at cookie from docker-compose.yml."""
    text = COMPOSE_FILE.read_text()
    match = re.search(r"LINKEDIN_COOKIE=(\S+)", text)
    return match.group(1) if match else None


def update_cookie_in_compose(new_cookie):
    """Replace LINKEDIN_COOKIE value in docker-compose.yml."""
    text = COMPOSE_FILE.read_text()
    new_text = re.sub(
        r"(LINKEDIN_COOKIE=)\S+",
        rf"\g<1>{new_cookie}",
        text,
    )
    if new_text == text:
        return False
    COMPOSE_FILE.write_text(new_text)
    return True


def container_running():
    r = subprocess.run(
        ["docker", "ps", "--filter", "name=linkedin-mcp", "--format", "{{.Status}}"],
        capture_output=True, text=True, timeout=10,
    )
    return "Up" in r.stdout


def check_logs_for_errors(since="6h"):
    """Check recent docker logs for auth failures."""
    r = subprocess.run(
        ["docker", "logs", "linkedin-mcp", f"--since={since}", "--tail=300"],
        capture_output=True, text=True, timeout=10,
    )
    logs = r.stdout + r.stderr
    found = [p for p in AUTH_ERROR_PATTERNS if p in logs]
    return found


def send_discord(message):
    """Send Discord notification via openclaw CLI."""
    try:
        r = subprocess.run(
            [
                "/usr/local/bin/openclaw", "message", "send",
                "--channel", "discord",
                "--target", DISCORD_CHANNEL,
                "--message", message,
            ],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0:
            print(f"Discord alert sent.")
            return True
        print(f"Discord send failed: {r.stderr}")
        return False
    except Exception as e:
        print(f"Discord send error: {e}")
        return False


def cmd_check():
    """Quick health check: container + recent logs."""
    state = load_state()
    state["last_check"] = now_iso()

    # 1. Container running?
    if not container_running():
        print("FAIL: Container not running")
        state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
        save_state(state)
        _maybe_alert(state, "LinkedIn MCP container is not running!")
        return 1

    # 2. Auth errors in recent logs? Check 24h window since job hunter runs daily.
    errors = check_logs_for_errors("24h")
    if errors:
        print(f"FAIL: Auth errors in logs: {', '.join(errors)}")
        state["consecutive_failures"] = state.get("consecutive_failures", 0) + 1
        save_state(state)
        _maybe_alert(state, f"LinkedIn cookie expired! Errors: {', '.join(errors)}")
        return 1

    # Healthy
    print("OK: LinkedIn MCP appears healthy")
    state["last_healthy"] = now_iso()
    state["consecutive_failures"] = 0
    save_state(state)
    return 0


def _maybe_alert(state, reason):
    """Send alert if we haven't alerted recently (throttle: 6h)."""
    last_alert = state.get("last_alert_sent")
    if last_alert:
        try:
            last_dt = datetime.fromisoformat(last_alert)
            elapsed = (datetime.now(timezone.utc) - last_dt).total_seconds()
            if elapsed < 6 * 3600:
                print(f"Alert throttled (last sent {int(elapsed)}s ago)")
                return
        except (ValueError, TypeError):
            pass

    ip = get_tailscale_ip()
    msg = (
        f"**LinkedIn MCP Session Expired**\n"
        f"{reason}\n\n"
        f"To fix: open LinkedIn in Chrome → F12 → Application → Cookies → linkedin.com → copy `li_at` value → DM it to me here.\n\n"
        f"Or paste it at: http://{ip}:{WEB_LOGIN_PORT}"
    )
    if send_discord(msg):
        state["last_alert_sent"] = now_iso()
        save_state(state)


def cmd_update(cookie_value):
    """Update cookie: compose file + clear profile + restart."""
    if not cookie_value or len(cookie_value) < 50:
        print("ERROR: Cookie value looks too short")
        return 1

    print(f"Updating cookie ({len(cookie_value)} chars)...")

    # 1. Update docker-compose.yml
    if update_cookie_in_compose(cookie_value):
        print("Updated docker-compose.yml")
    else:
        print("WARNING: Could not update docker-compose.yml (pattern not found)")

    # 2. Clear stale browser profile to avoid redirect loops
    profile_dir = WORK_DIR / "data" / "profile"
    if profile_dir.exists():
        import shutil
        shutil.rmtree(profile_dir, ignore_errors=True)
        profile_dir.mkdir(parents=True, exist_ok=True)
        print("Cleared stale browser profile")

    # 3. Restart container
    print("Restarting container...")
    subprocess.run(
        ["docker", "compose", "down"],
        cwd=str(WORK_DIR), capture_output=True, timeout=30,
    )
    subprocess.run(
        ["docker", "compose", "up", "-d"],
        cwd=str(WORK_DIR), capture_output=True, timeout=60,
    )
    print("Container restarted")

    # 4. Update state
    state = load_state()
    state["cookie_updated_at"] = now_iso()
    state["consecutive_failures"] = 0
    save_state(state)

    print("Done! The next MCP tool call will test the new cookie.")
    return 0


def cmd_notify_expired():
    """Force-send a Discord alert about expired session."""
    state = load_state()
    state["last_alert_sent"] = None  # bypass throttle
    save_state(state)
    _maybe_alert(state, "LinkedIn session needs a fresh cookie.")


def cmd_status():
    """Show current health state."""
    state = load_state()
    running = container_running()
    cookie = get_current_cookie()
    cookie_preview = f"{cookie[:20]}...{cookie[-10:]}" if cookie else "NOT SET"

    print(f"Container:     {'Running' if running else 'STOPPED'}")
    print(f"Cookie:        {cookie_preview}")
    print(f"Last check:    {state.get('last_check', 'never')}")
    print(f"Last healthy:  {state.get('last_healthy', 'never')}")
    print(f"Failures:      {state.get('consecutive_failures', 0)}")
    print(f"Cookie set:    {state.get('cookie_updated_at', 'unknown')}")
    print(f"Last alert:    {state.get('last_alert_sent', 'never')}")

    # Quick log check
    if running:
        errors = check_logs_for_errors("1h")
        if errors:
            print(f"Recent errors: {', '.join(errors)}")
        else:
            print("Recent errors: none")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    cmd = sys.argv[1]
    if cmd == "check":
        return cmd_check()
    elif cmd == "update":
        if len(sys.argv) < 3:
            print("Usage: linkedin_cookie_manager.py update <li_at_cookie_value>")
            return 1
        return cmd_update(sys.argv[2])
    elif cmd == "notify-expired":
        cmd_notify_expired()
        return 0
    elif cmd == "status":
        cmd_status()
        return 0
    else:
        print(f"Unknown command: {cmd}")
        print(__doc__)
        return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
