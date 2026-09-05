# ==========================================
# Stage 1: Build Frontend Assets
# ==========================================
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend

COPY frontend/package*.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

# ==========================================
# Stage 2: Production Backend & Runtime
# ==========================================
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install system dependencies, Tectonic LaTeX engine, and font utilities
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    fontconfig \
    libfontconfig1 \
    libgraphite2-3 \
    libharfbuzz0b \
    libssl3 \
    ca-certificates \
    tar \
    && rm -rf /var/lib/apt/lists/*

# Install Tectonic binary (statically linked musl release to prevent GLIBC version mismatch on Debian Bookworm)
ARG TECTONIC_VERSION=0.17.0
RUN set -eux; \
    ARCH="$(uname -m)"; \
    case "$ARCH" in \
        x86_64) TECTONIC_ARCH="x86_64-unknown-linux-musl" ;; \
        aarch64|arm64) TECTONIC_ARCH="aarch64-unknown-linux-musl" ;; \
        *) echo "Unsupported architecture: $ARCH" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://github.com/tectonic-typesetting/tectonic/releases/download/tectonic%40${TECTONIC_VERSION}/tectonic-${TECTONIC_VERSION}-${TECTONIC_ARCH}.tar.gz" \
        | tar -xz -C /usr/local/bin/; \
    chmod +x /usr/local/bin/tectonic; \
    tectonic --version

# Install Python dependencies
COPY backend/requirements.txt /app/backend/
RUN pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy backend code
COPY backend/ /app/backend/

# Copy built frontend into backend/dist for static serving
COPY --from=frontend-builder /app/frontend/dist /app/backend/dist

# Initialize custom fonts directory
RUN fc-cache -f -v

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/backend/data /app/backend/temp && \
    chown -R appuser:appuser /app

USER appuser

WORKDIR /app/backend
ENV WORKERS=4 \
    PORT=8001

CMD ["sh", "-c", "gunicorn -k uvicorn.workers.UvicornWorker -w ${WORKERS:-4} --bind 0.0.0.0:${PORT:-8001} --timeout 120 --graceful-timeout 30 main:app"]
