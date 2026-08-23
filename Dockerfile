# syntax=docker/dockerfile:1
#
# Single-stage image: this is a small Django monolith, and a multi-stage build
# would add complexity for a handful of megabytes.

FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# libpq is needed by psycopg; curl is used by the container health check.
RUN apt-get update && apt-get install --no-install-recommends -y \
        libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Dependencies first, so code edits do not invalidate the layer cache.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Bake the hashed static files into the image. Production uses WhiteNoise's
# manifest storage, so without this every page raises "Missing staticfiles
# manifest entry" on the first request. The key here is a throwaway used only to
# let settings import during the build; the real one comes from the environment.
RUN DJANGO_DEBUG=false \
    DJANGO_SECRET_KEY=build-time-placeholder-not-used-at-runtime \
    DATABASE_URL=postgres://build/placeholder \
    python manage.py collectstatic --noinput --clear

COPY --chmod=0755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

# Run as an unprivileged user.
RUN useradd --create-home --shell /usr/sbin/nologin shopkeeper \
    && mkdir -p /app/staticfiles /app/media \
    && chown -R shopkeeper:shopkeeper /app
USER shopkeeper

# Hosting platforms inject the port to listen on. Default to 8000 so plain
# `docker run` and docker compose still work unchanged.
ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/healthz/" || exit 1

# The entrypoint migrates, ensures the owner, then execs this command, so
# gunicorn still ends up as PID 1 and receives SIGTERM directly.
ENTRYPOINT ["docker-entrypoint.sh"]

# Shell form on purpose: $PORT has to expand at container start, and the JSON
# array form does not run a shell. The inner `exec` matters too: without it the
# shell stays PID 1, SIGTERM never reaches gunicorn, and workers are killed
# rather than drained.
CMD exec gunicorn config.wsgi:application \
      --bind "0.0.0.0:${PORT}" \
      --workers "${WEB_CONCURRENCY:-3}" \
      --threads 2 \
      --timeout 60 \
      --access-logfile - \
      --error-logfile -
