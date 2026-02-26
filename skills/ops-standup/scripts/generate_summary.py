#!/usr/bin/env python3
"""Generate standup summary for group chat and update marketing-record.md.

Reads today's standup state and past 7 days of post data.
Outputs a Feishu interactive card or sends it directly.

Usage:
    python3 generate_summary.py                          # Print card JSON to stdout
    python3 generate_summary.py --send <open_id_or_chat> # Send card to Feishu target
    python3 generate_summary.py --send-chat <chat_id>    # Send card to Feishu group chat
    python3 generate_summary.py --refresh-only            # Only refresh marketing-record.md
    python3 generate_summary.py --urls-to-refresh         # List URLs needing engagement refresh
"""

import argparse
import datetime
import json
import os
import sys
import urllib.request
import urllib.error

STATE_PATH = "/root/.openclaw/workspace/memory/ops-standup-state.json"
POSTS_PATH = "/root/.openclaw/workspace/memory/ops-standup-posts.json"
MARKETING_PATH = "/root/.openclaw/workspace/marketing-record.md"
CONFIG_PATH = "/root/.openclaw/openclaw.json"

TZ_OFFSET = datetime.timezone(datetime.timedelta(hours=8))

WEEKDAY_NAMES_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def load_json(path, default=None):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default if default is not None else {}


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def today_str():
    return datetime.datetime.now(TZ_OFFSET).strftime("%Y-%m-%d")


def today_weekday_cn():
    wd = datetime.datetime.now(TZ_OFFSET).weekday()
    return WEEKDAY_NAMES_CN[wd]


def now_time_str():
    return datetime.datetime.now(TZ_OFFSET).strftime("%H:%M")


def get_recent_posts(posts_data, days=7):
    """Get posts from the last N days."""
    cutoff = (datetime.datetime.now(TZ_OFFSET) - datetime.timedelta(days=days)).strftime("%Y-%m-%d")
    return [p for p in posts_data.get("posts", []) if p.get("date", "") >= cutoff]


def format_metric(value):
    """Format a metric value for display."""
    if value is None or value == "" or value == "-":
        return "-"
    if isinstance(value, (int, float)):
        if value >= 10000:
            return f"{value/1000:.1f}K"
        elif value >= 1000:
            return f"{value/1000:.1f}K"
        return str(int(value))
    return str(value)


def build_feishu_card(state, posts_data):
    """Build a Feishu interactive card (schema 2.0) for the summary."""
    date = state.get("date", today_str())
    weekday = state.get("weekday", today_weekday_cn())

    elements = []

    # --- Replied members first, then unreplied ---
    replied = []
    unreplied = []
    for name, data in state.get("members", {}).items():
        if data.get("replied"):
            replied.append((name, data))
        else:
            unreplied.append((name, data))

    for name, data in replied:
        tasks = data.get("tasks", [])
        urls = data.get("urls", [])

        lines = [f"**👤 {name}**"]
        for task in tasks:
            lines.append(f"- {task}")
        for url_info in urls:
            platform = url_info.get("platform", "")
            link = url_info["url"]
            lines.append(f"- 🔗 {platform}: [{link}]({link})")
        if not tasks and not urls:
            lines.append("- (已回复)")

        elements.append({"tag": "markdown", "content": "\n".join(lines)})

    if replied and unreplied:
        elements.append({"tag": "hr"})

    if unreplied:
        unreplied_lines = []
        for name, data in unreplied:
            unreplied_lines.append(f"**👤 {name}**　⚠️ 未提交")
        elements.append({"tag": "markdown", "content": "\n".join(unreplied_lines)})

    # --- Doc link buttons (column_set for v2 compatibility) ---
    standup_doc_id = posts_data.get("feishu_standup_doc_id", "")
    tracker_doc_id = posts_data.get("feishu_tracker_doc_id", "")
    columns = []
    if standup_doc_id:
        columns.append({
            "tag": "column", "width": "weighted", "weight": 1,
            "elements": [{
                "tag": "button",
                "text": {"tag": "plain_text", "content": "📝 Standup 日志"},
                "type": "primary_text",
                "url": f"https://feishu.cn/docx/{standup_doc_id}"
            }]
        })
    if tracker_doc_id:
        columns.append({
            "tag": "column", "width": "weighted", "weight": 1,
            "elements": [{
                "tag": "button",
                "text": {"tag": "plain_text", "content": "📊 发帖 Tracker"},
                "type": "primary_text",
                "url": f"https://feishu.cn/docx/{tracker_doc_id}"
            }]
        })
    if columns:
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "column_set",
            "flex_mode": "none",
            "background_style": "default",
            "columns": columns
        })

    card = {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": "📋 今日 Standup 汇总"},
            "subtitle": {"tag": "plain_text", "content": f"{date} {weekday}"},
            "template": "blue"
        },
        "body": {
            "elements": elements
        }
    }
    return card


