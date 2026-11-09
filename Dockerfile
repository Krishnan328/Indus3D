# Multi-stage Docker build for Indus3D: Digital Twin & Web UI

# ── Stage 1: Build React Frontend ───────────────────────────
FROM node:22-alpine AS frontend-builder
WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci --prefer-offline --no-audit

COPY frontend/ ./
RUN npm run build

# ── Stage 2: Runtime Backend Container ──────────────────────
FROM python:3.11-slim AS runtime

LABEL maintainer="Indus3D Authors <krishnan.h@indus3d.org>"
LABEL org.opencontainers.image.title="Indus3D"
LABEL org.opencontainers.image.description="Digital Twin and Quality Controller for FDM 3D Printing"
LABEL org.opencontainers.image.source="https://github.com/Krishnan328/Indus3D"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=5001 \
    INDUS3D_ENV=production \
    INDUS3D_FRONTEND_DIR=/app/frontend/dist

WORKDIR /app

# Install runtime OS packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    sqlite3 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY backend/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend source
COPY backend/ /app/

# Copy built frontend assets from stage 1
COPY --from=frontend-builder /app/frontend/dist /app/frontend/dist

# Security: Create non-root system user
RUN groupadd -g 1000 indus3d && \
    useradd -u 1000 -g indus3d -m -s /bin/bash indus3d && \
    mkdir -p /app/data && \
    chown -R indus3d:indus3d /app

USER indus3d

EXPOSE 5001

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -f http://127.0.0.1:5001/api/v1/twin/state || exit 1

CMD ["python", "main.py"]
