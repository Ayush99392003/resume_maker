#!/usr/bin/env bash
# ==============================================================================
# Production Deployment Script for AI LaTeX Resume Maker (Single VM, 100 Users)
# ==============================================================================

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "========================================================"
echo " Starting Resume Maker Production Deployment"
echo "========================================================"

# 1. System checks
if ! command -v docker &> /dev/null; then
    echo "[ERROR] Docker is not installed. Please install docker before proceeding."
    exit 1
fi

COMPOSE_CMD=""
if docker compose version &> /dev/null; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose &> /dev/null; then
    COMPOSE_CMD="docker-compose"
else
    echo "[ERROR] Docker Compose is not installed."
    exit 1
fi

# 2. Host capacity assessment
CPU_CORES=$(nproc || echo "unknown")
TOTAL_MEM_KB=$(grep MemTotal /proc/meminfo 2>/dev/null | awk '{print $2}' || echo "0")
TOTAL_MEM_GB=$((TOTAL_MEM_KB / 1024 / 1024))

echo "[INFO] Host specifications detected: ${CPU_CORES} CPU cores, ~${TOTAL_MEM_GB} GB RAM"
if [ "$CPU_CORES" != "unknown" ] && [ "$CPU_CORES" -lt 4 ]; then
    echo "[WARN] Host has fewer than 4 CPU cores. For 100 concurrent users with heavy compiles,"
    echo "       an 8 vCPU host is strongly recommended."
fi

# 3. Environment configuration
if [ ! -f ".env.production" ]; then
    if [ -f ".env" ]; then
        echo "[INFO] Using existing .env for deployment."
        ENV_FILE=".env"
    else
        echo "[WARN] No .env.production found. Creating from .env.production.template..."
        cp .env.production.template .env.production
        echo "[IMPORTANT] Please edit .env.production with your real API keys and SESSION_SECRET before running in production."
        ENV_FILE=".env.production"
    fi
else
    ENV_FILE=".env.production"
fi

# 4. Build and deploy containers
echo "[INFO] Building production containers with ${COMPOSE_CMD}..."
$COMPOSE_CMD --env-file "$ENV_FILE" -f docker-compose.prod.yml build

echo "[INFO] Starting containers in detached mode..."
$COMPOSE_CMD --env-file "$ENV_FILE" -f docker-compose.prod.yml up -d --remove-orphans

# 5. Wait for backend healthcheck
echo "[INFO] Waiting for backend cluster to report healthy..."
MAX_RETRIES=20
RETRY_COUNT=0
HEALTHY=0

while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    if curl -s -f "http://localhost/health" > /dev/null 2>&1 || curl -s -f "http://localhost:8001/health" > /dev/null 2>&1; then
        HEALTHY=1
        break
    fi
    echo -n "."
    sleep 3
    RETRY_COUNT=$((RETRY_COUNT + 1))
done
echo ""

if [ $HEALTHY -eq 1 ]; then
    echo "========================================================"
    echo " Deployment Succeeded!"
    echo " Resume Maker is active on: http://localhost"
    echo " Nginx reverse proxy routing: Port 80 / 443"
    echo " Backend Gunicorn cluster running on internal port 8001"
    echo "========================================================"
    $COMPOSE_CMD -f docker-compose.prod.yml ps
else
    echo "[ERROR] Health check failed after 60 seconds. Checking logs..."
    $COMPOSE_CMD -f docker-compose.prod.yml logs --tail 50 backend
    exit 1
fi
