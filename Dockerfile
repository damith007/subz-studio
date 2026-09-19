FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg fontconfig curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py .
COPY templates/ templates/

RUN mkdir -p uploads downloads fonts fontcache logs

EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:5000/health || exit 1

CMD ["gunicorn","--worker-class","gevent","--workers","1","--timeout","1800","--bind","0.0.0.0:5000","--access-logfile","-","--error-logfile","-","app:app"]
