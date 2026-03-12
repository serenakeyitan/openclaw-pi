#!/usr/bin/env bash
# Wrapper that auto-restarts dashboard on reload (exit code 42).
# Reload trigger: touch .reload  (dashboard checks every 1s)
cd "$(dirname "$0")"
rm -f .reload

reset_term() {
    # Exit alternate screen, disable mouse tracking, restore cursor, reset terminal
    printf '\033[?1049l\033[?1000l\033[?1003l\033[?1006l\033[?1015l\033[?25h\033[0m'
    stty sane 2>/dev/null
}

trap reset_term EXIT INT TERM

while true; do
    .venv/bin/python dashboard.py
    rc=$?
    reset_term
    if [ "$rc" -eq 42 ]; then
        sleep 0.3
        continue
    fi
    break
done
