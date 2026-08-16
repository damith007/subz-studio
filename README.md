# Subz Studio Pro

A Flask/Socket.IO web app for burning Sinhala subtitles into videos using FFmpeg + libass.

## Features
- Multi-URL + multi-SRT queue processing
- ASS/libass subtitle burn-in with Nirmala UI font (Sinhala, Tamil, Latin)
- Watermark (Subz.LK) top-left
- Promo text at intro, midpoint, and outro
- Archive.org upload with S3 API
- ZIP download of multiple files
- Live progress: download %, encoding bitrate, fps, speed
- Auto audio conversion (MP3/AC3 → AAC)
- Configurable preset and CRF from UI

## Requirements
- Python 3.10+
- FFmpeg with libass (`apt-get install ffmpeg`)
- fontconfig (`apt-get install fontconfig`)

## Setup

```bash
# 1. Clone
git clone https://github.com/youruser/subz-studio.git
cd subz-studio

# 2. Create virtualenv
python3 -m venv venv
source venv/bin/activate

# 3. Install Python deps
pip install -r requirements.txt

# 4. Run
python app.py
# or with gunicorn (recommended):
nohup gunicorn --worker-class gevent -w 1 --timeout 1800 --bind 0.0.0.0:5000 app:app > app.log 2>&1 &
```

## Notes
- `NirmalaB.ttf` is auto-downloaded on first run from a public CDN
- `fonts/`, `uploads/`, `downloads/` folders are created automatically
- Archive.org upload requires S3 API keys from https://archive.org/account/s3.php

## Folder structure
```
subz-studio/
├── app.py              # Flask app + all processing logic
├── templates/
│   └── index.html      # Frontend UI
├── requirements.txt
├── .gitignore
└── README.md
```
