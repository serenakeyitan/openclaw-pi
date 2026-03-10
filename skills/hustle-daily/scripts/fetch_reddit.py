#!/usr/bin/env python3
"""Fetch top side-hustle posts from Reddit's public JSON API."""

import json
import sys
import time

try:
    import requests
except ImportError:
    print("Error: 'requests' package is required. Install with: pip3 install requests", file=sys.stderr)
    print("[]")
    sys.exit(0)

SUBREDDITS = [
    "sidehustle",
    "beermoney",
    "passive_income",
    "Entrepreneur",
    "sweatystartup",
]

HEADERS = {
    "User-Agent": "hustle-daily/1.0 (linux; bot)",
}

THIRTY_DAYS_AGO = time.time() - 30 * 86400


def fetch_subreddit(sub: str) -> list[dict]:
    """Fetch top posts from a subreddit for the past week."""
    url = f"https://www.reddit.com/r/{sub}/top.json"
    params = {"t": "week", "limit": 25, "raw_json": 1}

    try:
        resp = requests.get(url, headers=HEADERS, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"Error fetching r/{sub}: {e}", file=sys.stderr)
        return []

    posts = []
    for child in data.get("data", {}).get("children", []):
        p = child.get("data", {})
        created = p.get("created_utc", 0)

        # Only posts from the last 30 days
        if created < THIRTY_DAYS_AGO:
            continue

        posts.append({
            "title": p.get("title", ""),
            "url": f"https://www.reddit.com{p.get('permalink', '')}",
            "permalink": p.get("permalink", ""),
            "score": p.get("score", 0),
            "num_comments": p.get("num_comments", 0),
            "subreddit": p.get("subreddit", sub),
            "created_utc": created,
        })

    return posts


def main():
    all_posts = []
    for sub in SUBREDDITS:
        posts = fetch_subreddit(sub)
        all_posts.extend(posts)
        # Be polite to Reddit's API
        time.sleep(1)

    print(json.dumps(all_posts, ensure_ascii=False))


if __name__ == "__main__":
    main()
