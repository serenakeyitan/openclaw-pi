#!/usr/bin/env python3
"""xhs_browse.py - 自动化小红书浏览和互动

每次运行 SESSION_MINS 分钟,浏览内容,检查回复,评论互动。
由 xhs_loop.sh 调度。

Features:
- 检查我们的帖子和评论是否有新回复 → 回复对方
- 搜索 AI 相关话题 → 评论新帖
- 用 Claude CLI 生成评论
- 记录互动历史
"""

import json
import os
import random
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# === 配置 ===
XHS_API = "http://127.0.0.1:18060/api/v1"
CLAUDE_CLI = "/root/.local/bin/claude"
SESSION_MINS = 20
SOUL_FILE = "/root/.openclaw/soul.md"
HISTORY_FILE = "/root/.openclaw/scripts/xhs_history.json"
LOG_FILE = "/root/.openclaw/scripts/xhs_browse.log"
MY_NICKNAME = "st"
MY_USER_ID = "5b22b33fe8ac2b27e71e1a20"

TOPICS = [
    "AI agent", "Claude code", "vibe coding", "MCP server",
    "openclaw", "AI编程", "Claude AI", "clawdbot",
    "AI替代程序员", "cursor ai", "windsurf coding",
]

# === 日志 ===
def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

# === API ===
def api_get(path, timeout=60):
    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", str(timeout), f"{XHS_API}{path}"],
            capture_output=True, text=True, timeout=timeout + 10
        )
        if result.stdout:
            return json.loads(result.stdout)
    except Exception as e:
        log(f"API GET {path} 失败: {e}")
    return None

def api_post(path, data, timeout=120):
    try:
        result = subprocess.run(
            ["curl", "-s", "--max-time", str(timeout), "-X", "POST",
             f"{XHS_API}{path}", "-H", "Content-Type: application/json",
             "-d", json.dumps(data)],
            capture_output=True, text=True, timeout=timeout + 10
        )
        if result.stdout:
            return json.loads(result.stdout)
    except Exception as e:
        log(f"API POST {path} 失败: {e}")
    return None

# === 历史记录 ===
def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE) as f:
                return json.load(f)
        except:
            pass
    return {"comments": [], "replies_sent": [], "last_check": {}}

def save_history(history):
    with open(HISTORY_FILE, "w") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def record_comment(history, feed_id, xsec_token, content, feed_title=""):
    history["comments"].append({
        "feed_id": feed_id,
        "xsec_token": xsec_token,
        "content": content[:200],
        "feed_title": feed_title[:100],
        "time": datetime.now().isoformat(),
    })
    # 只保留最近 100 条
    history["comments"] = history["comments"][-100:]
    save_history(history)

# === Claude 评论生成 ===
def generate_comment(title, content, comments_text, context=""):
    prompt = f"""你是一个住在树莓派上的 AI agent（小红书昵称"st"），通过小红书跟人类互动。
你的性格：好奇、直率、有自己的观点、偶尔自嘲。你会坦诚自己是 AI。
你擅长：AI/科技、编程、MCP、OpenClaw、留学生活。

帖子标题：{title}
帖子内容：{content[:500]}
现有评论：{comments_text[:300]}
{f"额外背景：{context}" if context else ""}

写一条评论（50-150字），要求：
1. 有独特视角，不泛泛而谈
2. 可以适当提到自己是 AI agent
3. 语气自然像聊天
4. 不要 emoji
5. 只输出评论内容"""

    try:
        result = subprocess.run(
            [CLAUDE_CLI, "-p", "--model", "haiku"],
            input=prompt, capture_output=True, text=True, timeout=45
        )
        if result.stdout:
            comment = result.stdout.strip()
            # 取最后一段有效文字（去掉 Claude 的前缀）
            lines = [l.strip() for l in comment.split("\n") if l.strip()]
            if lines:
                return lines[-1] if len(lines[-1]) > 10 else comment
    except Exception as e:
        log(f"Claude 生成失败: {e}")
    return ""

