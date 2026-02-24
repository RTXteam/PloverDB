# Fixed version to avoid breaking changes
FROM python:3.12.12

# Create non-root user with explicit uid/gid (matches ITRB securityContext)
RUN groupadd -g 1000 plover && \
    useradd -u 1000 -g plover -m -s /bin/bash plover

# Install system dependencies
# - libgit2-dev: for pygit2 (code version endpoint)
# - build-essential: for compiling uWSGI
# - ca-certificates: for HTTPS connections
# - nginx: reverse proxy in front of uwsgi for connection buffering.
#   the old tiangolo base image had nginx built in. without it, uwsgi
#   serves http directly and the kernel listen backlog fills up under load.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ca-certificates \
    libgit2-dev \
    build-essential \
    nginx \
    logrotate && \
    rm -rf /var/lib/apt/lists/*

# Set up log files and directories with correct ownership
RUN mkdir -p /var/log/nginx && \
    touch /var/log/ploverdb.log /var/log/uwsgi.log && \
    chown -R plover:plover /var/log/ploverdb.log /var/log/uwsgi.log /var/log/nginx

# Create /app directory with correct ownership
RUN mkdir -p /app && chown plover:plover /app

WORKDIR /app

# Install Python dependencies (includes uwsgi). setuptools in requirements.txt
# for opentelemetry (pkg_resources); uWSGI is started as plover in start.sh.
COPY --chown=plover:plover requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code (includes uwsgi.ini, nginx.conf, start.sh)
COPY --chown=plover:plover ./app /app

# install nginx config -- replaces the nginx that was built into tiangolo.
# nginx sits in front of uwsgi as a connection-buffering reverse proxy.
COPY ./app/nginx.conf /etc/nginx/nginx.conf

# log rotation config (prevents disk fill after multi-day uptime)
COPY ./app/logrotate.conf /etc/logrotate.d/ploverdb
RUN chmod 644 /etc/logrotate.d/ploverdb && chmod +x /app/start.sh

# Copy .git to user's home for pygit2 /code_version endpoint
COPY --chown=plover:plover ./.git /home/plover/.git

# Set environment
ENV HOME=/home/plover

# Match legacy tiangolo uWSGI worker defaults (tunable at runtime)
ENV UWSGI_PROCESSES=16
ENV UWSGI_CHEAPER=8

RUN python -m app.build_indexes && chown -R plover:plover /app

# Expose port
EXPOSE 80

# Run as root so nginx can bind to port 80. start.sh runs uwsgi as plover via runuser.
# uid/gid is NOT set in uwsgi.ini — start.sh handles it with runuser to avoid conflicts.
USER root

# start nginx + uwsgi via startup script.
# nginx buffers connections; uwsgi runs as PID 1 for signal handling.
# see app/start.sh for details on why we need this (tiangolo had supervisord).
CMD ["/app/start.sh"]
