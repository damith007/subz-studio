import subprocess, re, os, uuid, time, threading, requests, chardet, psutil
from PIL import Image, ImageDraw, ImageFont
from flask import Flask, render_template, request, send_from_directory, jsonify, Response
from flask_socketio import SocketIO

app = Flask(__name__)
app.config['SECRET_KEY'] = 'subz_studio_v9'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent')

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'uploads')
FINAL_FOLDER  = os.path.join(BASE_DIR, 'downloads')
FONT_PATH     = os.path.join(BASE_DIR, 'NirmalaB.ttf')
FONT_URL      = "https://static.wfonts.com/data/2016/04/29/nirmala-ui/NirmalaB.ttf"
CPU_THREADS   = max(1, (psutil.cpu_count(logical=False) or 2) - 1)
PRESET        = 'superfast'
CRF           = 18

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(FINAL_FOLDER,  exist_ok=True)

# ── Download Nirmala Bold font if missing ─────────────────────────────────────
if not os.path.exists(FONT_PATH):
    print('[INFO] Downloading NirmalaB.ttf...')
    try:
        r = requests.get(FONT_URL, timeout=30)
        r.raise_for_status()
        with open(FONT_PATH, 'wb') as f:
            f.write(r.content)
        print(f'[INFO] Font saved → {FONT_PATH}')
    except Exception as e:
        print(f'[WARN] Font download failed: {e}')

# ── fontconfig — register NirmalaB.ttf so libass finds it ────────────────────
FC_DIR = os.path.join(BASE_DIR, 'fonts')
os.makedirs(FC_DIR, exist_ok=True)
FC_CACHE = os.path.join(BASE_DIR, 'fontcache')
os.makedirs(FC_CACHE, exist_ok=True)

# Hard-copy font into fonts dir (symlink can fail on some VPS setups)
FC_FONT = os.path.join(FC_DIR, 'NirmalaB.ttf')
if not os.path.exists(FC_FONT) and os.path.exists(FONT_PATH):
    import shutil as _sh
    _sh.copy2(FONT_PATH, FC_FONT)

FC_CONF = os.path.join(BASE_DIR, 'fonts.conf')
with open(FC_CONF, 'w') as _f:
    _f.write(f'''<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <dir>{FC_DIR}</dir>
  <cachedir>{FC_CACHE}</cachedir>
  <match target="pattern">
    <test qual="any" name="family"><string>Nirmala UI</string></test>
    <edit name="family" mode="assign" binding="same"><string>Nirmala UI</string></edit>
  </match>
</fontconfig>''')

os.environ['FONTCONFIG_FILE'] = FC_CONF
os.environ['FONTCONFIG_PATH'] = FC_DIR

# Pre-build fontconfig cache at startup so first job is fast
subprocess.run(['fc-cache', '-f', FC_DIR],
               capture_output=True, env=os.environ.copy())
print(f'[INFO] fontconfig cache built. Font: {FC_FONT}')


# ── Resource monitor ──────────────────────────────────────────────────────────
def monitor_resources():
    while True:
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory().percent
        ff  = [p for p in psutil.process_iter(['name']) if 'ffmpeg' in p.info['name']]
        disk_free = round(psutil.disk_usage(BASE_DIR).free / 1024**3, 1)
        socketio.emit('sys_usage', {
            'cpu': cpu, 'ram': ram,
            'ffmpeg': 'Running' if ff else 'Idle',
            'disk': disk_free
        })
        time.sleep(2)

threading.Thread(target=monitor_resources, daemon=True).start()


