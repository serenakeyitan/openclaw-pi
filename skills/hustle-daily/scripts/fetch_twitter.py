#!/usr/bin/env python3
"""Search Twitter for side-hustle content via twitter_client.py."""

import json
import os
import subprocess
import sys

# Try to find twitter-scraper as a sibling skill
_SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SKILLS_DIR = os.path.dirname(_SKILL_DIR)
TWITTER_CLIENT = os.path.join(_SKILLS_DIR, "twitter-scraper", "scripts", "twitter_client.py")

QUERIES = [
    "side hustle",
    "passive income",
    "make money online",
]

COUNT_PER_QUERY = 15


def run_search(query: str) -> list[dict]:
    """Run a twitter search query and return parsed results."""
    try:
        result = subprocess.run(
            ["python3", TWITTER_CLIENT, "search", query, "--count", str(COUNT_PER_QUERY)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            print(f"Twitter search error for '{query}': {result.stderr.strip()}", file=sys.stderr)
            return []

        return json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        print(f"Twitter search timed out for '{query}'", file=sys.stderr)
        return []
    except json.JSONDecodeError as e:
        print(f"Twitter search JSON error for '{query}': {e}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"Twitter search unexpected error for '{query}': {e}", file=sys.stderr)
        return []


def main():
    seen_ids = set()
    all_tweets = []

    for query in QUERIES:
        tweets = run_search(query)
        for tweet in tweets:
            tid = tweet.get("id")
            if tid and tid not in seen_ids:
                seen_ids.add(tid)
                all_tweets.append({
                    "id": tid,
                    "text": tweet.get("text", ""),
                    "user": tweet.get("user", ""),
                    "favorite_count": tweet.get("favorite_count", 0) or 0,
                    "retweet_count": tweet.get("retweet_count", 0) or 0,
                    "created_at": tweet.get("created_at", ""),
                })

    print(json.dumps(all_tweets, ensure_ascii=False))


if __name__ == "__main__":
    main()
