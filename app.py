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


def pick(info, mode):
    fmts = info.get("formats") or []
    out = []
    if mode == "audio":
        a = [f for f in fmts if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none")]
        if a:
            out.append(("Audio (M4A)", a[-1]["url"], "m4a"))
    elif mode == "photo":
        if info.get("thumbnail"):
            out.append(("Photo (JPG)", info["thumbnail"], "jpg"))
    else:
        v = [f for f in fmts if f.get("vcodec") not in (None, "none") and f.get("acodec") not in (None, "none")]
        v.sort(key=lambda f: f.get("height") or 0, reverse=True)
        for f in v[:2]:
            h = f.get("height")
            out.append((f"MP4 {h}p" if h else "MP4", f["url"], "mp4"))
        if not out and info.get("url"):
            out.append(("MP4", info["url"], "mp4"))
    return out


@app.post("/api/download")
def download():
    data = request.get_json(silent=True) or {}
    url, mode = data.get("url", ""), data.get("mode", "video")
    if not IG.match(url):
        return jsonify(error="invalid link"), 400
    try:
        with yt_dlp.YoutubeDL({"quiet": True, "skip_download": True, "noplaylist": True}) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:
        return jsonify(error="not found"), 404
    items = pick(info, mode)
    if not items:
        return jsonify(error="nothing to download"), 404
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
