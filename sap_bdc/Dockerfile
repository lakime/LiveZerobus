# Multi-stage build: compile frontend, then assemble Python runtime.

# ── Stage 1: build the React SPA ────────────────────────────
FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./frontend/
RUN cd frontend && npm ci
COPY frontend ./frontend
RUN cd frontend && npm run build

# ── Stage 2: Python runtime ─────────────────────────────────
FROM python:3.11-slim AS runtime
WORKDIR /app

# Install dependencies that the Databricks Apps runtime gave us for free
RUN pip install --no-cache-dir \
    fastapi==0.115.5 \
    "uvicorn[standard]==0.32.1" \
    pyarrow>=17.0.0 \
    pandas>=2.2.0 \
    faker \
    python-multipart==0.0.12

# Copy backend
COPY app ./app
COPY app.yaml ./

# Copy built frontend from stage 1
COPY --from=frontend /build/frontend/dist ./frontend/dist

# Data directory (mountable as a volume for persistence across restarts)
RUN mkdir -p /data
ENV DATA_DIR=/data

EXPOSE 8000

# Default token — OVERRIDE in production via -e SAP_BDC_TOKEN=...
ENV SAP_BDC_TOKEN=changeme
ENV HOST=http://localhost:8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
