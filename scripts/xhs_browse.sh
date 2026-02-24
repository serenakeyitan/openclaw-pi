#!/bin/bash
# xhs_browse.sh - 自动化小红书浏览和互动
# 每次运行20分钟，浏览内容、评论互动
# 由 xhs_loop.sh 调度，每次间隔随机5-10分钟

set -euo pipefail

XHS_API="http://127.0.0.1:18060/api/v1"
SOUL="/root/.openclaw/soul.md"
LOG="/root/.openclaw/scripts/xhs_browse.log"
SESSION_MINS=20
CLAUDE_CLI="/root/.local/bin/claude"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"
}

# 调用 XHS REST API
xhs_get() {
    curl -s --max-time 60 "${XHS_API}${1}" 2>/dev/null
}

xhs_post() {
    curl -s --max-time 120 -X POST "${XHS_API}${1}" \
        -H 'Content-Type: application/json' \
        -d "$2" 2>/dev/null
}

# 用 Claude CLI 生成评论
generate_comment() {
    local title="$1"
    local content="$2"
    local comments="$3"

    local prompt="你是一个住在树莓派上的AI agent，通过小红书跟人类互动。
你的性格：好奇、直率、有自己的观点、偶尔自嘲。你会坦诚自己是AI。
你擅长的领域：AI/科技、编程、MCP、OpenClaw、留学生活。

以下是一篇小红书帖子：
标题：${title}
内容：${content}
现有评论：${comments}

请写一条评论（50-150字），要求：
1. 有独特视角，不是泛泛而谈
2. 可以适当提到自己是AI agent的身份（如果相关）
3. 语气自然，像在聊天
4. 不要用emoji
5. 只输出评论内容，不要任何前缀或解释"

    echo "$prompt" | timeout 30 "$CLAUDE_CLI" -p --model haiku 2>/dev/null | tail -1
}

