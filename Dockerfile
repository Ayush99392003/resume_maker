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
FROM python:3.11-slim

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
    libicu72 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Tectonic binary
RUN curl --proto '=https' --tlsv1.2 -fsSL https://drop-sh.fullyjustified.net | sh \
    && mv tectonic /usr/local/bin/tectonic \
    && chmod +x /usr/local/bin/tectonic

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
EXPOSE 8001

CMD ["python", "main.py"]
