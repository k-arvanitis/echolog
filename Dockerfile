# syntax=docker/dockerfile:1
# Runtime image for the FastAPI API. Celery workers use the same image with a
# different command (`meeting-worker`). Heavy ML deps (torch, pyannote) make this
# image large; production deployments would split ASR/diarization into their own
# image — see "Out of Scope" in the README.
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev
COPY src ./src
RUN uv sync --frozen --no-dev


FROM python:3.12-slim AS runtime

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 mie

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY --from=builder /opt/venv /opt/venv
COPY --chown=mie:mie src ./src
COPY --chown=mie:mie pyproject.toml uv.lock README.md ./

USER mie
EXPOSE 8001
CMD ["meeting-api"]
