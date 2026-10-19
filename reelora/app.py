import os, re, time, uuid, threading, html
from urllib.parse import urlparse, quote
from flask import Flask, request, jsonify, send_file, send_from_directory, abort, Response
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix
import yt_dlp

try:
    import curl_cffi  # noqa: F401
    from yt_dlp.networking.impersonate import ImpersonateTarget
    CAN_IMPERSONATE = True
except Exception:
    CAN_IMPERSONATE = False

app = Flask(__name__, static_folder="static", static_url_path="")
app.debug = False
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024          # JSON ی داواکاری هەرگیز گەورە نییە
app.config["JSON_AS_ASCII"] = False
# Render/Railway proxy ێکی یەک-ڕێز لە پێشەوەیە؛ تەنها ئەو ڕێزە باوەڕپێکراوە
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# ── ڕێکخستنەکان لە ڕێگەی Environment Variables ──────────────────────────
# ALLOWED_ORIGINS: تەنها ئەگەر ڕووکار لە دۆمەینێکی جیاوازە، نموونە: https://my-site.vercel.app
ALLOWED_ORIGINS = [o.strip().rstrip("/") for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
SHOW_DETAIL = os.environ.get("SHOW_DETAIL") == "1"   # تەنها بۆ دیباگ، بە پێشوەخت کوژاوەیە
COOKIES_FILE = os.environ.get("COOKIES_FILE")
# پەیوەندی (بۆ لاپەڕەی ڕیکلام و یاساییەکان) — هەموو ئارەزوومەندانەن
CONTACT_EMAIL = os.environ.get("CONTACT_EMAIL", "").strip()
CONTACT_WHATSAPP = re.sub(r"\D", "", os.environ.get("CONTACT_WHATSAPP", ""))      # ژمارە بە کۆدی وڵاتەوە، نموونە 9647501234567
CONTACT_TELEGRAM = os.environ.get("CONTACT_TELEGRAM", "").strip().lstrip("@")
PAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pages")

if ALLOWED_ORIGINS:
    CORS(app, resources={r"/api/*": {"origins": ALLOWED_ORIGINS}}, methods=["GET", "POST"], max_age=600)

TMP = "/tmp/vidora"
os.makedirs(TMP, exist_ok=True)

HOSTS = {
    "tiktok": ["tiktok.com"],
    "instagram": ["instagram.com", "instagr.am"],
    "snapchat": ["snapchat.com"],
}
FORMATS = {
    "hd": ["bv*+ba/b", "b", "best"],
    "sd": ["b[height<=480]/w", "b", "best"],
}
MAX_BYTES = 200 * 1024 * 1024
MAX_TMP_BYTES = 1024 * 1024 * 1024
FILE_TTL = 15 * 60
RATE_LIMIT = 8          # داواکاری داگرتن لە هەر خولەکێکدا بۆ هەر IP
FILE_RATE_LIMIT = 30
hits, fhits = {}, {}
slots = threading.BoundedSemaphore(3)   # زۆرترین داگرتنی هاوکات
lock = threading.Lock()

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; "
       "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; manifest-src 'self'; "
       "worker-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


@app.after_request
def secure_headers(resp):
    resp.headers["Content-Security-Policy"] = CSP
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    resp.headers["Cross-Origin-Resource-Policy"] = "same-site" if ALLOWED_ORIGINS else "same-origin"
    if request.is_secure:
        resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.path.startswith("/api/") or request.path == "/health":
        resp.headers["Cache-Control"] = "no-store"
    return resp


@app.before_request
def origin_guard():
    """POSTی ئەو وێبسایتانە ڕەتدەکاتەوە کە ڕێگەپێدراو نین (CSRF/بەکارهێنانی API لە سایتی تر)."""
    if request.method == "POST":
        o = (request.headers.get("Origin") or "").rstrip("/")
        if o and o != request.host_url.rstrip("/") and o not in ALLOWED_ORIGINS:
            abort(403)


def rate(store, ip, limit):
    now = time.time()
    with lock:
        arr = [t for t in store.get(ip, []) if now - t < 60]
        arr.append(now)
        store[ip] = arr
    return len(arr) > limit


def host_ok(url, platform):
    if len(url) > 500:
        return False
    try:
        u = urlparse(url)
        h = (u.hostname or "").lower()
        if u.scheme not in ("http", "https") or u.username or u.password:
            return False
        if u.port not in (None, 80, 443):
            return False
    except Exception:
        return False
    return any(h == x or h.endswith("." + x) for x in HOSTS.get(platform, []))


def tmp_size():
    total = 0
    for f in os.listdir(TMP):
        try:
            total += os.path.getsize(os.path.join(TMP, f))
        except OSError:
            pass
    return total


def cleaner():
    while True:
        time.sleep(120)
        now = time.time()
        for f in os.listdir(TMP):
            p = os.path.join(TMP, f)
            try:
                if now - os.path.getmtime(p) > FILE_TTL:
                    os.remove(p)
            except OSError:
                pass
        with lock:   # بیرگەی IP ی کۆن پاک دەکاتەوە
            for store in (hits, fhits):
                for k in [k for k, v in store.items() if not v or now - v[-1] > 60]:
                    store.pop(k, None)


threading.Thread(target=cleaner, daemon=True).start()


def explain(err):
    s = str(err).lower()
    if any(k in s for k in ("login", "log in", "sign in", "cookies", "rate-limit", "rate limit", "empty media response")):
        return "ئەم پلاتفۆرمە داواکاری سێرڤەرەکەی ڕەتکردەوە (پێویستی بە لۆگین/کووکی هەیە). دواتر دووبارە هەوڵ بدەرەوە."
    if "private" in s or "not available" in s or "removed" in s or "unavailable" in s:
        return "ئەم ڤیدیۆیە تایبەتە یان سڕاوەتەوە. دڵنیابە گشتییە (Public)."
    if "unsupported url" in s:
        return "ئەم جۆرە لینکە پشتگیری ناکرێت. لینکی ڕاستەوخۆی ڤیدیۆکە بەکاربهێنە."
    if "max-filesize" in s or "larger than" in s:
        return "ڤیدیۆکە زۆر گەورەیە."
    if "timed out" in s or "timeout" in s:
        return "سێرڤەر کاتی تەواو بوو. دووبارە هەوڵ بدەرەوە."
    return "نەتوانرا ڤیدیۆکە دابەزێنرێت. دڵنیابە لینکەکە گشتییە (Public) و دووبارە هەوڵ بدەرەوە."


def build_opts(vid, fmt, platform):
    opts = {
        "format": fmt,
        "merge_output_format": "mp4",
        "outtmpl": os.path.join(TMP, vid + ".%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "max_filesize": MAX_BYTES,
        "socket_timeout": 20,
        "retries": 3,
        "allowed_extractors": ["(?i)(vm\\.)?tiktok.*", "(?i)instagram.*", "(?i)snapchat.*"],  # extractor ی گشتی (Generic) قەدەغەیە
        "enable_file_urls": False,
    }
    if CAN_IMPERSONATE and platform in ("tiktok", "instagram"):
        opts["impersonate"] = ImpersonateTarget("chrome")
    if COOKIES_FILE and os.path.exists(COOKIES_FILE):
        opts["cookiefile"] = COOKIES_FILE
    return opts


def find_file(vid):
    for f in os.listdir(TMP):
        if f.startswith(vid) and not f.endswith((".part", ".ytdl", ".temp")):
            return os.path.join(TMP, f)
    return None


def clean_title(t):
    return re.sub(r"[^\w\- ]+", "", t or "")[:50].strip() or "vidora"


@app.post("/api/download")
def download():
    ip = request.remote_addr or "?"
    if rate(hits, ip, RATE_LIMIT):
        return jsonify(error="داواکاری زۆرە، کەمێک چاوەڕێ بکە و دووبارە هەوڵ بدەرەوە."), 429

    d = request.get_json(silent=True)
    if not isinstance(d, dict):
        return jsonify(error="داواکارییەکە دروست نییە."), 400
    url = str(d.get("url") or "").strip()
    platform = str(d.get("platform") or "")
    quality = str(d.get("quality") or "hd")
    if quality not in FORMATS:
        quality = "hd"

    if not url or not host_ok(url, platform):
        return jsonify(error="لینکەکە دروست نییە یان لەگەڵ پلاتفۆرمەکە ناگونجێت."), 400

    if tmp_size() > MAX_TMP_BYTES or not slots.acquire(blocking=False):
        return jsonify(error="سێرڤەر خەریکە، دووبارە هەوڵ بدەرەوە."), 503

    try:
        vid = uuid.uuid4().hex
        info, path, last_err = None, None, None
        for fmt in FORMATS[quality]:
            try:
                with yt_dlp.YoutubeDL(build_opts(vid, fmt, platform)) as ydl:
                    info = ydl.extract_info(url, download=True)
                path = find_file(vid)
                if path:
                    break
                last_err = RuntimeError("no file produced")
            except Exception as e:
                last_err = e
                app.logger.warning("download failed (%s): %s", fmt, e)
                if "format" not in str(e).lower():
                    break
    finally:
        slots.release()

    if not path:
        body = {"error": explain(last_err)}
        if SHOW_DETAIL:
            body["detail"] = str(last_err)[-300:]
        return jsonify(body), 422

    title = clean_title((info or {}).get("title"))
    return jsonify(download_url=f"/api/file/{os.path.basename(path)}?name={quote(title)}")


@app.get("/api/file/<name>")
def file(name):
    if rate(fhits, request.remote_addr or "?", FILE_RATE_LIMIT):
        abort(429)
    if not re.fullmatch(r"[0-9a-f]{32}\.[A-Za-z0-9]{2,5}", name):
        abort(404)
    p = os.path.join(TMP, name)
    if not os.path.isfile(p):
        abort(404)
    ext = os.path.splitext(name)[1]
    return send_file(p, as_attachment=True, download_name=f"{clean_title(request.args.get('name'))}{ext}")


@app.get("/")
def home():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/health")
def health():
    body = {"ok": True}
    if SHOW_DETAIL:
        body.update(impersonate=CAN_IMPERSONATE, yt_dlp=yt_dlp.version.__version__)
    return jsonify(body)


# ───────── لاپەڕەکانی سایت (ڕیکلام، یاساییەکان، 404) ─────────
def contact_html():
    parts = []
    if re.fullmatch(r"[^@\s<>\"']+@[^@\s<>\"']+\.[A-Za-z]{2,}", CONTACT_EMAIL):
        e = html.escape(CONTACT_EMAIL)
        parts.append(f'<a class="cta" href="mailto:{e}">{e}</a>')
    if re.fullmatch(r"\d{6,15}", CONTACT_WHATSAPP):
        parts.append(f'<a class="cta alt" href="https://wa.me/{CONTACT_WHATSAPP}" target="_blank" rel="noopener noreferrer">WhatsApp</a>')
    if re.fullmatch(r"[A-Za-z0-9_]{5,32}", CONTACT_TELEGRAM):
        parts.append(f'<a class="cta alt" href="https://t.me/{CONTACT_TELEGRAM}" target="_blank" rel="noopener noreferrer">Telegram</a>')
    if not parts:
        return '    <p class="mut">شێوازی پەیوەندی هێشتا دیاری نەکراوە.</p>'
    return '    <div class="cta-row">' + "".join(parts) + "</div>"


def render_page(name, status=200):
    with open(os.path.join(PAGES_DIR, name), encoding="utf-8") as f:
        body = f.read().replace("{{CONTACT}}", contact_html())
    return Response(body, status=status, mimetype="text/html")


def _add_page(slug, filename):
    app.add_url_rule(f"/{slug}", endpoint=f"page_{slug}", view_func=lambda: render_page(filename))


for _slug in ("advertise", "privacy", "terms", "copyright"):
    _add_page(_slug, f"{_slug}.html")


@app.errorhandler(404)
def not_found(_e):
    if request.path.startswith("/api/"):
        return jsonify(error="نەدۆزرایەوە."), 404
    return render_page("404.html", 404)


@app.get("/robots.txt")
def robots():
    base = request.host_url.rstrip("/")
    return Response(f"User-agent: *\nAllow: /\nDisallow: /api/\nSitemap: {base}/sitemap.xml\n", mimetype="text/plain")


@app.get("/sitemap.xml")
def sitemap():
    base = request.host_url.rstrip("/")
    urls = "".join(f"<url><loc>{base}{p}</loc></url>" for p in ("/", "/advertise", "/privacy", "/terms", "/copyright"))
    return Response('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + urls + "</urlset>", mimetype="application/xml")
