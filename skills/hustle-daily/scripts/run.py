#!/usr/bin/env python3
"""Orchestrator: fetch Reddit + Twitter, dedup, output top 30 candidates as JSON."""

import json
import os
import subprocess
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
FETCH_REDDIT = os.path.join(SCRIPTS_DIR, "fetch_reddit.py")
FETCH_TWITTER = os.path.join(SCRIPTS_DIR, "fetch_twitter.py")
DEDUP_SCRIPT = os.path.join(SCRIPTS_DIR, "dedup.py")

MAX_CANDIDATES = 30


def run_script(script_path: str) -> list[dict]:
    """Run a fetch script and parse its JSON output."""
    try:
        result = subprocess.run(
            ["python3", script_path],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.stderr:
            print(f"[{os.path.basename(script_path)}] {result.stderr.strip()}", file=sys.stderr)
        if result.returncode != 0:
            print(f"[{os.path.basename(script_path)}] exited with code {result.returncode}", file=sys.stderr)
            return []
        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        print(f"[{os.path.basename(script_path)}] timed out", file=sys.stderr)
        return []
    except json.JSONDecodeError as e:
        print(f"[{os.path.basename(script_path)}] JSON error: {e}", file=sys.stderr)
        return []


def normalize_reddit(posts: list[dict]) -> list[dict]:
    """Normalize Reddit posts to common format."""
    items = []
    for p in posts:
        items.append({
            "source": "reddit",
            "title": p.get("title", ""),
            "url": p.get("url", ""),
            "score": p.get("score", 0),
            "details": "",
            "created": p.get("created_utc", ""),
        })
    return items


def normalize_twitter(tweets: list[dict]) -> list[dict]:
    """Normalize Twitter tweets to common format."""
    items = []
    for t in tweets:
        text = t.get("text", "")
        # First sentence as title
        title = text.split(".")[0].split("\n")[0].strip()
        if len(title) > 120:
            title = title[:117] + "..."

        tweet_id = t.get("id", "")
        user = t.get("user", "")
        url = f"https://x.com/{user}/status/{tweet_id}" if user and tweet_id else ""

        fav = t.get("favorite_count", 0) or 0
        rt = t.get("retweet_count", 0) or 0

        items.append({
            "source": "twitter",
            "title": title,
            "url": url,
            "score": fav + rt,
            "details": text,
            "created": t.get("created_at", ""),
        })
    return items


def dedup_filter(items: list[dict]) -> list[dict]:
    """Pipe items through dedup.py filter."""
    try:
        result = subprocess.run(
            ["python3", DEDUP_SCRIPT, "filter"],
            input=json.dumps(items, ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.stderr:
            print(f"[dedup] {result.stderr.strip()}", file=sys.stderr)
        return json.loads(result.stdout)
    except Exception as e:
        print(f"[dedup] error: {e}", file=sys.stderr)
        # On dedup failure, return all items (better than nothing)
        return items


def main():
    print("Fetching Reddit posts...", file=sys.stderr)
    reddit_raw = run_script(FETCH_REDDIT)
    print(f"  Got {len(reddit_raw)} Reddit posts", file=sys.stderr)

    print("Fetching Twitter posts...", file=sys.stderr)
    twitter_raw = run_script(FETCH_TWITTER)
    print(f"  Got {len(twitter_raw)} Twitter posts", file=sys.stderr)

    # Normalize to common format
    reddit_items = normalize_reddit(reddit_raw)
    twitter_items = normalize_twitter(twitter_raw)
    all_items = reddit_items + twitter_items
    print(f"Total raw candidates: {len(all_items)}", file=sys.stderr)

    # Dedup against seen history
    unseen = dedup_filter(all_items)
    print(f"After dedup: {len(unseen)} unseen candidates", file=sys.stderr)

    # Sort by score descending
    unseen.sort(key=lambda x: x.get("score", 0), reverse=True)

    # Output top N
    candidates = unseen[:MAX_CANDIDATES]
    print(f"Outputting top {len(candidates)} candidates", file=sys.stderr)

    print(json.dumps(candidates, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
