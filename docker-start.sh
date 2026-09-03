#!/bin/bash
# Quick Docker start script for Subz Studio Pro
set -e

echo "=== Subz Studio Pro - Docker Setup ==="

# Create required directories
mkdir -p uploads downloads fontcache tg-data ssl

# Check docker is installed
if ! command -v docker &>/dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
fi

# Check docker compose
if ! docker compose version &>/dev/null 2>&1; then
    echo "ERROR: Docker Compose v2 required. Update Docker."
    exit 1
fi

echo ""
echo "Choose startup mode:"
echo "  1) App + Telegram server  (recommended)"
echo "  2) App only               (no Telegram)"
echo "  3) App + Telegram + Nginx (production)"
echo ""
read -p "Choice [1]: " choice
choice=${choice:-1}

case $choice in
    1)
        docker compose up -d subz-studio tg-server
        ;;
    2)
        docker compose up -d subz-studio
        ;;
    3)
        if [ ! -f ssl/cert.pem ] || [ ! -f ssl/key.pem ]; then
            echo "SSL certs not found in ./ssl/ — generating self-signed..."
            openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
                -keyout ssl/key.pem -out ssl/cert.pem \
                -subj "/CN=studio.subz.lk"
        fi
        docker compose --profile nginx up -d
        ;;
    *)
        docker compose up -d subz-studio tg-server
        ;;
esac

echo ""
echo "=== Started! ==="
echo "Studio:  http://$(hostname -I | awk '{print $1}'):5000"
echo "Logs:    docker compose logs -f subz-studio"
echo "Stop:    docker compose down"
