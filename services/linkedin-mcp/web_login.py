"""Web server for phone-friendly LinkedIn cookie injection.

When a cookie is submitted:
1. Updates docker-compose.yml LINKEDIN_COOKIE env var
2. Clears stale browser profile
3. Restarts the LinkedIn MCP container
4. Sends Discord confirmation
"""

import http.server
import os
import re
import shutil
import subprocess
import sys
import urllib.parse

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8899
WORK_DIR = os.path.dirname(os.path.abspath(__file__))
COMPOSE_FILE = os.path.join(WORK_DIR, "docker-compose.yml")
PROFILE_DIR = os.path.join(WORK_DIR, "data", "profile")
DISCORD_CHANNEL = "1470566790710169661"

HTML = """<!DOCTYPE html>
<html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>LinkedIn Login</title>
<style>
body{font-family:system-ui;max-width:500px;margin:40px auto;padding:0 20px;background:#1a1a2e;color:#e0e0e0}
h2{color:#0a66c2}
textarea{width:100%;height:80px;margin:10px 0;font-size:16px;padding:10px;border-radius:8px;border:1px solid #333;background:#16213e;color:#e0e0e0;box-sizing:border-box}
button{background:#0a66c2;color:white;border:none;padding:14px 28px;font-size:18px;border-radius:8px;cursor:pointer;width:100%}
button:active{background:#004182}
.info{background:#16213e;padding:15px;border-radius:8px;margin:15px 0;font-size:14px;line-height:1.6}
.success{color:#4caf50;font-size:48px;margin:40px 0 20px;text-align:center}
.error{color:#f44336;font-size:24px;margin:40px 0 20px;text-align:center}
code{background:#0d1b2a;padding:2px 6px;border-radius:4px;font-size:13px}
a{color:#0a66c2}
.status{background:#0d1b2a;padding:10px;border-radius:8px;margin:10px 0;font-size:13px}
</style></head><body>
<h2>LinkedIn Cookie Login</h2>
<div class="info">
<b>How to get your <code>li_at</code> cookie:</b>
<p>1. Open <a href="https://www.linkedin.com">linkedin.com</a> in Chrome (logged in)</p>
<p>2. Tap the lock/tune icon in the URL bar</p>
<p>3. Tap <b>Cookies</b> > <b>linkedin.com</b> > <b>li_at</b></p>
<p>4. Long-press the value to copy it</p>
<hr style="border-color:#333">
<p><b>Desktop Chrome:</b> F12 > Application > Cookies > linkedin.com > li_at</p>
</div>
<form method="POST" action="/submit">
<textarea name="cookie" placeholder="Paste your li_at cookie value here..." required></textarea>
<button type="submit">Update Cookie & Restart</button>
</form>
<div class="status" id="status">Waiting for cookie...</div>
</body></html>"""

SUCCESS_HTML = """<!DOCTYPE html>
<html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Done!</title>
<style>body{font-family:system-ui;max-width:500px;margin:40px auto;padding:0 20px;background:#1a1a2e;color:#e0e0e0;text-align:center}
.success{color:#4caf50;font-size:48px;margin:40px 0 20px}
.detail{background:#16213e;padding:15px;border-radius:8px;margin:15px 0;font-size:14px;text-align:left;line-height:1.6}</style></head>
<body><div class="success">Done!</div>
<p>LinkedIn session updated and service restarted.</p>
<div class="detail">
<b>What happened:</b><br>
1. docker-compose.yml updated with new cookie<br>
2. Stale browser profile cleared<br>
3. Container restarted<br>
<br>
The next job search will use the new cookie.
</div>
<p>You can close this page.</p></body></html>"""

ERROR_HTML = """<!DOCTYPE html>
<html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Error</title>
<style>body{font-family:system-ui;max-width:500px;margin:40px auto;padding:0 20px;background:#1a1a2e;color:#e0e0e0;text-align:center}
.error{color:#f44336;font-size:24px;margin:40px 0 20px}a{color:#0a66c2}</style></head>
<body><div class="error">Error</div><p>%s</p><a href="/">Try again</a></body></html>"""


def update_compose_cookie(cookie_value):
    """Update LINKEDIN_COOKIE in docker-compose.yml."""
    with open(COMPOSE_FILE, "r") as f:
        text = f.read()
    new_text = re.sub(r"(LINKEDIN_COOKIE=)\S+", rf"\g<1>{cookie_value}", text)
    if new_text == text:
        return False
    with open(COMPOSE_FILE, "w") as f:
        f.write(new_text)
    return True


def clear_browser_profile():
    """Remove stale browser profile to avoid redirect loops."""
    if os.path.isdir(PROFILE_DIR):
        shutil.rmtree(PROFILE_DIR, ignore_errors=True)
        os.makedirs(PROFILE_DIR, exist_ok=True)
        return True
    return False


def send_discord(message):
    """Send Discord notification."""
    try:
        subprocess.run(
            [
                "/usr/local/bin/openclaw", "message", "send",
                "--channel", "discord",
                "--target", DISCORD_CHANNEL,
                "--message", message,
            ],
            capture_output=True, text=True, timeout=30,
        )
    except Exception:
        pass


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(HTML.encode())

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode()
        params = urllib.parse.parse_qs(body)
        cookie = params.get("cookie", [""])[0].strip()

        if not cookie or len(cookie) < 50:
            self._respond(400, ERROR_HTML % "Cookie value looks too short. Please try again.")
            return

        try:
            steps = []

            # Step 1: Update docker-compose.yml
            if update_compose_cookie(cookie):
                steps.append("docker-compose.yml updated")
            else:
                steps.append("docker-compose.yml update skipped (no change)")

            # Step 2: Clear browser profile
            if clear_browser_profile():
                steps.append("Browser profile cleared")

            # Step 3: Restart container
            subprocess.run(
                ["docker", "compose", "down"],
                cwd=WORK_DIR, capture_output=True, timeout=30,
            )
            subprocess.run(
                ["docker", "compose", "up", "-d"],
                cwd=WORK_DIR, capture_output=True, timeout=60,
            )
            steps.append("Container restarted")

            # Step 4: Update health state
            try:
                state_file = os.path.join(WORK_DIR, "data", "health_state.json")
                from datetime import datetime, timezone
                state = {}
                if os.path.exists(state_file):
                    with open(state_file) as f:
                        state = __import__("json").load(f)
                state["cookie_updated_at"] = datetime.now(timezone.utc).isoformat()
                state["consecutive_failures"] = 0
                with open(state_file, "w") as f:
                    __import__("json").dump(state, f, indent=2)
            except Exception:
                pass

            # Step 5: Notify Discord
            send_discord(
                f"**LinkedIn cookie updated!** Session should be working again.\n"
                f"Steps: {', '.join(steps)}"
            )

            self._respond(200, SUCCESS_HTML)
            print(f"[web] Cookie updated! ({', '.join(steps)})")

        except Exception as e:
            self._respond(500, ERROR_HTML % str(e))

    def _respond(self, code, html):
        self.send_response(code)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(html.encode())

    def log_message(self, fmt, *args):
        print(f"[web] {args[0]}")


if __name__ == "__main__":
    print(f"LinkedIn Cookie Web Login - serving on port {PORT}...")
    print(f"Open: http://localhost:{PORT}")
    http.server.HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
