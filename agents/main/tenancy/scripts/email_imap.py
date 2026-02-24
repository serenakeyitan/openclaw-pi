#!/usr/bin/env python3
"""
Minimal IMAP client helper for OpenClaw tenancy.

Reads config JSON (path passed via --config) that contains IMAP settings and
credentials. Outputs JSON only. Never prints passwords.
"""

from __future__ import annotations

import argparse
import email
import imaplib
import json
import re
import ssl
import sys
from datetime import datetime, timezone
from email.header import decode_header


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _fail(msg: str, *, code: int = 2) -> None:
    print(json.dumps({"ok": False, "error": msg}), flush=True)
    raise SystemExit(code)


def _decode_mime_header(value: str | None) -> str:
    if not value:
        return ""
    parts = []
    for chunk, enc in decode_header(value):
        if isinstance(chunk, bytes):
            try:
                parts.append(chunk.decode(enc or "utf-8", errors="replace"))
            except Exception:
                parts.append(chunk.decode("utf-8", errors="replace"))
        else:
            parts.append(str(chunk))
    return "".join(parts).strip()


def _normalize_text(s: str) -> str:
    # Collapse whitespace for compact snippets.
    return re.sub(r"\s+", " ", (s or "").strip())


def _connect(cfg: dict) -> imaplib.IMAP4:
    imap = cfg.get("imap") or {}
    host = str(imap.get("host") or "").strip()
    port = int(imap.get("port") or 993)
    use_ssl = bool(imap.get("ssl", True))
    if not host:
        _fail("missing imap.host")

    if use_ssl:
        ctx = ssl.create_default_context()
        conn: imaplib.IMAP4 = imaplib.IMAP4_SSL(host, port, ssl_context=ctx)
    else:
        conn = imaplib.IMAP4(host, port)

    user = str(cfg.get("username") or "").strip()
    password = str(cfg.get("password") or "").strip()
    if not user or not password:
        _fail("missing username/password")

    try:
        conn.login(user, password)
    except Exception as e:
        _fail(f"imap login failed: {e.__class__.__name__}")
    return conn


def cmd_inbox(args: argparse.Namespace) -> None:
    cfg = _load_json(args.config)
    mailbox = args.mailbox or "INBOX"
    limit = max(1, min(int(args.limit or 5), 50))

    conn = _connect(cfg)
    try:
        typ, _ = conn.select(mailbox, readonly=True)
        if typ != "OK":
            _fail("failed to select mailbox")

        # Get most recent message sequence numbers.
        typ, data = conn.search(None, "ALL")
        if typ != "OK" or not data or not data[0]:
            print(json.dumps({"ok": True, "messages": []}), flush=True)
            return

        ids = data[0].split()
        ids = ids[-limit:]
        out = []
        for mid in reversed(ids):
            typ, msg_data = conn.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])")
            if typ != "OK" or not msg_data:
                continue
            raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else b""
            m = email.message_from_bytes(raw)
            out.append(
                {
                    "id": mid.decode("ascii", errors="ignore"),
                    "from": _decode_mime_header(m.get("From")),
                    "subject": _decode_mime_header(m.get("Subject")),
                    "date": _decode_mime_header(m.get("Date")),
                }
            )
        print(json.dumps({"ok": True, "mailbox": mailbox, "messages": out}), flush=True)
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def _list_headers(conn: imaplib.IMAP4, ids: list[bytes], *, limit: int) -> list[dict]:
    out = []
    for mid in reversed(ids[-limit:]):
        typ, msg_data = conn.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID)])")
        if typ != "OK" or not msg_data:
            continue
        raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else b""
        m = email.message_from_bytes(raw)
        out.append(
            {
                "id": mid.decode("ascii", errors="ignore"),
                "from": _decode_mime_header(m.get("From")),
                "subject": _decode_mime_header(m.get("Subject")),
                "date": _decode_mime_header(m.get("Date")),
            }
        )
    return out


def cmd_unread(args: argparse.Namespace) -> None:
    cfg = _load_json(args.config)
    mailbox = args.mailbox or "INBOX"
    limit = max(1, min(int(args.limit or 5), 50))

    conn = _connect(cfg)
    try:
        typ, _ = conn.select(mailbox, readonly=True)
        if typ != "OK":
            _fail("failed to select mailbox")

        typ, data = conn.search(None, "UNSEEN")
        if typ != "OK" or not data or not data[0]:
            print(json.dumps({"ok": True, "mailbox": mailbox, "messages": []}), flush=True)
            return

        ids = data[0].split()
        out = _list_headers(conn, ids, limit=limit)
        print(json.dumps({"ok": True, "mailbox": mailbox, "messages": out}), flush=True)
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def _escape_imap_string(s: str) -> str:
    # Very small helper to avoid breaking IMAP search strings.
    return (s or "").replace("\\", "\\\\").replace('"', '\\"')