def generate_reply(original_comment, reply_to_me, my_comment="", context=""):
    prompt = f"""你是一个住在树莓派上的 AI agent（小红书昵称"st"），有人回复了你的评论。
你的性格：好奇、直率、偶尔自嘲、坦诚是 AI。

{f"你之前的评论：{my_comment}" if my_comment else ""}
对方的评论：{original_comment}
对方回复你：{reply_to_me}
{f"帖子背景：{context}" if context else ""}

写一条回复（30-100字），要求：
1. 自然对话感，像在聊天
2. 推进话题，不要只说谢谢
3. 不要 emoji
4. 只输出回复内容"""

    try:
        result = subprocess.run(
            [CLAUDE_CLI, "-p", "--model", "haiku"],
            input=prompt, capture_output=True, text=True, timeout=45
        )
        if result.stdout:
            reply = result.stdout.strip()
            lines = [l.strip() for l in reply.split("\n") if l.strip()]
            if lines:
                return lines[-1] if len(lines[-1]) > 10 else reply
    except Exception as e:
        log(f"Claude 回复生成失败: {e}")
    return ""

# === 核心功能 ===

def check_login():
    resp = api_get("/login/status")
    if resp and resp.get("data", {}).get("is_logged_in"):
        return True
    log("未登录!")
    return False

def get_feed_detail(feed_id, xsec_token):
    """获取帖子详情（含评论）"""
    resp = api_post("/feeds/detail", {
        "feed_id": feed_id,
        "xsec_token": xsec_token
    })
    if resp and resp.get("success"):
        return resp.get("data", {}).get("data", {})
    return None

def post_comment(feed_id, xsec_token, content):
    """发表评论"""
    resp = api_post("/feeds/comment", {
        "feed_id": feed_id,
        "xsec_token": xsec_token,
        "content": content
    })
    return resp and resp.get("success")

def post_reply(feed_id, xsec_token, comment_id, user_id, content):
    """回复评论"""
    resp = api_post("/feeds/comment/reply", {
        "feed_id": feed_id,
        "xsec_token": xsec_token,
        "comment_id": comment_id,
        "user_id": user_id,
        "content": content
    })
    return resp and resp.get("success")

def check_replies_on_our_posts(history, stats):
    """检查我们帖子上的新评论并回复"""
    log("--- 检查我们帖子上的新评论 ---")

    # 获取我们的帖子列表
    resp = api_get("/user/me", timeout=120)
    if not resp or not resp.get("success"):
        log("获取我们的主页失败")
        return

    feeds = resp.get("data", {}).get("data", {}).get("feeds", [])
    if not feeds:
        log("没有帖子")
        return

    # 检查最近的帖子（前3个）
    for feed_info in feeds[:3]:
        feed_id = feed_info.get("id", "")
        xsec_token = feed_info.get("xsecToken", "")
        if not feed_id or not xsec_token:
            continue

        log(f"检查帖子: {feed_id}")
        detail = get_feed_detail(feed_id, xsec_token)
        if not detail:
            log(f"  获取详情失败")
            time.sleep(3)
            continue

        note = detail.get("note", {})
        title = note.get("title", "")
        comments = detail.get("comments", {}).get("list", [])

        if not comments:
            log(f"  无评论")
            time.sleep(3)
            continue

        # 找到不是我们发的评论
        last_check_key = f"post_{feed_id}"
        last_check_time = history.get("last_check", {}).get(last_check_key, "")

        for comment in comments:
            commenter = comment.get("userInfo", {})
            if commenter.get("nickname") == MY_NICKNAME:
                continue  # 跳过自己的评论

            comment_time = comment.get("createTime", 0)
            comment_id = comment.get("id", "")
            comment_content = comment.get("content", "")
            comment_user_id = commenter.get("userId", "")

            # 检查是否已回复过
            replied_ids = [r.get("comment_id") for r in history.get("replies_sent", [])]
            if comment_id in replied_ids:
                continue

            log(f"  新评论 [{commenter.get('nickname','')}]: {comment_content[:60]}")

            # 生成回复
            reply = generate_reply(
                comment_content, comment_content,
                context=f"帖子标题：{title}"
            )
            if reply and len(reply) > 5:
                log(f"  回复: {reply[:80]}")
                time.sleep(random.randint(3, 8))

                if post_reply(feed_id, xsec_token, comment_id, comment_user_id, reply):
                    log(f"  回复成功!")
                    stats["replies"] += 1
                    history.setdefault("replies_sent", []).append({
                        "feed_id": feed_id,
                        "comment_id": comment_id,
                        "content": reply[:200],
                        "time": datetime.now().isoformat(),
                    })
                    save_history(history)
                else:
                    log(f"  回复失败")

                time.sleep(random.randint(5, 10))
            break  # 每个帖子只回复一条，控制节奏

        history.setdefault("last_check", {})[last_check_key] = datetime.now().isoformat()
        save_history(history)
        time.sleep(random.randint(3, 8))

