# syntax=docker/dockerfile:1
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

FROM python:3.11-slim AS runtime

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

RUN groupadd --system agentops \
    && useradd --system --gid agentops --home-dir /app --create-home agentops

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv

COPY --chown=agentops:agentops app ./app
COPY --chown=agentops:agentops migrations ./migrations
COPY --chown=agentops:agentops scripts ./scripts

USER agentops
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).read()"]

# Render is the only network path to this container. Trust its forwarding
# proxy so request.client.host (and therefore SlowAPI) identifies the real
# caller instead of rate-limiting every visitor as one internal proxy.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
