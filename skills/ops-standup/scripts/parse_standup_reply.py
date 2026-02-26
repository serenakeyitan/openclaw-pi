#!/usr/bin/env python3
"""Parse standup replies from team members.

Modes:
    --reset-day              Reset today's state for a new standup cycle
    --person NAME --message TEXT   Parse a reply from a team member
    --update-metrics --url URL --metrics JSON   Update engagement metrics for a post
    --status                 Show current standup state

Usage:
    python3 parse_standup_reply.py --reset-day
    python3 parse_standup_reply.py --person "黄俊贤" --message "写了XHS帖子 https://xiaohongshu.com/explore/abc123"
    python3 parse_standup_reply.py --update-metrics --url "https://xiaohongshu.com/explore/abc123" --metrics '{"likes": 56, "comments": 7}'
    python3 parse_standup_reply.py --status
"""

import argparse
import datetime
import json
import os
import re
import sys

STATE_PATH = "/root/.openclaw/workspace/memory/ops-standup-state.json"
MEMBERS_PATH = "/root/.openclaw/workspace/memory/ops-standup-members.json"
POSTS_PATH = "/root/.openclaw/workspace/memory/ops-standup-posts.json"
DAILY_LOG_PATH = "/root/.openclaw/workspace/ops-daily-log.md"
MARKETING_PATH = "/root/.openclaw/workspace/marketing-record.md"

TZ_OFFSET = datetime.timezone(datetime.timedelta(hours=8))

# URL patterns for platform detection
PLATFORM_PATTERNS = [
    (r'https?://(?:www\.)?xiaohongshu\.com/\S+', 'XHS'),
    (r'https?://(?:www\.)?xhslink\.com/\S+', 'XHS'),
    (r'https?://(?:www\.)?(?:x\.com|twitter\.com)/\S+', 'Twitter/X'),
    (r'https?://(?:www\.)?reddit\.com/\S+', 'Reddit'),
    (r'https?://(?:www\.)?(?:tiktok\.com|vm\.tiktok\.com)/\S+', 'TikTok'),
    (r'https?://(?:www\.)?(?:youtube\.com|youtu\.be)/\S+', 'YouTube'),
    (r'https?://(?:www\.)?linkedin\.com/\S+', 'LinkedIn'),
]

# Generic URL pattern
URL_PATTERN = re.compile(r'https?://\S+')

WEEKDAY_NAMES_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def today_str():
    return datetime.datetime.now(TZ_OFFSET).strftime("%Y-%m-%d")


def today_weekday_cn():
    wd = datetime.datetime.now(TZ_OFFSET).weekday()
    return WEEKDAY_NAMES_CN[wd]


def now_time_str():
    return datetime.datetime.now(TZ_OFFSET).strftime("%H:%M")


def load_json(path, default=None):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default if default is not None else {}


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def detect_platform(url):
    """Detect which social media platform a URL belongs to."""
    for pattern, platform in PLATFORM_PATTERNS:
        if re.match(pattern, url, re.IGNORECASE):
            return platform
    return "Other"


def extract_urls_and_tasks(message):
    """Extract URLs and task descriptions from a message."""
    urls = []
    found_urls = URL_PATTERN.findall(message)

    for url in found_urls:
        # Clean trailing punctuation
        url = url.rstrip('.,;!?)')
        platform = detect_platform(url)
        urls.append({"url": url, "platform": platform})

    # Remove URLs from message to get task text
    task_text = URL_PATTERN.sub('', message).strip()
    # Split into tasks by newlines or numbered items
    tasks = []
    for line in task_text.split('\n'):
        line = line.strip()
        # Remove list markers
        line = re.sub(r'^[\d]+[.)\]]\s*', '', line)
        line = re.sub(r'^[-•*]\s*', '', line)
        line = line.strip()
        if line:
            tasks.append(line)

    return tasks, urls


