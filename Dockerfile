FROM python:3.12

# Create non-root user with explicit uid/gid
RUN groupadd -g 1000 plover && \
    useradd -u 1000 -g plover -m -s /bin/bash plover

# Install system dependencies (libgit2 for pygit2, ca-certificates for HTTPS)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates libgit2-dev && \
    rm -rf /var/lib/apt/lists/*

# Set up log files with correct ownership
RUN mkdir -p /var/log && \
    touch /var/log/ploverdb.log /var/log/gunicorn.log && \
    chown plover:plover /var/log/ploverdb.log /var/log/gunicorn.log

# Create /app directory with correct ownership before WORKDIR
RUN mkdir -p /app && chown plover:plover /app

WORKDIR /app

# Install Python dependencies
COPY --chown=plover:plover requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=plover:plover ./app /app

# Copy .git to user's home for pygit2 /code_version endpoint
COPY --chown=plover:plover ./.git /home/plover/.git

# Set environment
ENV HOME=/home/plover
# Allow the listening port to be overridden at runtime if needed.
ENV PORT=80

# FALLBACK: If ITRB Kubernetes forces a different uid (e.g., runAsUser in securityContext),
# the ownership check in libgit2/pygit2 will fail. This requires git installed and is not
# consistently honored by pygit2, so treat it as a last resort.
# RUN git config --global --add safe.directory /home/plover

# Build indexes (as plover user to ensure correct ownership)
USER plover
RUN python /app/app/build_indexes.py

# Expose port and set entrypoint
EXPOSE 80
# Use sh -c so the PORT environment variable is expanded at runtime.
CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT} --workers 8 --preload --timeout 600 --access-logfile /var/log/gunicorn.log --error-logfile /var/log/gunicorn.log app.main:app"]
