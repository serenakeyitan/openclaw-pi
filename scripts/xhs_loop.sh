#!/bin/bash
# xhs_loop.sh - 循环调度器
# 每次刷小红书20分钟，然后休息随机5-10分钟，无限循环
# Usage: nohup /root/.openclaw/scripts/xhs_loop.sh &

set -euo pipefail

SCRIPT_DIR="/root/.openclaw/scripts"
LOG="${SCRIPT_DIR}/xhs_loop.log"
PIDFILE="${SCRIPT_DIR}/xhs_loop.pid"

# 写入 PID 文件
echo $$ > "$PIDFILE"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"
}

cleanup() {
    log "收到停止信号，退出..."
    rm -f "$PIDFILE"
    exit 0
}

trap cleanup SIGTERM SIGINT

log "=== XHS Loop 启动 (PID: $$) ==="

cycle=0
while true; do
    cycle=$((cycle + 1))
    log "--- Cycle ${cycle} 开始 ---"

    # 运行浏览 session (20分钟)
    python3 "${SCRIPT_DIR}/xhs_browse.py" 2>&1 | tee -a "$LOG" || {
        log "浏览 session 异常退出，继续下一轮..."
    }

    # 随机休息 5-10 分钟
    break_mins=$((RANDOM % 6 + 5))
    break_secs=$((break_mins * 60))
    log "休息 ${break_mins} 分钟..."
    sleep "$break_secs"
done