# ── HTML/SRT tags → ASS override codes ──────────────────────────────────────
def srt_tags_to_ass(text):
    """
    Convert SRT inline tags to ASS override codes:
      <b>...</b>           → {\\b1}...{\\b0}
      <i>...</i>           → {\\i1}...{\\i0}
      <u>...</u>           → {\\u1}...{\\u0}
      <font color="#rrggbb">...</font>  → {\\c&Hbbggrr&}...{\\c}
      Unicode symbols pass through unchanged (ASS is UTF-8)
    """
    def hex_to_ass_color(hexval):
        # ASS color is &Hbbggrr& (BGR, not RGB)
        h = hexval.lstrip('#')
        if len(h) == 3:
            h = h[0]*2 + h[1]*2 + h[2]*2
        if len(h) != 6:
            return None
        r, g, b = h[0:2], h[2:4], h[4:6]
        return f'&H{b}{g}{r}&'

    def named_color_to_ass(name):
        colors = {
            'white':'&H00FFFFFF','yellow':'&H0000FFFF','red':'&H000000FF',
            'green':'&H0000FF00','blue':'&H00FF0000','cyan':'&H00FFFF00',
            'magenta':'&H00FF00FF','black':'&H00000000','orange':'&H000080FF',
            'pink':'&H00C0C0FF','purple':'&H00800080','gray':'&H00808080',
            'lime':'&H0000FF00','gold':'&H0000D7FF','orange':'&H000045FF',
        }
        return colors.get(name.lower())

    # Process tags left to right
    result = ''
    i = 0
    while i < len(text):
        if text[i] != '<':
            result += text[i]; i += 1; continue
        end = text.find('>', i)
        if end == -1:
            result += text[i]; i += 1; continue
        tag = text[i:end+1]
        tl  = tag.lower()
        if tl in ('<b>', '<strong>'):
            result += '{\\b1}'
        elif tl in ('</b>', '</strong>'):
            result += '{\\b0}'
        elif tl in ('<i>', '<em>'):
            result += '{\\i1}'
        elif tl in ('</i>', '</em>'):
            result += '{\\i0}'
        elif tl in ('<u>',):
            result += '{\\u1}'
        elif tl == '</u>':
            result += '{\\u0}'
        elif tl == '</font>':
            result += '{\\c}'   # reset color to style default
        elif tl.startswith('<font'):
            # Extract color attribute
            cm = re.search(r'color=["\'\']?([^"\'\' >]+)["\'\']?', tag, re.I)
            if cm:
                raw_c = cm.group(1)
                ass_c = hex_to_ass_color(raw_c) or named_color_to_ass(raw_c)
                if ass_c:
                    result += '{\\c' + ass_c + '}'
                # else skip unknown color
        else:
            pass   # drop unknown tags
        i = end + 1

    return result


# ── SRT parser — preserves inline tags for ASS conversion ────────────────────
def parse_srt(srt_path):
    with open(srt_path, 'rb') as f:
        raw = f.read()
    enc     = chardet.detect(raw)['encoding'] or 'utf-8'
    content = raw.decode(enc, errors='ignore')
    content = content.replace('\r\n', '\n').replace('\r', '\n')
    entries = []
    for block in re.split(r'\n{2,}', content.strip()):
        lines = [l.strip() for l in block.strip().splitlines() if l.strip()]
        if len(lines) < 3:
            continue
        tc_line = tc_idx = None
        for idx, line in enumerate(lines):
            tc = re.match(
                r'(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)', line)
            if tc:
                tc_line = tc; tc_idx = idx; break
        if not tc_line:
            continue
        h1,m1,s1,ms1,h2,m2,s2,ms2 = map(int, tc_line.groups())
        text = '\n'.join(lines[tc_idx+1:])
        # Strip ASS override tags only (not HTML — those we convert)
        text = re.sub(r'\{[^}]*\}', '', text)
        text = text.strip()
        if not text:
            continue
        entries.append({
            'start_ms': (h1*3600+m1*60+s1)*1000+ms1,
            'end_ms':   (h2*3600+m2*60+s2)*1000+ms2,
            'text':     text   # HTML tags preserved — converted in build_ass_file
        })
    return entries


# ── Font size scaled to video height ─────────────────────────────────────────
def get_font_size(video_h):
    # 480p→34px  720p→51px  1080p→72px(capped)
    return max(20, min(72, round(video_h / 14)))


# Promo text for intro/outro overlays
PROMO_TEXT = 'නවතම කතා හා ෆිල්ම් සදහා පිවිසෙන්න, subz.lk වෙත'
PROMO_SECS = 30   # show for first 30s and last 30s


