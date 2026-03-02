#!/bin/bash
# start nginx and uwsgi inside the container.
#
# the old tiangolo/uwsgi-nginx-flask image used supervisord to manage both
# processes. we use a simpler approach: start nginx in the background, then
# exec uwsgi as the foreground process (PID 1). this way docker signals
# (SIGTERM on "docker stop") go directly to uwsgi for graceful shutdown.
#
# if uwsgi dies, the container exits -- correct behavior for kubernetes.
# if nginx dies, the watchdog below restarts it so port 80 stays alive.

set -e

# check if nginx master is actually alive (not zombie).
# pgrep alone matches zombie processes, which fooled the watchdog into
# thinking nginx was running when it was actually dead.
nginx_is_alive() {
    local pid
    pid=$(cat /var/run/nginx.pid 2>/dev/null) || return 1
    [ -d "/proc/$pid" ] && [ "$(cat /proc/$pid/status 2>/dev/null | grep '^State:' | awk '{print $2}')" != "Z" ]
}

# background loop: check nginx every 30s, restart if dead.
# also runs logrotate to prevent unbounded log growth on long-lived pods.
nginx_watchdog() {
    while true; do
        sleep 30
        if ! nginx_is_alive; then
            echo "[watchdog] nginx not running, restarting..." >&2
            nginx || echo "[watchdog] nginx restart failed" >&2
        fi
        logrotate /etc/logrotate.d/ploverdb --state /tmp/logrotate.state 2>/dev/null || true
    done
}

# start nginx in background (daemon mode is set in nginx.conf by default)
nginx

# verify nginx actually started before proceeding
sleep 1
if ! nginx_is_alive; then
    echo "ERROR: nginx failed to start on boot" >&2
    exit 1
fi
echo "nginx started successfully"

# launch watchdog in background
nginx_watchdog &
echo "nginx watchdog started (pid $!)"

# Start the FastAPI rebuild server in the background (separate from main app)
# This listens on port 8000 and handles /rebuild requests independently
runuser -u plover -g plover -- uvicorn rebuild_main:app --host 0.0.0.0 --port 8000 &
echo "Rebuild server started on port 8000 (pid $!)"

# Run uwsgi as plover (same user as before we added in-container nginx).
# Starting uwsgi as root and dropping via uid/gid in uwsgi.ini breaks
# pkg_resources import; starting as plover from the beginning restores it.
exec runuser -u plover -g plover -- uwsgi --ini /app/uwsgi.ini \
    --processes ${UWSGI_PROCESSES:-16} \
    --cheaper ${UWSGI_CHEAPER:-8}