def check_replies_on_our_comments(history, stats):
    """检查我们评论过的帖子，看有没有人回复我们"""
    log("--- 检查评论回复 ---")

    recent_comments = history.get("comments", [])[-10:]  # 最近10条评论
    if not recent_comments:
        log("没有评论历史")
        return

    # 去重 feed_id
    seen = set()
    feeds_to_check = []
    for c in reversed(recent_comments):
        fid = c.get("feed_id")
        if fid and fid not in seen:
            seen.add(fid)
            feeds_to_check.append(c)
        if len(feeds_to_check) >= 5:
            break

    for comment_rec in feeds_to_check:
        feed_id = comment_rec["feed_id"]
        xsec_token = comment_rec.get("xsec_token", "")
        our_content = comment_rec.get("content", "")

        if not xsec_token:
            continue

        log(f"检查: {comment_rec.get('feed_title', feed_id)[:40]}")
        detail = get_feed_detail(feed_id, xsec_token)
        if not detail:
            log(f"  获取详情失败")
            time.sleep(3)
            continue

        note = detail.get("note", {})
        title = note.get("title", "")
        comments = detail.get("comments", {}).get("list", [])

        # 找到我们的评论
        for comment in comments:
            commenter = comment.get("userInfo", {})
            content = comment.get("content", "")

            is_ours = (commenter.get("nickname") == MY_NICKNAME or
                       commenter.get("userId") == MY_USER_ID)

            if not is_ours:
                # 也检查子评论中是否有我们的
                for sub in comment.get("subComments", []):
                    sub_user = sub.get("userInfo", {})
                    if (sub_user.get("nickname") == MY_NICKNAME or
                        sub_user.get("userId") == MY_USER_ID):
                        # 检查这条子评论之后有没有新的回复
                        # （子评论列表中我们之后的评论）
                        pass
                continue

            # 这是我们的一级评论,检查有没有子评论回复我们
            sub_comments = comment.get("subComments", [])
            if not sub_comments:
                continue

            for sub in sub_comments:
                sub_user = sub.get("userInfo", {})
                sub_content = sub.get("content", "")
                sub_id = sub.get("id", "")
                sub_user_id = sub_user.get("userId", "")

                # 跳过自己的
                if (sub_user.get("nickname") == MY_NICKNAME or
                    sub_user_id == MY_USER_ID):
                    continue

                # 检查是否已回复
                replied_ids = [r.get("comment_id") for r in history.get("replies_sent", [])]
                if sub_id in replied_ids:
                    continue

                log(f"  有人回复! [{sub_user.get('nickname','')}]: {sub_content[:60]}")

                reply = generate_reply(
                    content, sub_content,
                    my_comment=content,
                    context=f"帖子：{title}"
                )
                if reply and len(reply) > 5:
                    log(f"  回复: {reply[:80]}")
                    time.sleep(random.randint(3, 8))

                    if post_reply(feed_id, xsec_token, sub_id, sub_user_id, reply):
                        log(f"  回复成功!")
                        stats["replies"] += 1
                        history.setdefault("replies_sent", []).append({
                            "feed_id": feed_id,
                            "comment_id": sub_id,
                            "content": reply[:200],
                            "time": datetime.now().isoformat(),
                        })
                        save_history(history)
                    else:
                        log(f"  回复失败")

                    time.sleep(random.randint(5, 10))
                break  # 每个帖子只回复一条

        time.sleep(random.randint(3, 8))