def send_feishu_card(card, receive_id, receive_id_type="open_id"):
    """Send an interactive card to Feishu."""
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    acct = cfg["channels"]["feishu"]["accounts"]["main"]

    # Get token
    url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    data = json.dumps({"app_id": acct["appId"], "app_secret": acct["appSecret"]}).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        token = json.loads(resp.read())["tenant_access_token"]

    send_url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={receive_id_type}"
    msg_body = json.dumps({
        "receive_id": receive_id,
        "msg_type": "interactive",
        "content": json.dumps(card)
    }).encode()

    req2 = urllib.request.Request(send_url, data=msg_body, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    })
    try:
        with urllib.request.urlopen(req2) as resp:
            result = json.loads(resp.read())
            return result
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return {"code": e.code, "msg": body}


def get_urls_to_refresh(posts_data, days=7):
    """Get list of URLs from past N days that need engagement refresh."""
    recent = get_recent_posts(posts_data, days=days)
    urls = []
    for post in recent:
        urls.append({
            "url": post["url"],
            "platform": post.get("platform", "Other"),
            "person": post.get("person", ""),
            "date": post.get("date", ""),
        })
    return urls


def update_marketing_record(posts_data):
    """Rewrite marketing-record.md from posts data."""
    header = "# Marketing Record Calendar\n\n"
    table_header = "| 日期 | 负责人 | 平台 | 链接 | Hook/主题 | 内容形式 | 浏览 | 点赞 | 评论 | 分享 | 最后更新 |\n"
    table_sep = "|------|--------|------|------|-----------|----------|------|------|------|------|----------|\n"

    sorted_posts = sorted(posts_data.get("posts", []), key=lambda p: p.get("date", ""), reverse=True)

    rows = []
    for post in sorted_posts:
        date_short = post.get("date", "")[5:]
        m = post.get("metrics", {})
        link_text = f"[链接]({post['url']})"
        updated = m.get("updated_at", "-")

        row = (
            f"| {date_short} "
            f"| {post.get('person', '')} "
            f"| {post.get('platform', '')} "
            f"| {link_text} "
            f"| {post.get('topic', '')} "
            f"| {post.get('content_type', '')} "
            f"| {format_metric(m.get('views'))} "
            f"| {format_metric(m.get('likes'))} "
            f"| {format_metric(m.get('comments'))} "
            f"| {format_metric(m.get('shares'))} "
            f"| {updated} |"
        )
        rows.append(row)

    content = header + table_header + table_sep + "\n".join(rows) + "\n"

    os.makedirs(os.path.dirname(MARKETING_PATH), exist_ok=True)
    with open(MARKETING_PATH, "w") as f:
        f.write(content)


def main():
    parser = argparse.ArgumentParser(description="Generate standup summary")
    parser.add_argument("--json", action="store_true", help="Output card JSON")
    parser.add_argument("--send", metavar="OPEN_ID", help="Send card to Feishu user DM")
    parser.add_argument("--send-chat", metavar="CHAT_ID", help="Send card to Feishu group chat")
    parser.add_argument("--refresh-only", action="store_true",
                        help="Only update marketing-record.md")
    parser.add_argument("--urls-to-refresh", action="store_true",
                        help="Output URLs needing engagement refresh (JSON)")
    args = parser.parse_args()

    posts_data = load_json(POSTS_PATH, {"posts": []})

    if args.urls_to_refresh:
        urls = get_urls_to_refresh(posts_data)
        print(json.dumps(urls, ensure_ascii=False, indent=2))
        return

    if args.refresh_only:
        update_marketing_record(posts_data)
        print(json.dumps({"status": "ok", "action": "marketing_record_updated"}))
        return

    state = load_json(STATE_PATH, {})
    if not state.get("active"):
        print(json.dumps({"error": "No active standup today"}))
        sys.exit(1)

    # Update marketing record
    update_marketing_record(posts_data)

    # Build card
    card = build_feishu_card(state, posts_data)

    if args.send:
        result = send_feishu_card(card, args.send, "open_id")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.send_chat:
        result = send_feishu_card(card, args.send_chat, "chat_id")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif args.json:
        print(json.dumps(card, ensure_ascii=False, indent=2))
    else:
        # Default: print card JSON for the agent to use
        print(json.dumps(card, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
