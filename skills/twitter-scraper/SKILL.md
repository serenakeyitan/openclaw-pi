---
name: twitter-scraper
description: Search tweets, look up user profiles, get trending topics on Twitter/X
requires: python3, twikit
---

# Twitter Scraper Skill

Read-only Twitter/X data access via twikit.

## Commands

All commands return JSON. Run from any directory:

```bash
python3 /root/.openclaw/skills/twitter-scraper/scripts/twitter_client.py <command> [args]
```

### Search tweets
```bash
python3 /root/.openclaw/skills/twitter-scraper/scripts/twitter_client.py search "query" [--count N]
```
Returns: array of `{id, user, name, text, created_at, retweet_count, favorite_count, reply_count}`

### Get user profile
```bash
python3 /root/.openclaw/skills/twitter-scraper/scripts/twitter_client.py user <username>
```
Returns: `{id, name, screen_name, description, followers_count, following_count, statuses_count, created_at, location, verified, profile_image_url}`

### Get user's tweets
```bash
python3 /root/.openclaw/skills/twitter-scraper/scripts/twitter_client.py tweets <username> [--count N]
```
Returns: array of `{id, text, created_at, retweet_count, favorite_count, reply_count}`

### Get trending topics
```bash
python3 /root/.openclaw/skills/twitter-scraper/scripts/twitter_client.py trending
```
Returns: array of `{name, posts_count}`

### Import browser cookies (required for first setup)
Cloudflare blocks login from server IPs. Import cookies from your browser instead:
1. Log into x.com in your browser
2. Open DevTools → Application → Cookies → x.com
3. Copy the values of `auth_token` and `ct0`
4. Run:
```bash
python3 /root/.openclaw/skills/twitter-scraper/scripts/twitter_client.py import-cookies <auth_token> <ct0>
```

## Auth
- Cookies: `/root/.openclaw/services/twitter/cookies.json` (imported from browser)
- Credentials: `/root/.openclaw/credentials/twitter.json` (backup, login blocked by Cloudflare on server IPs)

## Rate Limits
Twitter rate-limits aggressively. Space out calls. Avoid rapid repeated queries.
