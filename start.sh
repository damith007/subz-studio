#!/bin/bash
cd "$(dirname "$0")"
source venv/bin/activate
pkill -9 gunicorn 2>/dev/null; pkill -9 ffmpeg 2>/dev/null; sleep 1
nohup gunicorn --worker-class gevent -w 1 --timeout 1800 --bind 0.0.0.0:5000 app:app > app.log 2>&1 &
echo "Started. Logs: tail -f app.log"