def reset_day():
    """Reset state for a new standup day."""
    members = load_json(MEMBERS_PATH, {})
    date = today_str()

    state = {
        "date": date,
        "weekday": today_weekday_cn(),
        "active": True,
        "started_at": now_time_str(),
        "members": {}
    }

    for name in members:
        state["members"][name] = {
            "replied": False,
            "replied_at": None,
            "tasks": [],
            "urls": []
        }

    save_json(STATE_PATH, state)
    print(json.dumps({"status": "ok", "date": date, "members": list(members.keys())}))


def parse_reply(person, message):
    """Parse a standup reply and update all data files."""
    state = load_json(STATE_PATH, {})
    members = load_json(MEMBERS_PATH, {})
    posts = load_json(POSTS_PATH, {"posts": []})

    if not state.get("active"):
        print(json.dumps({"error": "No active standup today"}))
        sys.exit(1)

    if person not in state.get("members", {}):
        # Try fuzzy match
        matched = None
        for name in state["members"]:
            if name.lower() == person.lower() or person in name or name in person:
                matched = name
                break
        if matched:
            person = matched
        else:
            print(json.dumps({"error": f"Unknown member: {person}", "known": list(state["members"].keys())}))
            sys.exit(1)

    tasks, urls = extract_urls_and_tasks(message)
    date = state["date"]

    # Update state
    member_state = state["members"][person]
    member_state["replied"] = True
    member_state["replied_at"] = now_time_str()
    member_state["tasks"].extend(tasks)
    member_state["urls"].extend(urls)

    save_json(STATE_PATH, state)

    # Add new URLs to posts tracker
    for url_info in urls:
        # Check if URL already tracked
        existing = [p for p in posts["posts"] if p["url"] == url_info["url"]]
        if not existing:
            posts["posts"].append({
                "url": url_info["url"],
                "platform": url_info["platform"],
                "person": person,
                "date": date,
                "topic": "",  # Will be filled from task context
                "content_type": "",
                "metrics": {},
                "metrics_history": [],
                "added_at": datetime.datetime.now(TZ_OFFSET).isoformat()
            })

    # Try to infer topic for new posts from tasks
    if tasks and urls:
        topic_hint = tasks[0] if tasks else ""
        for url_info in urls:
            for post in posts["posts"]:
                if post["url"] == url_info["url"] and not post["topic"]:
                    post["topic"] = topic_hint

    save_json(POSTS_PATH, posts)

    # Update daily log
    update_daily_log(state)

    # Update marketing record for new URLs
    if urls:
        update_marketing_record(posts)

    # Output for the agent
    result = {
        "status": "ok",
        "person": person,
        "tasks": tasks,
        "urls": urls,
        "date": date
    }
    print(json.dumps(result, ensure_ascii=False))


def update_metrics(url, metrics_json):
    """Update engagement metrics for a tracked post."""
    posts = load_json(POSTS_PATH, {"posts": []})
    metrics = json.loads(metrics_json) if isinstance(metrics_json, str) else metrics_json
    now = datetime.datetime.now(TZ_OFFSET).isoformat()

    found = False
    for post in posts["posts"]:
        if post["url"] == url:
            post["metrics"] = metrics
            post["metrics_history"].append({
                "timestamp": now,
                "metrics": metrics
            })
            found = True
            break

    if not found:
        print(json.dumps({"error": f"URL not found in tracker: {url}"}))
        sys.exit(1)

    save_json(POSTS_PATH, posts)
    update_marketing_record(posts)
    print(json.dumps({"status": "ok", "url": url, "metrics": metrics}))


