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

# Run as an unprivileged user.
RUN useradd --create-home --shell /usr/sbin/nologin shopkeeper \
    && mkdir -p /app/staticfiles /app/media \
    && chown -R shopkeeper:shopkeeper /app
USER shopkeeper

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz/ || exit 1

CMD ["gunicorn", "config.wsgi:application", \
     "--bind", "0.0.0.0:8000", \
     "--workers", "3", \
     "--threads", "2", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
