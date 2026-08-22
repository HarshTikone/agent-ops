# syntax=docker/dockerfile:1
FROM python:3.11-slim AS base

WORKDIR /app

# System deps for building any wheels that need compilation (kept minimal;
# most deps here ship manylinux wheels so this stays small).
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Render (and most PaaS free tiers) injects $PORT at runtime — default to
# 8000 for local `docker run` so the image is still useful standalone.
ENV PORT=8000
EXPOSE 8000

# JSON-array form wrapping a shell so $PORT still expands (Render injects it
# at runtime) while keeping proper signal handling (SIGTERM forwards to
# uvicorn instead of being swallowed by a shell-form CMD).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