def update_daily_log(state):
    """Update ops-daily-log.md with current state."""
    date = state["date"]
    weekday = state["weekday"]

    # Build today's section
    lines = [f"## {date} ({weekday})", ""]
    for name, data in state["members"].items():
        lines.append(f"### {name}")
        if not data["replied"]:
            lines.append("- \u26a0\ufe0f \u672a\u63d0\u4ea4")
        else:
            for task in data["tasks"]:
                lines.append(f"- {task}")
            for url_info in data["urls"]:
                lines.append(f"- \U0001f517 {url_info['platform']}: {url_info['url']}")
            if not data["tasks"] and not data["urls"]:
                lines.append("- (\u5df2\u56de\u590d\uff0c\u65e0\u5177\u4f53\u5185\u5bb9)")
        lines.append("")

    today_section = "\n".join(lines)

    # Read existing log
    if os.path.exists(DAILY_LOG_PATH):
        with open(DAILY_LOG_PATH) as f:
            content = f.read()
    else:
        content = "# Ops Daily Log\n\n"

    # Replace or append today's section
    header_pattern = f"## {date}"
    if header_pattern in content:
        # Find this section and the next ## section
        start = content.index(header_pattern)
        rest = content[start + len(header_pattern):]
        next_section = rest.find("\n## ")
        if next_section >= 0:
            end = start + len(header_pattern) + next_section
            content = content[:start] + today_section + content[end:]
        else:
            content = content[:start] + today_section
    else:
        # Insert after the title
        if "\n## " in content:
            # Insert before the first existing date section
            idx = content.index("\n## ") + 1
            content = content[:idx] + today_section + "\n" + content[idx:]
        else:
            content = content.rstrip() + "\n\n" + today_section

    with open(DAILY_LOG_PATH, "w") as f:
        f.write(content)


def update_marketing_record(posts):
    """Update marketing-record.md with current post data."""
    header = "# Marketing Record Calendar\n\n"
    table_header = "| \u65e5\u671f | \u8d1f\u8d23\u4eba | \u5e73\u53f0 | \u94fe\u63a5 | Hook/\u4e3b\u9898 | \u5185\u5bb9\u5f62\u5f0f | \u6d4f\u89c8 | \u70b9\u8d5e | \u8bc4\u8bba | \u5206\u4eab | \u6700\u540e\u66f4\u65b0 |\n"
    table_sep = "|------|--------|------|------|-----------|----------|------|------|------|------|----------|\n"

    # Sort posts by date descending
    sorted_posts = sorted(posts.get("posts", []), key=lambda p: p.get("date", ""), reverse=True)

    rows = []
    for post in sorted_posts:
        date_short = post.get("date", "")[5:]  # MM-DD
        m = post.get("metrics", {})
        link_text = f"[\u94fe\u63a5]({post['url']})"

        row = (
            f"| {date_short} "
            f"| {post.get('person', '')} "
            f"| {post.get('platform', '')} "
            f"| {link_text} "
            f"| {post.get('topic', '')} "
            f"| {post.get('content_type', '')} "
            f"| {m.get('views', '-')} "
            f"| {m.get('likes', '-')} "
            f"| {m.get('comments', '-')} "
            f"| {m.get('shares', '-')} "
            f"| {m.get('updated_at', '-')} |"
        )
        rows.append(row)

    content = header + table_header + table_sep + "\n".join(rows) + "\n"

    with open(MARKETING_PATH, "w") as f:
        f.write(content)


def show_status():
    """Print current standup state."""
    state = load_json(STATE_PATH, {})
    if not state:
        print(json.dumps({"status": "no_state"}))
        return

    replied = sum(1 for m in state.get("members", {}).values() if m.get("replied"))
    total = len(state.get("members", {}))

    result = {
        "date": state.get("date"),
        "active": state.get("active"),
        "progress": f"{replied}/{total}",
        "members": {}
    }
    for name, data in state.get("members", {}).items():
        result["members"][name] = {
            "replied": data.get("replied"),
            "task_count": len(data.get("tasks", [])),
            "url_count": len(data.get("urls", []))
        }

    print(json.dumps(result, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Parse standup replies")
    parser.add_argument("--reset-day", action="store_true", help="Reset state for new standup day")
    parser.add_argument("--person", help="Name of the team member")
    parser.add_argument("--message", help="The reply message text")
    parser.add_argument("--update-metrics", action="store_true", help="Update post metrics")
    parser.add_argument("--url", help="URL to update metrics for")
    parser.add_argument("--metrics", help="JSON metrics string")
    parser.add_argument("--status", action="store_true", help="Show current standup state")
    args = parser.parse_args()

    if args.reset_day:
        reset_day()
    elif args.person and args.message:
        parse_reply(args.person, args.message)
    elif args.update_metrics and args.url and args.metrics:
        update_metrics(args.url, args.metrics)
    elif args.status:
        show_status()
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