# ── SRT entries → ASS file (with tags, promo, unicode) ───────────────────────
def build_ass_file(entries, video_w, video_h, font_size, tmp_dir, duration_s):
    """
    ASS subtitle file with:
      - Sinhala / isipili / pali / komawa via Nirmala UI font
      - Unicode symbols pass-through (ASS is UTF-8)
      - <b><i><u><font color> SRT tags converted to ASS override codes
      - Intro promo: first 30s at top-center (Alignment=8)
      - Outro promo: last 30s at top-center (Alignment=8)
      - Main subtitles: bottom-center (Alignment=2)
    """
    FONT_FAMILY = 'Nirmala UI'
    margin_v    = max(20, int(video_h * 0.04))
    margin_h    = max(20, int(video_w * 0.04))
    promo_size  = max(16, int(font_size * 0.85))   # slightly smaller than subtitles
    promo_mv    = max(20, int(video_h * 0.035))    # top margin for promo

    header = (
        '[Script Info]\n'
        'ScriptType: v4.00+\n'
        f'PlayResX: {video_w}\n'
        f'PlayResY: {video_h}\n'
        'ScaledBorderAndShadow: yes\n'
        'WrapStyle: 0\n'
        'Collisions: Normal\n'
        '\n'
        '[V4+ Styles]\n'
        'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, '
        'OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, '
        'ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, '
        'Alignment, MarginL, MarginR, MarginV, Encoding\n'
        # Default style — white bold, bottom-center
        f'Style: Default,{FONT_FAMILY},{font_size},'
        '&H00FFFFFF,&H000000FF,&H00000000,&H80000000,'
        f'-1,0,0,0,100,100,0,0,1,2.5,0.5,2,'
        f'{margin_h},{margin_h},{margin_v},1\n'
        # Promo style — yellow bold, top-center (alignment=8)
        # 23 fields: Name,Fontname,Fontsize,Primary,Secondary,Outline,Back,
        #            Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,
        #            Spacing,Angle,BorderStyle,Outline,Shadow,
        #            Alignment,MarginL,MarginR,MarginV,Encoding
        f'Style: Promo,{FONT_FAMILY},{promo_size},'
        '&H0000FFFF,&H000000FF,&H00000000,&H90000000,'
        f'-1,0,0,0,100,100,0,0,1,2.0,0.5,8,'
        f'{margin_h},{margin_h},{promo_mv},1\n'
        '\n'
        '[Events]\n'
        'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
    )

    def ms_to_ass(ms):
        ms  = max(0, int(ms))
        h   = ms // 3_600_000; ms -= h * 3_600_000
        m   = ms //    60_000; ms -= m *    60_000
        s   = ms //     1_000
        cs  = (ms % 1_000) // 10
        return f'{h}:{m:02d}:{s:02d}.{cs:02d}'

    def escape_and_convert(text):
        """Escape ASS specials then convert SRT HTML tags to ASS overrides."""
        # Escape literal backslash first
        text = text.replace('\\', '\\\\')
        # Convert HTML tags to ASS overrides (handles {\c}, {\b1} etc.)
        text = srt_tags_to_ass(text)
        # Convert newlines to ASS line break
        text = text.replace('\n', '\\N')
        return text

    def promo_line(start_ms, end_ms):
        t = PROMO_TEXT.replace('\\', '\\\\').replace('\n', '\\N')
        return (f"Dialogue: 0,{ms_to_ass(start_ms)},{ms_to_ass(end_ms)},"
                f"Promo,,0,0,0,,{t}")

    lines = []

    total_ms  = int(duration_s * 1000)
    promo_ms  = PROMO_SECS * 1000
    half_ms   = total_ms // 2   # midpoint of video

    # ── Intro: 0 → 30s ───────────────────────────────────────────────────────
    intro_end = min(promo_ms, total_ms)
    lines.append(promo_line(0, intro_end))

    # ── Mid: (half - 15s) → (half + 15s)  [centred on midpoint, 30s total] ──
    mid_start = max(intro_end + 1, half_ms - promo_ms // 2)
    mid_end   = min(mid_start + promo_ms, total_ms)
    # Only add if it doesn't overlap intro and has enough room
    if mid_start + 5000 < mid_end:
        lines.append(promo_line(mid_start, mid_end))
    else:
        mid_end = intro_end   # track for outro gap check

    # ── Outro: (duration-30s) → end ──────────────────────────────────────────
    outro_start = max(mid_end + 1, total_ms - promo_ms)
    outro_end   = total_ms
    if outro_start + 5000 < outro_end:
        lines.append(promo_line(outro_start, outro_end))

    # ── Subtitle dialogues ────────────────────────────────────────────────────
    for e in entries:
        text = escape_and_convert(e['text'])
        lines.append(
            f"Dialogue: 0,{ms_to_ass(e['start_ms'])},{ms_to_ass(e['end_ms'])},"
            f"Default,,0,0,0,,{text}"
        )

    ass_path = os.path.join(tmp_dir, 'subtitles.ass')
    with open(ass_path, 'w', encoding='utf-8-sig') as f:
        f.write(header + '\n'.join(lines) + '\n')

    print(f'[ASS] {len(lines)} lines ({len(entries)} subs + promo) → {ass_path}')
    return ass_path


# ── Watermark PNG ─────────────────────────────────────────────────────────────
def build_watermark_png(w, h, out_png):
    sz   = max(18, h // 24)
    try:   font = ImageFont.truetype(FONT_PATH, sz)
    except: font = ImageFont.load_default()
    img  = Image.new('RGBA', (w, h), (0,0,0,0))
    draw = ImageDraw.Draw(img)
    pad  = 12
    b1   = draw.textbbox((0,0), 'Subz', font=font)
    b2   = draw.textbbox((0,0), '.LK',  font=font)
    w1   = b1[2]-b1[0]; w2 = b2[2]-b2[0]
    th   = max(b1[3]-b1[1], b2[3]-b2[1])
    bp   = 5
    draw.rounded_rectangle(
        [pad-bp, pad-bp, pad+w1+w2+bp*2, pad+th+bp*2],
        radius=5, fill=(0,0,0,140))
    draw.text((pad, pad),    'Subz', font=font, fill=(255,255,255,230))
    draw.text((pad+w1, pad), '.LK',  font=font, fill=(220,38,38,230))
    img.save(out_png)


# ── ffprobe helpers ───────────────────────────────────────────────────────────
def get_duration(path):
    try:
        r = subprocess.run(
            ['ffprobe','-v','error','-show_entries','format=duration',
             '-of','default=noprint_wrappers=1:nokey=1', path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return float(r.stdout.strip())
    except: return 1.0

def get_video_size(path):
    try:
        r = subprocess.run(
            ['ffprobe','-v','error','-select_streams','v:0',
             '-show_entries','stream=width,height','-of','csv=s=x:p=0', path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        w, h = map(int, r.stdout.strip().split('x'))
        return w, h
    except: return 1280, 720

def get_video_fps(path):
    try:
        r = subprocess.run(
            ['ffprobe','-v','error','-select_streams','v:0',
             '-show_entries','stream=r_frame_rate',
             '-of','default=noprint_wrappers=1:nokey=1', path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        num, den = r.stdout.strip().split('/')
        fps = round(int(num) / int(den), 3)
        return fps if fps > 0 else 25
    except: return 25

def get_audio_codec(path):
    """Return audio codec name e.g. 'aac', 'mp3', 'ac3', or None."""
    try:
        r = subprocess.run(
            ['ffprobe','-v','error','-select_streams','a:0',
             '-show_entries','stream=codec_name',
             '-of','default=noprint_wrappers=1:nokey=1', path],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return r.stdout.strip().lower() or None
    except: return None

def get_file_size_mb(path):
    try: return round(os.path.getsize(path) / 1024 / 1024, 1)
    except: return 0


# ── FFmpeg progress reader ────────────────────────────────────────────────────
def read_ffmpeg_progress(proc, duration_s, progress_cb, pct_start, pct_range, label):
    buf = b''
    bitrate_str = ''
    while True:
        chunk = proc.stdout.read(1024)
        if not chunk: break
        buf += chunk
        while True:
            found = False
            for sep in [b'\r\n', b'\r', b'\n']:
                idx = buf.find(sep)
                if idx != -1:
                    line = buf[:idx].decode('utf-8', errors='ignore')
                    buf  = buf[idx+len(sep):]
                    m = re.search(r'time=(\d+):(\d+):(\d+\.?\d*)', line)
                    if m and duration_s > 0:
                        h, mn, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
                        elapsed  = h*3600 + mn*60 + s
                        pct      = min(round(pct_start + (elapsed/duration_s)*pct_range, 1),
                                       pct_start + pct_range)
                        bm = re.search(r'bitrate=\s*([\d.]+\s*\S*bits/s)', line)
                        if bm: bitrate_str = bm.group(1)
                        sm  = re.search(r'speed=\s*([\d.]+x)', line)
                        fpm = re.search(r'fps=\s*([\d.]+)', line)
                        extra = ''
                        if sm:  extra += ' · ' + sm.group(1)
                        if fpm: extra += ' · ' + fpm.group(1) + 'fps'
                        progress_cb(pct, label + extra, bitrate_str)
                    found = True; break
            if not found: break
    proc.wait()
    return proc.returncode


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route('/')
def index(): return render_template('index.html')

@app.route('/upload-srt', methods=['POST'])
def upload_srt():
    files = request.files.getlist('files[]') or [request.files.get('file')]
    saved = []
    for f in files:
        if not f: continue
        srt_name = f"{uuid.uuid4().hex}.srt"
        f.save(os.path.join(UPLOAD_FOLDER, srt_name))
        saved.append(srt_name)
    return jsonify({'filenames': saved}), 200

@app.route('/get-files/<folder_type>')
def get_files(folder_type):
    folder = FINAL_FOLDER if folder_type == 'downloads' else UPLOAD_FOLDER
    items  = sorted(os.listdir(folder), reverse=True)
    files  = [f for f in items
              if not f.startswith('.') and not f.startswith('tmp_')
              and os.path.isfile(os.path.join(folder, f))]
    return jsonify([{
        'name': f,
        'size': round(os.path.getsize(os.path.join(folder, f)) / 1024/1024, 1)
    } for f in files])

@app.route('/delete-file/<folder_type>/<filename>', methods=['POST'])
def delete_file(folder_type, filename):
    import shutil
    folder = FINAL_FOLDER if folder_type == 'downloads' else UPLOAD_FOLDER
    fp     = os.path.join(folder, filename)
    if not os.path.exists(fp): return {'status': 'error'}, 404
    shutil.rmtree(fp) if os.path.isdir(fp) else os.remove(fp)
    return {'status': 'deleted'}, 200

@app.route('/delete-all/<folder_type>', methods=['POST'])
def delete_all(folder_type):
    import shutil
    folder  = FINAL_FOLDER if folder_type == 'downloads' else UPLOAD_FOLDER
    removed = 0
    for name in os.listdir(folder):
        fp = os.path.join(folder, name)
        if name.startswith('.'): continue
        try:
            shutil.rmtree(fp) if os.path.isdir(fp) else os.remove(fp)
            removed += 1
        except: pass
    return {'status': 'ok', 'removed': removed}, 200

@app.route('/cleanup-tmp', methods=['POST'])
def cleanup_tmp():
    import shutil
    removed = 0
    for name in os.listdir(UPLOAD_FOLDER):
        if name.startswith('tmp_'):
            shutil.rmtree(os.path.join(UPLOAD_FOLDER, name), ignore_errors=True)
            removed += 1
    return {'status': 'ok', 'removed': removed}, 200

@app.route('/download/<f>')
def download_file(f): return send_from_directory(FINAL_FOLDER, f)

@app.route('/download-zip', methods=['POST'])
def download_zip():
    import zipfile, io
    data      = request.get_json()
    filenames = data.get('filenames', [])
    if not filenames:
        return jsonify({'status': 'error', 'msg': 'No files'}), 400
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        for fname in filenames:
            fp = os.path.join(FINAL_FOLDER, fname)
            if os.path.exists(fp) and os.path.isfile(fp):
                zf.write(fp, fname)
    buf.seek(0)
    return Response(buf.getvalue(), mimetype='application/zip',
        headers={'Content-Disposition':
                 f'attachment; filename=subz_{uuid.uuid4().hex[:8]}.zip'})



# ── Telegram upload via Local Bot API Server ─────────────────────────────────
# Uses your Telegram App credentials (api_id + api_hash) with a local
# telegram-bot-api server running on the VPS — supports files up to 2 GB.
# Official Bot API only allows 50 MB; local server bypasses this limit.
#
# One-time VPS setup:
#   apt-get install telegram-bot-api
#   nohup telegram-bot-api \
#     --api-id=36668698 \
#     --api-hash=5e1172b296563abf8ba9939c557c9f66 \
#     --local --http-port=8081 &

TG_API_ID   = os.environ.get('TG_API_ID',   '36668698')
TG_API_HASH = os.environ.get('TG_API_HASH', '5e1172b296563abf8ba9939c557c9f66')
TG_LOCAL_PORT = 8081   # local Bot API server port


def tg_api_url(token, method, local=True):
    base = f'http://localhost:{TG_LOCAL_PORT}/bot' if local else 'https://api.telegram.org/bot'
    return f'{base}{token}/{method}'


def check_tg_local_server(token):
    """Ping local Bot API server — returns True if running."""
    try:
        r = requests.get(tg_api_url(token, 'getMe', local=True), timeout=5)
        return r.status_code == 200 and r.json().get('ok')
    except:
        return False


@app.route('/check-tg-server', methods=['POST'])
def check_tg_server():
    """Check if local Bot API server is running."""
    data  = request.get_json()
    token = data.get('bot_token', '').strip()
    if not token:
        return jsonify({'running': False, 'msg': 'Bot token ලබාදෙන්න'}), 400
    running = check_tg_local_server(token)
    return jsonify({
        'running': running,
        'msg': f'Local Bot API server {"running ✓" if running else "running නැත ✗"} (localhost:{TG_LOCAL_PORT})'
    })


@app.route('/start-tg-server', methods=['POST'])
def start_tg_server():
    """Start the local Bot API server if not already running."""
    data  = request.get_json()
    token = data.get('bot_token', '').strip()

    # Check if already running
    if check_tg_local_server(token):
        return jsonify({'status': 'already_running', 'msg': 'Server already running'})

    log_path = os.path.join(BASE_DIR, 'tgapi.log')
    cmd = [
        'telegram-bot-api',
        f'--api-id={TG_API_ID}',
        f'--api-hash={TG_API_HASH}',
        '--local',
        f'--http-port={TG_LOCAL_PORT}',
        '--daemonize',
        f'--log={log_path}'
    ]
    try:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(3)   # give it time to start
        running = check_tg_local_server(token)
        return jsonify({
            'status': 'started' if running else 'failed',
            'msg':    'Server started ✓' if running else 'Server start failed — tgapi.log check කරන්න'
        })
    except FileNotFoundError:
        return jsonify({
            'status': 'not_installed',
            'msg':    'telegram-bot-api installed නැත. apt-get install telegram-bot-api'
        }), 500


@app.route('/upload-to-telegram', methods=['POST'])
def upload_to_telegram():
    data      = request.get_json()
    filename  = data.get('filename', '')
    bot_token = data.get('bot_token', '').strip()
    chat_id   = data.get('chat_id', '').strip()
    caption   = data.get('caption', filename).strip()
    use_local = data.get('use_local', True)
    file_path = os.path.join(FINAL_FOLDER, filename)

    if not os.path.exists(file_path):
        return jsonify({'status': 'error', 'msg': 'File not found'}), 404
    if not bot_token or not chat_id:
        return jsonify({'status': 'error', 'msg': 'Bot Token සහ Chat ID ලබාදෙන්න'}), 400

    def do_upload():
        try:
            file_size    = os.path.getsize(file_path)
            file_size_mb = round(file_size / 1024 / 1024, 1)

            # Auto-check local server if use_local
            if use_local:
                if not check_tg_local_server(bot_token):
                    socketio.emit('tg_status', {
                        'msg': '⚠ Local server running නැත. "Start Server" click කරන්න.',
                        'error': True
                    })
                    return
                api = 'local'
            else:
                if file_size_mb > 50:
                    socketio.emit('tg_status', {
                        'msg': f'⚠ {file_size_mb}MB > 50MB limit. Local server use කරන්න.',
                        'error': True
                    })
                    return
                api = 'official'

            socketio.emit('tg_status', {
                'msg': f'Uploading {file_size_mb}MB via {api} API...',
                'pct': 0
            })

            # Progress-tracking wrapper
            class PF:
                def __init__(self, path, total):
                    self._f = open(path, 'rb')
                    self._t = total
                    self._d = 0
                def read(self, sz=-1):
                    chunk = self._f.read(sz)
                    if chunk:
                        self._d += len(chunk)
                        pct = round(self._d / self._t * 100, 1)
                        socketio.emit('tg_status', {
                            'msg': f'Uploading {pct}% · {round(self._d/1024/1024,1)}/{file_size_mb} MB',
                            'pct': pct
                        })
                    return chunk
                def __len__(self): return self._t
                def close(self): self._f.close()

            pf = PF(file_path, file_size)
            url = tg_api_url(bot_token, 'sendVideo', local=use_local)

            try:
                resp = requests.post(
                    url,
                    data={
                        'chat_id':            chat_id,
                        'caption':            caption[:1024],
                        'supports_streaming': 'true',
                        'parse_mode':         'HTML',
                    },
                    files={'video': (filename, pf, 'video/mp4')},
                    timeout=7200
                )
            finally:
                pf.close()

            result = resp.json()
            if result.get('ok'):
                msg_id = result['result'].get('message_id', '')
                # Build link for channels
                tg_url = ''
                cid = str(chat_id)
                if cid.startswith('-100'):
                    tg_url = f'https://t.me/c/{cid[4:]}/{msg_id}'
                socketio.emit('tg_done', {
                    'msg':    f'✓ Upload සාර්ථකයි! Message ID: {msg_id}',
                    'url':    tg_url,
                    'msg_id': msg_id
                })
            else:
                err = result.get('description', 'Unknown error')
                socketio.emit('tg_status', {'msg': f'Failed: {err}', 'error': True})

        except requests.exceptions.ConnectionError:
            socketio.emit('tg_status', {
                'msg': f'Connection error — local server running ද? (localhost:{TG_LOCAL_PORT})',
                'error': True
            })
        except Exception as e:
            socketio.emit('tg_status', {'msg': f'Error: {e}', 'error': True})

    threading.Thread(target=do_upload, daemon=True).start()
    return jsonify({'status': 'started'})


# ── Single job processor ──────────────────────────────────────────────────────
def process_one(job_num, total_jobs, video_url, srt_filename, preset=None, crf=None):
    unique_id = str(uuid.uuid4())[:8]
    tmp_dir   = os.path.join(UPLOAD_FOLDER, f'tmp_{unique_id}')
    os.makedirs(tmp_dir, exist_ok=True)
    raw_video = os.path.join(tmp_dir, 'raw.mp4')

    url_fn = video_url.rstrip('/').split('/')[-1].split('?')[0]
    url_fn = re.sub(r'[^a-zA-Z0-9._-]', '_', url_fn) or 'video.mp4'
    if not url_fn.lower().endswith('.mp4'): url_fn += '.mp4'
    base, ext  = os.path.splitext(url_fn)
    final_name = url_fn
    candidate  = os.path.join(FINAL_FOLDER, final_name)
    n = 1
    while os.path.exists(candidate):
        final_name = f'{base}_{n}{ext}'
        candidate  = os.path.join(FINAL_FOLDER, final_name)
        n += 1
    final_path = candidate
    srt_path   = os.path.join(UPLOAD_FOLDER, srt_filename)
    prefix     = f'[{job_num}/{total_jobs}] '

    def emit(pct, task, bitrate=''):
        socketio.emit('progress', {
            'percentage': pct, 'task': prefix + task,
            'bitrate': bitrate, 'job': job_num, 'total': total_jobs})

    try:
        # ── 1. Download ───────────────────────────────────────────────────────
        emit(0, 'Downloading...')
        with requests.get(video_url, stream=True, timeout=120) as r:
            r.raise_for_status()
            total = int(r.headers.get('content-length', 0))
            done  = 0
            with open(raw_video, 'wb') as f:
                for chunk in r.iter_content(chunk_size=2*1024*1024):
                    f.write(chunk); done += len(chunk)
                    if total:
                        emit(round(done/total*20, 1), 'Downloading...')

        video_w, video_h = get_video_size(raw_video)
        duration_s       = get_duration(raw_video)
        font_size        = get_font_size(video_h)
        fps              = get_video_fps(raw_video)
        raw_mb           = get_file_size_mb(raw_video)

        socketio.emit('file_info', {
            'job': job_num,
            'file': 'raw.mp4',
            'details': f'{video_w}x{video_h} · {fps}fps · {round(duration_s)}s · {raw_mb} MB'
        })
        emit(20, f'raw.mp4 · {raw_mb}MB · {video_w}x{video_h} · {fps}fps')

        # ── 2. Parse SRT ──────────────────────────────────────────────────────
        emit(21, 'SRT parse කරමින්...')
        entries = parse_srt(srt_path)
        if not entries:
            socketio.emit('status', {'msg': prefix + 'SRT subtitles නැත!'}); return False
        emit(22, f'SRT: {len(entries)} entries · {len({e["text"] for e in entries})} unique')

        # ── 3. Build ASS file ─────────────────────────────────────────────────
        emit(25, 'SRT → ASS converting...')
        ass_path = build_ass_file(entries, video_w, video_h, font_size, tmp_dir, duration_s)
        ass_mb   = get_file_size_mb(ass_path)
        socketio.emit('file_info', {
            'job': job_num,
            'file': 'subtitles.ass',
            'details': f'{len(entries)} subtitles · font {font_size}px · {ass_mb} MB'
        })
        emit(30, f'subtitles.ass ready · {ass_mb}MB · {len(entries)} subs')

        # ── 4. Watermark ──────────────────────────────────────────────────────
        emit(32, 'Watermark සාදමින්...')
        wm_png = os.path.join(tmp_dir, 'watermark.png')
        build_watermark_png(video_w, video_h, wm_png)

        # ── 5. Encode with ASS burn-in ────────────────────────────────────────
        _preset = preset or PRESET
        _crf    = crf    if crf is not None else CRF
        emit(35, f'Encoding · libass · {_preset} · CRF{_crf}...')

        # Escape ass path for FFmpeg filter string
        # On Linux: escape backslash → nothing, colon → \:
        ass_esc = ass_path.replace('\\', '/').replace(':', '\\:')
        fonts_esc = FC_DIR.replace('\\', '/').replace(':', '\\:')

        # libass filter: ass= burns subtitles, fontsdir= tells libass where fonts are
        # FONTCONFIG_FILE env tells fontconfig where fonts.conf is
        vf = f"ass='{ass_esc}':fontsdir='{fonts_esc}'"

        ff_env = os.environ.copy()
        ff_env['FONTCONFIG_FILE'] = FC_CONF
        ff_env['FONTCONFIG_PATH'] = FC_DIR

        # Detect audio codec — MP4 needs AAC; copy only if already AAC/AC3/ALAC
        _audio_codec = get_audio_codec(raw_video)
        _aac_compat  = {'aac', 'alac', 'mp4a'}
        if _audio_codec in _aac_compat:
            audio_args = ['-c:a', 'copy']
            emit(34, f'Audio: {_audio_codec} → copy (no re-encode)')
        else:
            audio_args = ['-c:a', 'aac', '-b:a', '192k', '-ar', '48000']
            emit(34, f'Audio: {_audio_codec or "unknown"} → AAC 192k')

        ff_cmd = [
            'ffmpeg', '-y',
            '-i', raw_video,
            '-i', wm_png,
            '-filter_complex',
            # ass burn-in → scale to exact source res → overlay watermark
            f"[0:v]{vf},scale={video_w}:{video_h}:flags=lanczos[subbed];"
            f"[1:v]scale={video_w}:{video_h}:flags=lanczos,setpts=PTS-STARTPTS[wv];"
            "[subbed][wv]overlay=0:0:format=auto[vout]",
            '-map', '[vout]',
            '-map', '0:a?',
            '-c:v', 'libx264',
            '-preset', _preset,
            '-crf', str(_crf),
            '-threads', str(CPU_THREADS),
        ] + audio_args + [
            '-t', f'{duration_s:.6f}',
            '-movflags', '+faststart',
            final_path
        ]

        proc = subprocess.Popen(
            ff_cmd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=ff_env)
        rc = read_ffmpeg_progress(proc, duration_s, emit, 35, 65, 'Encoding')

        if rc == 0:
            size_mb = get_file_size_mb(final_path)
            socketio.emit('job_done', {
                'job': job_num, 'total': total_jobs,
                'filename': final_name, 'size': size_mb,
                'resolution': f'{video_w}x{video_h}',
                'duration': round(duration_s),
                'preset': _preset, 'crf': _crf
            })
            return True
        else:
            socketio.emit('status', {'msg': prefix + 'FFmpeg error!'}); return False

    except Exception as e:
        import traceback; traceback.print_exc()
        socketio.emit('status', {'msg': prefix + f'Error: {e}'}); return False

    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)
        if os.path.exists(srt_path):
            try: os.remove(srt_path)
            except: pass


# ── Queue processor ───────────────────────────────────────────────────────────
@socketio.on('start_automation')
def process(data):
    jobs   = data.get('jobs') or [{'url': data['url'], 'srt_name': data['srt_name']}]
    total  = len(jobs)
    preset = data.get('preset', PRESET)
    crf    = int(data.get('crf', CRF))
    # Validate preset
    valid_presets = {'ultrafast','superfast','veryfast','faster','fast','medium','slow','slower','veryslow'}
    if preset not in valid_presets: preset = PRESET
    crf = max(0, min(51, crf))
    socketio.emit('queue_start', {
        'total': total, 'preset': preset,
        'crf': crf, 'threads': CPU_THREADS
    })
    completed = failed = 0
    for i, job in enumerate(jobs, 1):
        ok = process_one(i, total, job['url'], job['srt_name'], preset=preset, crf=crf)
        if ok: completed += 1
        else:  failed    += 1
    socketio.emit('finished', {
        'success': True, 'completed': completed,
        'failed': failed, 'total': total
    })


if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
