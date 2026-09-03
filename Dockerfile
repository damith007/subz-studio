# ── Subz Studio Pro ──────────────────────────────────────────────────────────
# Multi-stage build: keeps final image lean
# Supports: Sinhala subtitles via libass + Nirmala UI font
#           FFmpeg with libass, fontconfig
#           Telegram Local Bot API Server (optional, run separately)

FROM python:3.11-slim-bookworm

LABEL maintainer="Subz Studio Pro"
LABEL description="Sinhala subtitle burning tool — Flask + FFmpeg + libass"

# ── System deps ───────────────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    # FFmpeg with libass support
    ffmpeg \
    # fontconfig — needed by libass to find fonts
    fontconfig \
    # curl for healthcheck
    curl \
    # telegram-bot-api (optional — uncomment if you want it pre-installed)
    # telegram-bot-api \
    && rm -rf /var/lib/apt/lists/*

# ── App directory ─────────────────────────────────────────────────────────────
WORKDIR /app

# ── Python deps ───────────────────────────────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── App source ────────────────────────────────────────────────────────────────
COPY app.py .
COPY templates/ templates/

# ── Runtime folders (will be mounted as volumes in production) ────────────────
RUN mkdir -p uploads downloads fonts fontcache

# ── Expose port ───────────────────────────────────────────────────────────────
EXPOSE 5000

# ── Healthcheck ───────────────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:5000/ || exit 1

# ── Start with gunicorn (gevent worker for Socket.IO) ────────────────────────
CMD ["gunicorn", \
     "--worker-class", "gevent", \
     "--workers", "1", \
     "--timeout", "1800", \
     "--bind", "0.0.0.0:5000", \
     "--log-level", "info", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "app:app"]
