#!/usr/bin/env bash
# Wrapper that auto-restarts dashboard on reload (exit code 42).
# Reload trigger: touch .reload  (dashboard checks every 1s)
# Only one instance allowed — kills any existing dashboard on start.
cd "$(dirname "$0")"
rm -f .reload

PIDFILE=".dashboard.pid"

# Kill ALL other dashboard processes before starting
pkill -f "python.*dashboard\.py" 2>/dev/null
sleep 0.5

reset_term() {
    printf '\033[?1049l\033[?1000l\033[?1003l\033[?1006l\033[?1015l\033[?25h\033[0m'
    stty sane 2>/dev/null
    rm -f "$PIDFILE"
}

trap reset_term EXIT INT TERM

while true; do
    .venv/bin/python dashboard.py &
    echo $! > "$PIDFILE"
    wait $!
    rc=$?
    reset_term
    if [ "$rc" -eq 42 ]; then
        sleep 0.3
        continue
    fi
    break
done
