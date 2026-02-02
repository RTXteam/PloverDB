# Fixed version to avoid breaking changes
FROM python:3.12.12

# Create non-root user with explicit uid/gid (matches ITRB securityContext)
RUN groupadd -g 1000 plover && \
    useradd -u 1000 -g plover -m -s /bin/bash plover

# Install system dependencies
# - libgit2-dev: for pygit2 (code version endpoint)
# - build-essential: for compiling uWSGI
# - ca-certificates: for HTTPS connections
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        libgit2-dev \
        build-essential && \
    rm -rf /var/lib/apt/lists/*

# Set up log files with correct ownership
RUN mkdir -p /var/log && \
    touch /var/log/ploverdb.log /var/log/uwsgi.log && \
    chown plover:plover /var/log/ploverdb.log /var/log/uwsgi.log

# Create /app directory with correct ownership
RUN mkdir -p /app && chown plover:plover /app

WORKDIR /app

# Install Python dependencies (includes uwsgi)
COPY --chown=plover:plover requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=plover:plover ./app /app

# Copy .git to user's home for pygit2 /code_version endpoint
COPY --chown=plover:plover ./.git /home/plover/.git

# Set environment
ENV HOME=/home/plover

# Match legacy tiangolo uWSGI worker defaults (tunable at runtime)
ENV UWSGI_PROCESSES=16
ENV UWSGI_CHEAPER=8

# Build indexes (as plover user to ensure correct ownership)
USER plover
RUN python /app/app/build_indexes.py

# Expose port
EXPOSE 80

# Start uWSGI with legacy-style worker scaling (env-driven)
CMD ["sh", "-c", "uwsgi --ini /app/uwsgi.ini --processes ${UWSGI_PROCESSES:-16} --cheaper ${UWSGI_CHEAPER:-8}"]
