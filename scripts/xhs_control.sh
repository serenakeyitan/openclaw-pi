#!/bin/bash
# xhs_control.sh - 控制 XHS 自动浏览
# Usage: xhs_control.sh start|stop|status|log

SCRIPT_DIR="/root/.openclaw/scripts"
PIDFILE="${SCRIPT_DIR}/xhs_loop.pid"
LOG="${SCRIPT_DIR}/xhs_loop.log"
BROWSE_LOG="${SCRIPT_DIR}/xhs_browse.log"

case "${1:-}" in
    start)
        if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
            echo "已在运行 (PID: $(cat "$PIDFILE"))"
            exit 1
        fi
        echo "启动 XHS 自动浏览..."
        nohup bash "${SCRIPT_DIR}/xhs_loop.sh" >> "$LOG" 2>&1 &
        echo "已启动 (PID: $!)"
        ;;
    stop)
        if [ -f "$PIDFILE" ]; then
            pid=$(cat "$PIDFILE")
            if kill -0 "$pid" 2>/dev/null; then
                kill "$pid"
                echo "已停止 (PID: ${pid})"
            else
                echo "进程已不存在"
            fi
            rm -f "$PIDFILE"
        else
            echo "未在运行"
        fi
        ;;
    status)
        if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
            echo "运行中 (PID: $(cat "$PIDFILE"))"
            echo "最近日志:"
            tail -5 "$LOG" 2>/dev/null || echo "(无日志)"
        else
            echo "未运行"
        fi
        ;;
    log)
        tail -30 "$BROWSE_LOG" 2>/dev/null || echo "(无日志)"
        ;;
    *)
        echo "Usage: $0 {start|stop|status|log}"
        exit 1
        ;;
esac
