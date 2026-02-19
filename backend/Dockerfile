# ── Backend Dockerfile ─────────────────────────────────────────────
# Multi-stage: slim Python 3.11 base → production-ready image
# ──────────────────────────────────────────────────────────────────

# ---------- build stage ----------
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build deps (needed for some native wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libz-dev \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --upgrade pip \
 && pip install --prefix=/install --no-cache-dir -r requirements.txt


# ---------- runtime stage ----------
FROM python:3.11-slim AS runtime

LABEL maintainer="PharmaGuard Team"
LABEL description="PharmaGuard FastAPI backend — pharmacogenomic risk analysis"

# Non-root user for security
RUN addgroup --system pharma && adduser --system --ingroup pharma pharma

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY backend/app/ ./app/

# Copy optional .env (override via docker compose env_file or environment:)
# We do NOT bake secrets into the image.

# App will run as non-root
RUN chown -R pharma:pharma /app
USER pharma

EXPOSE 8000

# Health check used by docker compose / orchestrators
HEALTHCHECK --interval=20s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
