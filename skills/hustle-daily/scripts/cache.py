#!/usr/bin/env python3
"""Cache manager for hustle-daily newsletter.

Usage:
  python3 cache.py check          # Exit 0 + print newsletter if today's cache exists, exit 1 if not
  python3 cache.py save            # Read newsletter text from stdin, save as today's cache
  python3 cache.py cleanup         # Remove caches older than 7 days
"""

import os
import sys
from datetime import datetime, timedelta

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(SKILL_DIR, "data", "cache")


def today_str() -> str:
    """Today's date in Beijing time (UTC+8)."""
    from datetime import timezone
    bj = timezone(timedelta(hours=8))
    return datetime.now(bj).strftime("%Y-%m-%d")


def cache_path(date_str: str) -> str:
    return os.path.join(CACHE_DIR, f"{date_str}.md")


def cmd_check():
    today = today_str()
    path = cache_path(today)
    if os.path.exists(path):
        with open(path) as f:
            print(f.read())
        sys.exit(0)
    else:
        sys.exit(1)


def cmd_save():
    os.makedirs(CACHE_DIR, exist_ok=True)
    today = today_str()
    content = sys.stdin.read()
    if not content.strip():
        print("Empty input, not saving.", file=sys.stderr)
        sys.exit(1)
    with open(cache_path(today), "w") as f:
        f.write(content)
    print(f"Saved cache for {today}", file=sys.stderr)


def cmd_cleanup():
    if not os.path.exists(CACHE_DIR):
        return
    from datetime import timezone
    bj = timezone(timedelta(hours=8))
    cutoff = (datetime.now(bj) - timedelta(days=7)).strftime("%Y-%m-%d")
    removed = 0
    for fname in os.listdir(CACHE_DIR):
        if fname.endswith(".md") and fname[:10] < cutoff:
            os.remove(os.path.join(CACHE_DIR, fname))
            removed += 1
    print(f"Removed {removed} old cache files.", file=sys.stderr)


def main():
    if len(sys.argv) < 2:
        print("Usage: cache.py <check|save|cleanup>", file=sys.stderr)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "check":
        cmd_check()
    elif cmd == "save":
        cmd_save()
    elif cmd == "cleanup":
        cmd_cleanup()
    else:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
