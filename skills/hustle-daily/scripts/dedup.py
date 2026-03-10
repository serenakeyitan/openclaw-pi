#!/usr/bin/env python3
"""Dedup manager with 30-day rolling window.

Usage:
  echo '<json_array>' | python3 dedup.py filter   # Output unseen items (does NOT mark)
  echo '<json_array>' | python3 dedup.py mark      # Mark items as seen
  python3 dedup.py cleanup                         # Remove entries older than 30 days
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timedelta

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = os.path.join(SKILL_DIR, "data", "seen.json")


def load_state() -> dict:
    """Load the seen-items state file."""
    if not os.path.exists(STATE_FILE):
        return {"seen": {}}
    try:
        with open(STATE_FILE) as f:
            data = json.load(f)
        if "seen" not in data:
            data["seen"] = {}
        return data
    except (json.JSONDecodeError, IOError):
        return {"seen": {}}


def save_state(state: dict):
    """Save state to disk."""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def make_hash(text: str) -> str:
    """Create a SHA256 hash of normalized text."""
    normalized = text.lower().strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def get_item_text(item: dict) -> str:
    """Extract the text to hash from an item."""
    # Works with both raw source items and normalized items
    return item.get("title", "") or item.get("text", "")


def cmd_filter():
    """Read JSON from stdin, output only unseen items."""
    state = load_state()
    seen = state["seen"]

    try:
        items = json.loads(sys.stdin.read())
    except json.JSONDecodeError as e:
        print(f"Invalid JSON input: {e}", file=sys.stderr)
        print("[]")
        return

    unseen = []
    for item in items:
        text = get_item_text(item)
        if not text:
            continue
        h = make_hash(text)
        if h not in seen:
            unseen.append(item)

    print(json.dumps(unseen, ensure_ascii=False))


def cmd_mark():
    """Read JSON from stdin, mark items as seen."""
    state = load_state()
    today = datetime.now().strftime("%Y-%m-%d")

    try:
        items = json.loads(sys.stdin.read())
    except json.JSONDecodeError as e:
        print(f"Invalid JSON input: {e}", file=sys.stderr)
        return

    count = 0
    for item in items:
        text = get_item_text(item)
        if not text:
            continue
        h = make_hash(text)
        state["seen"][h] = today
        count += 1

    save_state(state)
    print(f"Marked {count} items as seen.", file=sys.stderr)


def cmd_cleanup():
    """Remove entries older than 30 days."""
    state = load_state()
    cutoff = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

    before = len(state["seen"])
    state["seen"] = {
        h: date for h, date in state["seen"].items()
        if date >= cutoff
    }
    after = len(state["seen"])

    save_state(state)
    removed = before - after
    print(f"Cleanup: removed {removed} old entries, {after} remaining.", file=sys.stderr)


def main():
    if len(sys.argv) < 2:
        print("Usage: dedup.py <filter|mark|cleanup>", file=sys.stderr)
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "filter":
        cmd_filter()
    elif cmd == "mark":
        cmd_mark()
    elif cmd == "cleanup":
        cmd_cleanup()
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
