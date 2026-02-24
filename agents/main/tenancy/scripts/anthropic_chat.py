#!/usr/bin/env python3
"""
Minimal Anthropic Messages API client for OpenClaw tenancy.

Inputs:
- ANTHROPIC_API_KEY env var
- CLI args: --model, --prompt, optional --system, --max-tokens

Output: JSON {ok, text, model, usage?}

No dependencies beyond stdlib.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request


API_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


def _fail(msg: str, *, details: str | None = None, code: int = 1) -> None:
    out = {"ok": False, "error": msg}
    if details:
        out["details"] = details[:2000]
    print(json.dumps(out, indent=2))
    sys.exit(code)


def _post_json(url: str, headers: dict[str, str], payload: dict) -> tuple[int, str]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return int(resp.status), resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return int(e.code), e.read().decode("utf-8", errors="replace")
    except Exception as e:
        _fail("request failed", details=f"{e.__class__.__name__}: {e}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True)
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--system", default="")
    ap.add_argument("--max-tokens", type=int, default=2048)
    args = ap.parse_args()

    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        _fail("missing ANTHROPIC_API_KEY")

    payload: dict = {
        "model": args.model,
        "max_tokens": int(args.max_tokens),
        "messages": [{"role": "user", "content": args.prompt}],
    }
    if args.system:
        payload["system"] = args.system

    status, raw = _post_json(
        API_URL,
        headers={
            "x-api-key": key,
            "anthropic-version": ANTHROPIC_VERSION,
        },
        payload=payload,
    )
    if status != 200:
        _fail("anthropic api error", details=raw)

    try:
        obj = json.loads(raw)
    except Exception:
        _fail("invalid json from anthropic", details=raw)

    # Extract text blocks
    text_parts: list[str] = []
    for block in obj.get("content") or []:
        if isinstance(block, dict) and block.get("type") == "text":
            text_parts.append(str(block.get("text") or ""))
    text = "".join(text_parts).strip()

    out = {
        "ok": True,
        "model": obj.get("model") or args.model,
        "text": text,
        "usage": obj.get("usage") or None,
        "stop_reason": obj.get("stop_reason") or None,
    }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()