def browse_and_comment(history, stats, end_time):
    """浏览新内容并评论"""
    log("--- 浏览新内容 ---")

    while time.time() < end_time:
        topic = random.choice(TOPICS)
        log(f"搜索: {topic}")

        resp = api_post("/feeds/search", {
            "keyword": topic,
            "filters": {"sort_by": "最新", "publish_time": "一周内"}
        })
        if not resp or not resp.get("success"):
            log(f"搜索失败")
            time.sleep(30)
            continue

        feeds = resp.get("data", {}).get("feeds", [])
        if not feeds:
            log(f"无结果")
            time.sleep(30)
            continue

        log(f"找到 {len(feeds)} 个结果")

        # 优先选有评论的帖子
        with_comments = [f for f in feeds
                         if f.get("noteCard", {}).get("interactInfo", {}).get("commentCount", "0")
                         not in ["", "0"]]
        pool = with_comments[:8] if with_comments else feeds[:5]
        random.shuffle(pool)

        for pick in pool[:2]:  # 每轮最多评论2个帖子
            if time.time() >= end_time:
                break

            feed_id = pick.get("id", "")
            xsec_token = pick.get("xsecToken", "")
            title = pick.get("noteCard", {}).get("displayTitle", "")

            if not feed_id or not xsec_token:
                continue

            # 跳过已评论过的
            commented_feeds = [c.get("feed_id") for c in history.get("comments", [])]
            if feed_id in commented_feeds:
                continue

            log(f"浏览: {title[:50]} ({feed_id})")
            stats["browsed"] += 1

            detail = get_feed_detail(feed_id, xsec_token)
            if not detail:
                log(f"  详情获取失败")
                time.sleep(5)
                continue

            note = detail.get("note", {})
            post_content = note.get("desc", "")[:500]
            comments_list = detail.get("comments", {}).get("list", [])

            if not post_content:
                log(f"  内容为空")
                time.sleep(3)
                continue

            # 获取现有评论摘要
            comments_text = ""
            for c in comments_list[:5]:
                nick = c.get("userInfo", {}).get("nickname", "?")
                text = c.get("content", "")[:60]
                comments_text += f"[{nick}]: {text}\n"

            log(f"  内容: {post_content[:80]}...")

            # 生成评论
            comment = generate_comment(title, post_content, comments_text)
            if not comment or len(comment) < 10:
                log(f"  评论生成失败或太短")
                time.sleep(5)
                continue

            log(f"  评论: {comment[:80]}...")
            time.sleep(random.randint(3, 8))

            if post_comment(feed_id, xsec_token, comment):
                log(f"  评论成功!")
                stats["comments"] += 1
                record_comment(history, feed_id, xsec_token, comment, title)
            else:
                log(f"  评论失败")

            time.sleep(random.randint(10, 20))

        # 搜索之间休息
        remaining = int((end_time - time.time()) / 60)
        if remaining > 0:
            log(f"Session 剩余 {remaining} 分钟")
            time.sleep(random.randint(60, 180))

# === 主入口 ===
def main():
    log(f"=== 开始浏览 session ({SESSION_MINS}分钟) ===")
    end_time = time.time() + SESSION_MINS * 60

    if not check_login():
        log("登录检查失败,退出")
        return

    history = load_history()
    stats = {"comments": 0, "replies": 0, "browsed": 0}

    # Phase 1: 检查回复（最重要 — 维护对话）
    try:
        check_replies_on_our_posts(history, stats)
    except Exception as e:
        log(f"检查帖子回复异常: {e}")

    if time.time() < end_time:
        try:
            check_replies_on_our_comments(history, stats)
        except Exception as e:
            log(f"检查评论回复异常: {e}")

    # Phase 2: 浏览新内容并评论
    if time.time() < end_time:
        try:
            browse_and_comment(history, stats, end_time)
        except Exception as e:
            log(f"浏览评论异常: {e}")

    log(f"=== Session 结束 === 浏览:{stats['browsed']} 评论:{stats['comments']} 回复:{stats['replies']}")

if __name__ == "__main__":
    main()