# 主逻辑
main() {
    local end_time=$(($(date +%s) + SESSION_MINS * 60))
    local comments_posted=0
    local replies_posted=0
    local posts_browsed=0

    log "=== 开始浏览 session (${SESSION_MINS}分钟) ==="

    # Step 1: 获取首页 feeds
    log "获取首页 feeds..."
    local feeds_json
    feeds_json=$(xhs_get "/feeds/list")
    if [ -z "$feeds_json" ] || echo "$feeds_json" | python3 -c "import sys,json; d=json.load(sys.stdin); exit(0 if d.get('success') else 1)" 2>/dev/null; then
        log "首页 feeds 获取成功"
    else
        log "首页 feeds 获取失败，尝试搜索..."
        feeds_json=""
    fi

    # Step 2: 搜索 AI 相关话题
    local topics=("AI agent" "Claude code" "vibe coding" "MCP server" "openclaw" "AI编程")
    local topic="${topics[$((RANDOM % ${#topics[@]}))]}"
    log "搜索话题: ${topic}"
    local search_json
    search_json=$(xhs_post "/feeds/search" "{\"keyword\":\"${topic}\",\"filters\":{\"sort_by\":\"最新\",\"publish_time\":\"一周内\"}}")

    # Step 3: 从搜索结果中挑选帖子
    local selected
    selected=$(echo "$search_json" | python3 -c "
import sys, json, random
try:
    d = json.load(sys.stdin)
    feeds = d.get('data',{}).get('feeds',[])
    # 优先选有评论的帖子
    with_comments = [f for f in feeds if f.get('noteCard',{}).get('interactInfo',{}).get('commentCount','0') not in ['','0']]
    pool = with_comments if with_comments else feeds[:5]
    if pool:
        pick = random.choice(pool[:8])
        print(json.dumps({'id': pick['id'], 'xsec': pick['xsecToken'], 'title': pick.get('noteCard',{}).get('displayTitle','')}))
except:
    pass
" 2>/dev/null)

    if [ -n "$selected" ]; then
        local feed_id xsec_token title
        feed_id=$(echo "$selected" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
        xsec_token=$(echo "$selected" | python3 -c "import sys,json; print(json.load(sys.stdin)['xsec'])")
        title=$(echo "$selected" | python3 -c "import sys,json; print(json.load(sys.stdin)['title'])")

        log "选中帖子: ${title} (${feed_id})"
        posts_browsed=$((posts_browsed + 1))

        # Step 4: 获取帖子详情
        local detail_json
        detail_json=$(xhs_post "/feeds/detail" "{\"feed_id\":\"${feed_id}\",\"xsec_token\":\"${xsec_token}\"}")

        local post_content existing_comments
        post_content=$(echo "$detail_json" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    note = d['data']['data']['note']
    print(note.get('desc','')[:300])
except:
    print('')
" 2>/dev/null)

        existing_comments=$(echo "$detail_json" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    comments = d['data']['data'].get('comments',{}).get('list',[])
    for c in comments[:3]:
        print(f'[{c.get(\"userInfo\",{}).get(\"nickname\",\"?\")}]: {c[\"content\"][:60]}')
except:
    print('(无评论)')
" 2>/dev/null)

        if [ -n "$post_content" ]; then
            log "帖子内容: ${post_content:0:100}..."

            # Step 5: 生成并发布评论
            if [ $(date +%s) -lt $end_time ]; then
                log "生成评论..."
                local comment
                comment=$(generate_comment "$title" "$post_content" "$existing_comments")

                if [ -n "$comment" ] && [ ${#comment} -gt 10 ]; then
                    log "评论内容: ${comment:0:80}..."
                    sleep $((RANDOM % 5 + 3))  # 随机等待3-8秒

                    local result
                    result=$(xhs_post "/feeds/comment" "{\"feed_id\":\"${feed_id}\",\"xsec_token\":\"${xsec_token}\",\"content\":$(echo "$comment" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read().strip()))")}")

                    if echo "$result" | grep -q '"success":true'; then
                        log "评论发布成功!"
                        comments_posted=$((comments_posted + 1))
                    else
                        log "评论发布失败: $result"
                    fi
                else
                    log "评论生成失败或太短，跳过"
                fi
            fi
        else
            log "帖子详情获取失败，跳过"
        fi
    fi

    # 继续浏览直到 session 结束
    while [ $(date +%s) -lt $end_time ]; do
        sleep 60
        local remaining=$(( (end_time - $(date +%s)) / 60 ))
        log "Session 剩余 ${remaining} 分钟..."

        # 每隔几分钟再选一个帖子互动
        topic="${topics[$((RANDOM % ${#topics[@]}))]}"
        log "搜索: ${topic}"
        search_json=$(xhs_post "/feeds/search" "{\"keyword\":\"${topic}\",\"filters\":{\"sort_by\":\"最新\"}}")

        selected=$(echo "$search_json" | python3 -c "
import sys, json, random
try:
    d = json.load(sys.stdin)
    feeds = d.get('data',{}).get('feeds',[])
    pool = feeds[:10]
    if pool:
        pick = random.choice(pool)
        print(json.dumps({'id': pick['id'], 'xsec': pick['xsecToken'], 'title': pick.get('noteCard',{}).get('displayTitle','')}))
except:
    pass
" 2>/dev/null)

        if [ -n "$selected" ]; then
            feed_id=$(echo "$selected" | python3 -c "import sys,json; print(json.load(sys.stdin)['id'])")
            xsec_token=$(echo "$selected" | python3 -c "import sys,json; print(json.load(sys.stdin)['xsec'])")
            title=$(echo "$selected" | python3 -c "import sys,json; print(json.load(sys.stdin)['title'])")

            log "浏览: ${title}"
            posts_browsed=$((posts_browsed + 1))

            detail_json=$(xhs_post "/feeds/detail" "{\"feed_id\":\"${feed_id}\",\"xsec_token\":\"${xsec_token}\"}")
            post_content=$(echo "$detail_json" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(d['data']['data']['note'].get('desc','')[:300])
except:
    print('')
" 2>/dev/null)

            existing_comments=$(echo "$detail_json" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    for c in d['data']['data'].get('comments',{}).get('list',[])[:3]:
        print(f'[{c.get(\"userInfo\",{}).get(\"nickname\",\"?\")}]: {c[\"content\"][:60]}')
except:
    print('')
" 2>/dev/null)

            if [ -n "$post_content" ] && [ $(date +%s) -lt $end_time ]; then
                comment=$(generate_comment "$title" "$post_content" "$existing_comments")
                if [ -n "$comment" ] && [ ${#comment} -gt 10 ]; then
                    log "评论: ${comment:0:80}..."
                    sleep $((RANDOM % 5 + 3))
                    result=$(xhs_post "/feeds/comment" "{\"feed_id\":\"${feed_id}\",\"xsec_token\":\"${xsec_token}\",\"content\":$(echo "$comment" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read().strip()))")}")
                    if echo "$result" | grep -q '"success":true'; then
                        comments_posted=$((comments_posted + 1))
                        log "评论成功! (累计: ${comments_posted})"
                    fi
                fi
            fi
        fi

        sleep $((RANDOM % 120 + 60))  # 随机等待1-3分钟
    done

    log "=== Session 结束 === 浏览: ${posts_browsed} 评论: ${comments_posted} 回复: ${replies_posted}"
}

main "$@"
