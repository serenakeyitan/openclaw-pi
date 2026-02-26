---
name: ops-standup
description: Daily ops team standup collection via Feishu DMs. Collects work updates from team members, tracks social media posts with engagement metrics, and generates daily summaries.
metadata: {"clawdbot":{"emoji":"📋","requires":{"bins":["python3"]}}}
---

# Ops Standup Skill

Automated daily standup for the ops team (4 people). Collects work updates via Feishu DM, tracks social media post engagement, and posts a Feishu card summary to the ops group chat.

## Flow

1. **Anytime**: Team members can DM the bot with their work update at any time. The bot records it immediately and replies "已记录 ✓".
2. **9:00 AM Beijing** (cron: `ops-standup-morning`): Check calendar. Send a reminder DM **only to members who haven't submitted yet**. Mentions the 10:00 deadline.
3. **10:00 AM Beijing** (cron: `ops-standup-summary`): Refresh 7-day post engagement data, send Feishu card summary to ops group chat.

## Realtime Reply Handling (anytime)

When a Feishu DM arrives from a known team member (match sender open_id against `ops-standup-members.json`):

1. If no active standup state for today, auto-init it:
   ```bash
   python3 /root/.openclaw/skills/ops-standup/scripts/parse_standup_reply.py --reset-day
   ```

2. Parse the reply:
   ```bash
   python3 /root/.openclaw/skills/ops-standup/scripts/parse_standup_reply.py --person "NAME" --message "their reply text"
   ```
   - Extracts URLs and identifies platforms (XHS, Twitter/X, Reddit, TikTok, YouTube, LinkedIn)
   - Non-URL text becomes task descriptions
   - Updates state JSON + daily log + marketing record

3. For each URL returned, use WebFetch to grab engagement data, then:
   ```bash
   python3 /root/.openclaw/skills/ops-standup/scripts/parse_standup_reply.py --update-metrics --url "URL" --metrics '{"likes": 56, "comments": 7}'
   ```

4. Reply to the user: "已记录 ✓"

## Morning Reminder (9:00 AM cron)

```bash
python3 /root/.openclaw/skills/ops-standup/scripts/feishu_calendar_check.py
```
Exit 0 = proceed, exit 1 = skip. Then check current state — if not active for today, reset it.

**Only DM members who haven't replied yet:**
```
openclaw message send --channel feishu --account main --target user:<open_id> \
  --message "早上好！请回复今天的工作内容和进展，如果发了社交媒体帖子请附链接。10:00 会汇总发到群里 📋"
```

## Summary (10:00 AM cron)

```bash
# Send Feishu card directly to group chat
python3 /root/.openclaw/skills/ops-standup/scripts/generate_summary.py --send-chat <CHAT_ID>
```

Card format (schema 2.0, blue header):
- Replied members: bold name + markdown bullet tasks + post links
- Unreplied members: grouped with ⚠️ 未提交
- Two button links at bottom: 📝 Standup 日志 + 📊 发帖 Tracker

## Feishu Docs

| Doc | ID | Purpose |
|-----|----|---------|
| Standup 日志 | `GZl3dtwymodYfFxsroMcf0QbnTe` | Daily work log |
| 发帖 Tracker | `TN2Cd0FXOo0ZSoxHJ16cYdzInye` | Post engagement tracking |

## Data Files

| File | Location | Purpose |
|------|----------|---------|
| Members registry | `workspace/memory/ops-standup-members.json` | name → open_id mapping |
| Daily state | `workspace/memory/ops-standup-state.json` | Today's standup progress |
| Post tracker | `workspace/memory/ops-standup-posts.json` | All tracked posts + doc IDs |
| Daily log | `workspace/ops-daily-log.md` | Running daily work log |
| Marketing record | `workspace/marketing-record.md` | Post tracking table |

## URL Platform Detection

| Pattern | Platform |
|---------|----------|
| `xiaohongshu.com` or `xhslink.com` | XHS |
| `x.com` or `twitter.com` | Twitter/X |
| `reddit.com` | Reddit |
| `tiktok.com` or `vm.tiktok.com` | TikTok |
| `youtube.com` or `youtu.be` | YouTube |
| `linkedin.com` | LinkedIn |

## Engagement Extraction (WebFetch)

| Platform | Metrics |
|----------|---------|
| XHS | 点赞, 评论, 收藏 |
| Twitter/X | likes, retweets, replies, views |
| Reddit | upvotes, comments |
| TikTok | views, likes, comments, shares |
| YouTube | views, likes, comments |
| LinkedIn | likes, comments |

Failures → leave metrics as-is, mark "待手动填写".
