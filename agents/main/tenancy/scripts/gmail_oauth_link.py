#!/usr/bin/env python3
"""
OAuth "auth-start" / "auth-finish" helper for Gmail desktop OAuth clients.

This does NOT require a localhost callback server to be reachable. The user:
1) Opens auth_url and approves
2) Gets redirected to http://127.0.0.1:PORT/?code=...&state=... (may error)
3) Copies that full URL from the address bar
4) We exchange code->tokens server-side using the saved redirect_uri

All output is JSON.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


DEFAULT_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/userinfo.email",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _fail(msg: str, *, extra: dict[str, Any] | None = None, code: int = 1) -> None:
    obj: dict[str, Any] = {"ok": False, "error": msg}
    if extra:
        obj.update(extra)
    print(json.dumps(obj, indent=2))
    sys.exit(code)


def _read_json(p: Path) -> dict[str, Any]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        _fail(f"failed to read json: {p} ({e.__class__.__name__})")


def _write_json(p: Path, obj: dict[str, Any], mode: int = 0o600) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    os.chmod(tmp, mode)
    tmp.replace(p)


def _find_free_port() -> int:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return int(s.getsockname()[1])


def _http_post_form(url: str, data: dict[str, str]) -> tuple[int, str]:
    body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return int(resp.status), resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return int(e.code), e.read().decode("utf-8", errors="replace")
    except Exception as e:
        _fail(f"http post failed ({e.__class__.__name__})")


def _http_get_json(url: str, headers: dict[str, str]) -> Optional[dict[str, Any]]:
    req = urllib.request.Request(url, method="GET")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw)
    except Exception:
        return None


def _load_client(creds_path: Path) -> dict[str, Any]:
    obj = _read_json(creds_path)
    root = "installed" if "installed" in obj else "web" if "web" in obj else None
    if not root:
        _fail("credentials.json missing installed/web section")
    client_id = str(obj[root].get("client_id") or "").strip()
    client_secret = str(obj[root].get("client_secret") or "").strip()
    if not client_id or not client_secret:
        _fail("credentials.json missing client_id/client_secret")
    return {"client_id": client_id, "client_secret": client_secret}


def cmd_auth_start(args: argparse.Namespace) -> None:
    creds_path = Path(args.creds).expanduser()
    pending_path = Path(args.pending).expanduser()
    if not creds_path.exists():
        _fail("missing creds file")

    client = _load_client(creds_path)
    port = _find_free_port()
    redirect_uri = f"http://127.0.0.1:{port}"
    state = secrets.token_urlsafe(32)

    scopes = DEFAULT_SCOPES
    scope_str = " ".join(scopes)

    params: dict[str, str] = {
        "client_id": client["client_id"],
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": scope_str,
        "access_type": "offline",
        "state": state,
        "prompt": "consent",
    }
    if args.login_hint:
        params["login_hint"] = str(args.login_hint).strip()

    auth_url = f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"
    pending = {
        "created_at": _now_iso(),
        "state": state,
        "redirect_uri": redirect_uri,
        "scopes": scopes,
    }
    _write_json(pending_path, pending, mode=0o600)
    print(json.dumps({"ok": True, "auth_url": auth_url, "redirect_uri": redirect_uri, "pending_path": str(pending_path)}, indent=2))


def cmd_auth_finish(args: argparse.Namespace) -> None:
    creds_path = Path(args.creds).expanduser()
    pending_path = Path(args.pending).expanduser()
    token_out = Path(args.token_out).expanduser()
    callback_url = str(args.callback_url or "").strip()

    if not callback_url:
        _fail("missing callback_url")
    if not creds_path.exists():
        _fail("missing creds file")
    if not pending_path.exists():
        _fail("missing pending file; run auth-start again")

    pending = _read_json(pending_path)
    expected_state = str(pending.get("state") or "")
    redirect_uri = str(pending.get("redirect_uri") or "")
    if not expected_state or not redirect_uri:
        _fail("pending file invalid; run auth-start again")

    parsed = urllib.parse.urlparse(callback_url)
    q = urllib.parse.parse_qs(parsed.query)
    code = (q.get("code") or [None])[0]
    state = (q.get("state") or [None])[0]
    err = (q.get("error") or [None])[0]

    if err:
        _fail(f"oauth_error:{err}")
    if not code:
        _fail("callback_url missing ?code=")
    if state and state != expected_state:
        _fail("state mismatch; run auth-start again")

    client = _load_client(creds_path)

    status, raw = _http_post_form(GOOGLE_TOKEN_URL, {
        "client_id": client["client_id"],
        "client_secret": client["client_secret"],
        "code": str(code),
        "grant_type": "authorization_code",
        "redirect_uri": redirect_uri,
    })
    if status != 200:
        _fail("token exchange failed", extra={"details": raw})

    try:
        tok = json.loads(raw)
    except Exception:
        _fail("token exchange returned invalid json")

    if "expires_in" in tok:
        try:
            expiry = datetime.now(timezone.utc) + timedelta(seconds=int(tok["expires_in"]))
            tok["expiry"] = expiry.isoformat().replace("+00:00", "Z")
        except Exception:
            pass

    # attach email if possible
    access_token = str(tok.get("access_token") or "")
    if access_token:
        info = _http_get_json(GOOGLE_USERINFO_URL, {"Authorization": f"Bearer {access_token}"})
        if info and isinstance(info, dict) and info.get("email"):
            tok["email"] = info.get("email")

    _write_json(token_out, tok, mode=0o600)
    try:
        pending_path.unlink()
    except Exception:
        pass
    print(json.dumps({"ok": True, "email": tok.get("email"), "token_out": str(token_out)}, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p1 = sub.add_parser("auth-start")
    p1.add_argument("--creds", required=True)
    p1.add_argument("--pending", required=True)
    p1.add_argument("--login-hint", default=None)
    p1.set_defaults(func=cmd_auth_start)

    p2 = sub.add_parser("auth-finish")
    p2.add_argument("--creds", required=True)
    p2.add_argument("--pending", required=True)
    p2.add_argument("--token-out", required=True)
    p2.add_argument("--callback-url", required=True)
    p2.set_defaults(func=cmd_auth_finish)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
