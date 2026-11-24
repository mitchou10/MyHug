# syntax=docker/dockerfile:1

FROM python:3.13-slim AS builder
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev --no-install-project
COPY worker ./worker
RUN uv sync --frozen --no-dev

# Local development (docker-compose.yaml). Not an image to ship.
FROM python:3.13-slim AS dev
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev --no-install-project
ENV PATH="/app/.venv/bin:$PATH"
COPY worker ./worker
CMD ["celery", "-A", "worker.celery_app", "worker", "-Q", "datasets", "--loglevel=info"]

# The worker listens to nothing: no port, no HTTP health check. It is run as `worker` (the default) or, for the clock of
# the safety nets (one only), with the command `celery -A worker.celery_app beat`.
FROM python:3.13-slim AS runtime
# pip is a build tool: the runtime image never installs anything.
RUN python -m pip uninstall -y pip
RUN useradd --create-home --uid 1000 app
WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --from=builder --chown=app:app /app/worker /app/worker
USER app
ENV PATH="/app/.venv/bin:$PATH"
CMD ["celery", "-A", "worker.celery_app", "worker", "-Q", "datasets", "--loglevel=info"]