def cmd_search(args: argparse.Namespace) -> None:
    cfg = _load_json(args.config)
    mailbox = args.mailbox or "INBOX"
    limit = max(1, min(int(args.limit or 10), 50))
    query = str(args.query or "").strip()
    if not query:
        _fail("missing query")

    q = _escape_imap_string(query)
    conn = _connect(cfg)
    try:
        typ, _ = conn.select(mailbox, readonly=True)
        if typ != "OK":
            _fail("failed to select mailbox")

        # Conservative: OR SUBJECT/TEXT. If it looks like an address, try FROM first.
        if "@" in query and " " not in query:
            criteria = ["FROM", f"\"{q}\""]
        else:
            criteria = ["OR", "SUBJECT", f"\"{q}\"", "TEXT", f"\"{q}\""]

        typ, data = conn.search(None, *criteria)
        if typ != "OK" or not data or not data[0]:
            print(json.dumps({"ok": True, "mailbox": mailbox, "query": query, "messages": []}), flush=True)
            return

        ids = data[0].split()
        out = _list_headers(conn, ids, limit=limit)
        print(json.dumps({"ok": True, "mailbox": mailbox, "query": query, "messages": out}), flush=True)
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def cmd_read(args: argparse.Namespace) -> None:
    cfg = _load_json(args.config)
    mailbox = args.mailbox or "INBOX"
    mid = str(args.id or "").strip()
    if not mid:
        _fail("missing id")

    conn = _connect(cfg)
    try:
        typ, _ = conn.select(mailbox, readonly=True)
        if typ != "OK":
            _fail("failed to select mailbox")

        typ, msg_data = conn.fetch(mid.encode("ascii"), "(RFC822)")
        if typ != "OK" or not msg_data:
            _fail("message fetch failed")
        raw = msg_data[0][1] if isinstance(msg_data[0], tuple) else b""
        m = email.message_from_bytes(raw)

        body_text = ""
        if m.is_multipart():
            for part in m.walk():
                ctype = part.get_content_type()
                disp = (part.get("Content-Disposition") or "").lower()
                if "attachment" in disp:
                    continue
                if ctype == "text/plain":
                    payload = part.get_payload(decode=True) or b""
                    charset = part.get_content_charset() or "utf-8"
                    body_text = payload.decode(charset, errors="replace")
                    break
        else:
            payload = m.get_payload(decode=True) or b""
            charset = m.get_content_charset() or "utf-8"
            body_text = payload.decode(charset, errors="replace")

        text = body_text.strip()
        snippet = _normalize_text(text)[:2000]
        print(
            json.dumps(
                {
                    "ok": True,
                    "mailbox": mailbox,
                    "id": mid,
                    "from": _decode_mime_header(m.get("From")),
                    "subject": _decode_mime_header(m.get("Subject")),
                    "date": _decode_mime_header(m.get("Date")),
                    "snippet": snippet,
                }
            ),
            flush=True,
        )
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True, help="Path to config JSON (contains credentials).")
    sub = ap.add_subparsers(dest="cmd", required=True)

    inbox = sub.add_parser("inbox", help="List recent messages.")
    inbox.add_argument("--mailbox", default="INBOX")
    inbox.add_argument("--limit", type=int, default=5)
    inbox.set_defaults(fn=cmd_inbox)

    read = sub.add_parser("read", help="Read one message.")
    read.add_argument("--mailbox", default="INBOX")
    read.add_argument("--id", required=True)
    read.set_defaults(fn=cmd_read)

    unread = sub.add_parser("unread", help="List unread messages.")
    unread.add_argument("--mailbox", default="INBOX")
    unread.add_argument("--limit", type=int, default=5)
    unread.set_defaults(fn=cmd_unread)

    search = sub.add_parser("search", help="Search messages by subject/text/from.")
    search.add_argument("--mailbox", default="INBOX")
    search.add_argument("--limit", type=int, default=10)
    search.add_argument("--query", required=True)
    search.set_defaults(fn=cmd_search)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
