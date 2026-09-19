#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
set -a && source .env && set +a
pkill -f gunicorn 2>/dev/null; sleep 1
mkdir -p logs
nohup gunicorn --worker-class gevent -w 1 --timeout 1800 \
  --bind 0.0.0.0:5000 \
  --access-logfile logs/access.log \
  --error-logfile logs/error.log \
  app:app > logs/gunicorn.log 2>&1 &
echo "Started PID $! — tail -f logs/access.log"
