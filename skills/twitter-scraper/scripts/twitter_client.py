#!/usr/bin/env python3
"""Twitter/X scraper CLI using twikit. Read-only operations."""

import argparse
import asyncio
import json
import os
import sys

from twikit import Client

COOKIES_PATH = "/root/.openclaw/services/twitter/cookies.json"
CREDS_PATH = "/root/.openclaw/credentials/twitter.json"


def load_credentials():
    try:
        with open(CREDS_PATH) as f:
            return json.load(f)
    except FileNotFoundError:
        print(json.dumps({"error": f"Credentials file not found: {CREDS_PATH}"}))
        sys.exit(1)


async def get_client():
    client = Client("en-US")
    if os.path.exists(COOKIES_PATH):
        client.load_cookies(COOKIES_PATH)
    else:
        print(json.dumps({
            "error": "No cookies file found. Login is blocked by Cloudflare on this server.",
            "fix": "Import cookies from your browser: python3 twitter_client.py import-cookies <auth_token> <ct0>"
        }))
        sys.exit(1)
    return client


def cmd_import_cookies(args):
    """Import auth_token and ct0 cookies from browser."""
    cookies = {
        "auth_token": args.auth_token,
        "ct0": args.ct0,
    }
    os.makedirs(os.path.dirname(COOKIES_PATH), exist_ok=True)
    with open(COOKIES_PATH, "w") as f:
        json.dump(cookies, f)
    print(json.dumps({"status": "ok", "message": f"Cookies saved to {COOKIES_PATH}"}))


async def cmd_search(args):
    client = await get_client()
    results = await client.search_tweet(args.query, product="Latest", count=args.count)
    tweets = []
    for t in results:
        tweets.append({
            "id": t.id,
            "user": t.user.screen_name if t.user else None,
            "name": t.user.name if t.user else None,
            "text": t.text,
            "created_at": t.created_at,
            "retweet_count": t.retweet_count,
            "favorite_count": t.favorite_count,
            "reply_count": t.reply_count,
        })
    print(json.dumps(tweets, indent=2, default=str))


async def cmd_user(args):
    client = await get_client()
    user = await client.get_user_by_screen_name(args.username)
    print(json.dumps({
        "id": user.id,
        "name": user.name,
        "screen_name": user.screen_name,
        "description": user.description,
        "followers_count": user.followers_count,
        "following_count": user.following_count,
        "statuses_count": user.statuses_count,
        "created_at": user.created_at,
        "location": user.location,
        "verified": user.verified,
        "profile_image_url": user.profile_image_url,
    }, indent=2, default=str))


async def cmd_tweets(args):
    client = await get_client()
    user = await client.get_user_by_screen_name(args.username)
    results = await user.get_tweets("Tweets", count=args.count)
    tweets = []
    for t in results:
        tweets.append({
            "id": t.id,
            "text": t.text,
            "created_at": t.created_at,
            "retweet_count": t.retweet_count,
            "favorite_count": t.favorite_count,
            "reply_count": t.reply_count,
        })
    print(json.dumps(tweets, indent=2, default=str))


async def cmd_trending(args):
    client = await get_client()
    trends = await client.get_trends("trending")
    items = []
    for t in trends:
        items.append({
            "name": t.name,
            "posts_count": getattr(t, "posts_count", None),
        })
    print(json.dumps(items, indent=2, default=str))


def main():
    parser = argparse.ArgumentParser(description="Twitter/X scraper CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    p_import = sub.add_parser("import-cookies", help="Import browser cookies")
    p_import.add_argument("auth_token", help="auth_token cookie from x.com")
    p_import.add_argument("ct0", help="ct0 cookie from x.com")

    p_search = sub.add_parser("search", help="Search tweets")
    p_search.add_argument("query", help="Search query")
    p_search.add_argument("--count", type=int, default=10, help="Number of results")

    p_user = sub.add_parser("user", help="Get user profile")
    p_user.add_argument("username", help="Twitter username (without @)")

    p_tweets = sub.add_parser("tweets", help="Get user's recent tweets")
    p_tweets.add_argument("username", help="Twitter username (without @)")
    p_tweets.add_argument("--count", type=int, default=10, help="Number of tweets")

    sub.add_parser("trending", help="Get trending topics")

    args = parser.parse_args()

    if args.command == "import-cookies":
        cmd_import_cookies(args)
        return

    handler = {
        "search": cmd_search,
        "user": cmd_user,
        "tweets": cmd_tweets,
        "trending": cmd_trending,
    }[args.command]

    asyncio.run(handler(args))


if __name__ == "__main__":
    main()
