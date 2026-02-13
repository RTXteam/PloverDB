#!/bin/bash
# start nginx and uwsgi inside the container.
#
# the old tiangolo/uwsgi-nginx-flask image used supervisord to manage both
# processes. we use a simpler approach: start nginx in the background, then
# exec uwsgi as the foreground process (PID 1). this way docker signals
# (SIGTERM on "docker stop") go directly to uwsgi for graceful shutdown.
#
# if uwsgi dies, the container exits -- correct behavior for kubernetes.
# if nginx dies, uwsgi still works (just without connection buffering).

set -e

# start nginx in background (daemon mode is set in nginx.conf by default)
nginx

# Run uwsgi as plover (same user as before we added in-container nginx).
# Starting uwsgi as root and dropping via uid/gid in uwsgi.ini breaks
# pkg_resources import; starting as plover from the beginning restores it.
exec runuser -u plover -g plover -- uwsgi --ini /app/uwsgi.ini \
    --processes ${UWSGI_PROCESSES:-16} \
    --cheaper ${UWSGI_CHEAPER:-8}
