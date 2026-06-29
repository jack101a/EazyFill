# syntax=docker/dockerfile:1

FROM node:20-bookworm-slim AS frontend-builder

WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim-bookworm AS runtime

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        libgl1 \
        libglib2.0-0 \
        postgresql-client \
        rclone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm -f /tmp/requirements.txt

COPY backend/ /app/backend/
COPY docs/public-site/ /app/docs/public-site/
COPY backend/config/ /opt/eazyfill-seed/backend/config/
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY --from=frontend-builder /frontend/dist /app/frontend/dist

RUN mkdir -p /app/backend/app/templates \
             /app/backend/logs \
             /app/backend/backups \
             /app/data/models \
    && cp /app/frontend/dist/index.html /app/backend/app/templates/admin.html \
    && chmod +x /usr/local/bin/docker-entrypoint.sh

ENV APP_ENV=production \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    APP_CONFIG_PATH=/app/backend/config/config.yaml \
    SQLITE_PATH=/app/backend/logs/app.db \
    ONNX_PATH=/app/data/models/model.onnx

EXPOSE 8080
STOPSIGNAL SIGTERM

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD curl -sf http://localhost:8080/health || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
