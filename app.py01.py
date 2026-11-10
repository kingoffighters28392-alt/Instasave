import os, re
from urllib.parse import urlparse, quote
import requests
import yt_dlp
from flask import Flask, request, jsonify, send_from_directory, Response, stream_with_context

app = Flask(__name__, static_folder=None)
HERE = os.path.dirname(os.path.abspath(__file__))
IG = re.compile(r"^https?://(www\.)?instagram\.com/(reels?|p|tv)/[\w-]+", re.I)
CDN = (".cdninstagram.com", ".fbcdn.net")


@app.get("/")
def index():
    return send_from_directory(HERE, "index.html")


def usable(f):
    return f.get("url") and f.get("protocol", "https") in ("http", "https")


def pick(info, mode):
    fmts = [f for f in (info.get("formats") or []) if usable(f)]
    for f in info.get("requested_formats") or []:
        if usable(f) and f not in fmts:
            fmts.append(f)
    has_v = lambda f: f.get("vcodec") != "none"
    has_a = lambda f: f.get("acodec") != "none"
    out = []
    if mode == "audio":
        a = [f for f in fmts if not has_v(f) and has_a(f)]
        if a:
            out.append(("Audio (M4A)", a[-1]["url"], "m4a"))
    elif mode == "photo":
        if info.get("thumbnail"):
            out.append(("Photo (JPG)", info["thumbnail"], "jpg"))
    else:
        v = [f for f in fmts if has_v(f) and has_a(f)]
        v.sort(key=lambda f: f.get("height") or 0, reverse=True)
        seen = set()
        for f in v:
            h = f.get("height")
            if h in seen:
                continue
            seen.add(h)
            out.append((f"MP4 {h}p" if h else "MP4", f["url"], "mp4"))
            if len(out) == 2:
                break
        if not out and info.get("url"):
            out.append(("MP4", info["url"], "mp4"))
    return out


@app.post("/api/download")
def download():
    data = request.get_json(silent=True) or {}
    url, mode = data.get("url", ""), data.get("mode", "video")
    if not IG.match(url):
        return jsonify(error="invalid link"), 400
    opts = {"quiet": True, "skip_download": True, "noplaylist": True}
    cookies = os.path.join(HERE, "cookies.txt")
    if os.path.exists(cookies):
        opts["cookiefile"] = cookies
    if os.environ.get("PROXY"):
        opts["proxy"] = os.environ["PROXY"]
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e))
        app.logger.error("extract failed: %s", msg)
        return jsonify(error=msg[:200]), 404
    items = pick(info, mode)
    if not items:
        seen = ", ".join(
            f"{f.get('format_id')}/{f.get('ext')}/{f.get('vcodec')}/{f.get('acodec')}/{f.get('protocol')}"
            for f in (info.get("formats") or [])
        )
        app.logger.error("no usable formats: %s", seen)
        return jsonify(error=("nothing to download | " + seen)[:300]), 404
    return jsonify(
        title=(info.get("title") or "Your download is ready")[:80],
        thumbnail=info.get("thumbnail"),
        downloads=[
            {"label": label, "url": f"/api/file?u={quote(u, safe='')}&n=instasave.{ext}"}
            for label, u, ext in items
        ],
    )


@app.get("/api/file")
def file():
    u = request.args.get("u", "")
    p = urlparse(u)
    if p.scheme != "https" or not p.hostname or not p.hostname.endswith(CDN):
        return "bad link", 400
    name = re.sub(r"[^\w.-]", "", request.args.get("n", "instasave"))
    r = requests.get(u, stream=True, timeout=20, allow_redirects=False)
    headers = {
        "Content-Disposition": f'attachment; filename="{name}"',
        "Content-Type": r.headers.get("Content-Type", "application/octet-stream"),
    }
    return Response(stream_with_context(r.iter_content(65536)), headers=headers)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
