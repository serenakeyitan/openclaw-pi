#!/usr/bin/env python3
"""
Gmail API helper for OpenClaw tenancy.

Reads a per-user config JSON that points at:
- OAuth client credentials.json (Desktop app)
- OAuth token JSON (includes refresh_token)

Commands (JSON output):
- inbox --limit N
- unread --limit N
- search --query Q --limit N
- read --id MSG_ID
- send --to TO --subject SUBJECT --body BODY

Notes:
- This is intended to be invoked by tenancy/runtime.mjs and should not print secrets.
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
except ImportError:
    print(json.dumps({"ok": False, "error": "missing google api libs"}))
    sys.exit(1)


def _fail(msg: str, code: int = 1) -> None:
    print(json.dumps({"ok": False, "error": msg}))
    sys.exit(code)


def _read_json(p: Path) -> dict[str, Any]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        _fail(f"failed to read json: {p} ({e.__class__.__name__})")


def _write_json(p: Path, obj: dict[str, Any]) -> None:
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2), encoding="utf-8")
    tmp.replace(p)


def _safe_email_filename(email: str) -> str:
    return re.sub(r"[^\w\-.]", "_", email.lower())


def _parse_rfc822_date(s: str) -> Optional[str]:
    # Keep it simple: return original string; caller can display.
    s = (s or "").strip()
    return s or None


def _header(payload: dict[str, Any], name: str) -> str:
    headers = payload.get("headers") or []
    for h in headers:
        if str(h.get("name", "")).lower() == name.lower():
            return str(h.get("value", "")).strip()
    return ""


def _decode_part(data_b64: str) -> str:
    try:
        raw = base64.urlsafe_b64decode(data_b64.encode("utf-8"))
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _extract_body(payload: dict[str, Any]) -> str:
    # Prefer text/plain, fallback to text/html.
    body = ""
    if payload.get("body", {}).get("data"):
        return _decode_part(payload["body"]["data"])
    parts = payload.get("parts") or []
    for p in parts:
        if p.get("mimeType") == "text/plain" and p.get("body", {}).get("data"):
            return _decode_part(p["body"]["data"])
    for p in parts:
        if p.get("mimeType") == "text/html" and p.get("body", {}).get("data"):
            body = _decode_part(p["body"]["data"])
            break
    return body


def _load_creds(creds_path: Path, token_path: Path, scopes: list[str]) -> Credentials:
    client = _read_json(creds_path)
    token = _read_json(token_path)

    root = "installed" if "installed" in client else "web" if "web" in client else None
    if not root:
        _fail("credentials.json missing installed/web section")

    expiry = None
    exp_s = token.get("expiry")
    if isinstance(exp_s, str) and exp_s:
        try:
            # google creds accept naive or aware; use aware UTC
            expiry = datetime.fromisoformat(exp_s.replace("Z", "+00:00"))
        except Exception:
            expiry = None

    creds = Credentials(
        token=token.get("access_token"),
        refresh_token=token.get("refresh_token"),
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client[root].get("client_id"),
        client_secret=client[root].get("client_secret"),
        scopes=scopes,
        expiry=expiry,
    )

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            # persist refreshed token
            token["access_token"] = creds.token
            if creds.expiry:
                token["expiry"] = creds.expiry.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            _write_json(token_path, token)
        else:
            _fail("oauth token invalid and cannot refresh")

    return creds


def _gmail(creds: Credentials):
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _message_summary(svc, msg_id: str) -> dict[str, Any]:
    m = svc.users().messages().get(userId="me", id=msg_id, format="metadata").execute()
    payload = m.get("payload") or {}
    out = {
        "id": m.get("id"),
        "threadId": m.get("threadId"),
        "from": _header(payload, "From"),
        "subject": _header(payload, "Subject"),
        "date": _parse_rfc822_date(_header(payload, "Date")),
        "snippet": m.get("snippet", ""),
    }
    return out


def cmd_listlike(svc, *, query: str, limit: int) -> None:
    res = svc.users().messages().list(userId="me", q=query, maxResults=limit).execute()
    msgs = res.get("messages") or []
    out = []
    for m in msgs:
        try:
            out.append(_message_summary(svc, m.get("id")))
        except Exception:
            continue
    print(json.dumps({"ok": True, "messages": out, "total": len(out)}, indent=2))


def cmd_read(svc, *, msg_id: str) -> None:
    m = svc.users().messages().get(userId="me", id=msg_id, format="full").execute()
    payload = m.get("payload") or {}
    body = _extract_body(payload)
    out = {
        "ok": True,
        "id": m.get("id"),
        "threadId": m.get("threadId"),
        "from": _header(payload, "From"),
        "to": _header(payload, "To"),
        "subject": _header(payload, "Subject"),
        "date": _parse_rfc822_date(_header(payload, "Date")),
        "snippet": m.get("snippet", ""),
        "body": body[:12000],
    }
    print(json.dumps(out, indent=2))


def _encode_rfc822(to: str, subject: str, body: str) -> str:
    # Very small, good-enough RFC822 for text/plain.
    # Caller must provide already-sane inputs; we strip newlines from headers.
    to_h = (to or "").replace("\r", "").replace("\n", "").strip()
    subj_h = (subject or "").replace("\r", "").replace("\n", "").strip()
    msg = f"To: {to_h}\r\nSubject: {subj_h}\r\nContent-Type: text/plain; charset=UTF-8\r\n\r\n{body or ''}"
    raw = msg.encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def cmd_send(svc, *, to: str, subject: str, body: str) -> None:
    raw = _encode_rfc822(to=to, subject=subject, body=body)
    res = svc.users().messages().send(userId="me", body={"raw": raw}).execute()
    out = {"ok": True, "id": res.get("id"), "threadId": res.get("threadId")}
    print(json.dumps(out, indent=2))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_inbox = sub.add_parser("inbox")
    p_inbox.add_argument("--limit", type=int, default=5)

    p_unread = sub.add_parser("unread")
    p_unread.add_argument("--limit", type=int, default=5)

    p_search = sub.add_parser("search")
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--limit", type=int, default=5)

    p_read = sub.add_parser("read")
    p_read.add_argument("--id", required=True)

    p_send = sub.add_parser("send")
    p_send.add_argument("--to", required=True)
    p_send.add_argument("--subject", default="")
    p_send.add_argument("--body", default="")

    args = ap.parse_args()
    cfg = _read_json(Path(args.config))

    creds_path = Path(str(cfg.get("oauth_credentials_path") or "")).expanduser()
    token_path = Path(str(cfg.get("oauth_token_path") or "")).expanduser()
    if not creds_path.exists():
        _fail("missing oauth_credentials_path")
    if not token_path.exists():
        _fail("missing oauth_token_path")

    scopes = cfg.get("scopes")
    if not isinstance(scopes, list) or not scopes:
        scopes = [
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.modify",
        ]

    creds = _load_creds(creds_path, token_path, scopes=scopes)
    svc = _gmail(creds)

    if args.cmd == "inbox":
        cmd_listlike(svc, query="in:inbox", limit=max(1, min(int(args.limit), 50)))
        return
    if args.cmd == "unread":
        cmd_listlike(svc, query="in:inbox is:unread", limit=max(1, min(int(args.limit), 50)))
        return
    if args.cmd == "search":
        cmd_listlike(svc, query=str(args.query), limit=max(1, min(int(args.limit), 50)))
        return
    if args.cmd == "read":
        cmd_read(svc, msg_id=str(args.id))
        return
    if args.cmd == "send":
        cmd_send(svc, to=str(args.to), subject=str(args.subject), body=str(args.body))
        return

    _fail("unknown cmd")


if __name__ == "__main__":
    main()
