#!/bin/bash
# ── Install Telegram Local Bot API Server ────────────────────────────────────
# For Ubuntu 22.04 / 24.04 (Debian-based VPS)
# Run as root: bash install-telegram-bot-api.sh

set -e

echo "=== Telegram Bot API Server Install ==="

# Method 1: Pre-built binary (fastest — no compilation needed)
install_binary() {
    echo "[1] Downloading pre-built binary..."
    ARCH=$(uname -m)
    if [ "$ARCH" = "x86_64" ]; then
        URL="https://github.com/tdlib/telegram-bot-api/releases/download/v7.9/telegram-bot-api-amd64-linux.zip"
    elif [ "$ARCH" = "aarch64" ]; then
        URL="https://github.com/tdlib/telegram-bot-api/releases/download/v7.9/telegram-bot-api-aarch64-linux.zip"
    else
        echo "Unknown arch: $ARCH — falling back to build from source"
        return 1
    fi

    apt-get install -y unzip curl 2>/dev/null || true
    cd /tmp
    curl -L "$URL" -o tgbotapi.zip
    unzip -o tgbotapi.zip
    chmod +x telegram-bot-api
    mv telegram-bot-api /usr/local/bin/
    echo "[OK] Binary installed to /usr/local/bin/telegram-bot-api"
}

# Method 2: Build from source (takes ~10 mins but always works)
build_from_source() {
    echo "[2] Building from source..."
    apt-get update
    apt-get install -y \
        build-essential cmake git \
        libssl-dev zlib1g-dev \
        gperf

    cd /tmp
    rm -rf telegram-bot-api
    git clone --recursive https://github.com/tdlib/telegram-bot-api.git
    cd telegram-bot-api
    mkdir build && cd build
    cmake -DCMAKE_BUILD_TYPE=Release ..
    cmake --build . --target telegram-bot-api -j$(nproc)
    cp telegram-bot-api /usr/local/bin/
    echo "[OK] Built and installed to /usr/local/bin/telegram-bot-api"
}

# Try binary first, fall back to source
install_binary || build_from_source

# Verify
if command -v telegram-bot-api &>/dev/null; then
    echo ""
    echo "=== Installed: $(telegram-bot-api --version 2>&1 | head -1) ==="
else
    echo "ERROR: Installation failed!"
    exit 1
fi

# Create systemd service for auto-start
cat > /etc/systemd/system/telegram-bot-api.service << 'SERVICE'
[Unit]
Description=Telegram Local Bot API Server
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/telegram-bot-api \
    --api-id=36668698 \
    --api-hash=5e1172b296563abf8ba9939c557c9f66 \
    --local \
    --http-port=8081 \
    --log=/root/sinhala-studio/tgapi.log \
    --verbosity=1
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable telegram-bot-api
systemctl start telegram-bot-api

echo ""
echo "=== Service started! ==="
echo "Status: systemctl status telegram-bot-api"
echo "Logs:   journalctl -u telegram-bot-api -f"
echo "Test:   curl http://localhost:8081/botYOUR_TOKEN/getMe"
