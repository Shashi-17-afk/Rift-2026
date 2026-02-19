# ── Backend Dockerfile ─────────────────────────────────────────────
# Multi-stage: slim Python 3.11 base → production-ready image
# ──────────────────────────────────────────────────────────────────

# ---------- build stage ----------
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build deps (needed for native wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY backend/requirements.txt .
RUN pip install --upgrade pip \
 && pip install --prefix=/install --no-cache-dir -r requirements.txt


# ---------- runtime stage ----------
FROM python:3.11-slim AS runtime

LABEL maintainer="PharmaGuard Team"
LABEL description="PharmaGuard FastAPI backend — pharmacogenomic risk analysis"

# Create non-root user
RUN addgroup --system pharma && adduser --system --ingroup pharma pharma

WORKDIR /app

# Copy installed dependencies
COPY --from=builder /install /usr/local

# Copy backend source code
COPY backend/app/ ./app/

# Fix permissions
RUN chown -R pharma:pharma /app
USER pharma

# Render requires exposed port
EXPOSE 8000

# Healthcheck for container orchestration
HEALTHCHECK --interval=20s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Start FastAPI server
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
