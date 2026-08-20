"""Serve the local quiz archive and keep the scoreboard.

Static files come from web/ and data/; scores are appended to data/scores.json.
Stdlib only - run it with `python server.py` and open the printed URL.

The server is unauthenticated: anyone who can reach it can read the archive and
post a score. That is deliberate for a site shared with friends, but it means
the scoreboard is only as trustworthy as the people who know the URL.
"""
import argparse
import json
import os
import posixpath
import re
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.join(ROOT, "web")
DATA = os.path.join(ROOT, "data")
SCORES = os.path.join(DATA, "scores.json")

_lock = threading.Lock()

TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


def read_scores():
    if not os.path.exists(SCORES):
        return []
    try:
        with open(SCORES, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def write_scores(rows):
    os.makedirs(DATA, exist_ok=True)
    tmp = SCORES + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=1, ensure_ascii=False)
    os.replace(tmp, SCORES)


def safe_path(base, url_path):
    """Resolve url_path under base, refusing anything that escapes it."""
    rel = urllib.parse.unquote(url_path).lstrip("/")
    rel = posixpath.normpath(rel)
    if rel.startswith("..") or os.path.isabs(rel):
        return None
    full = os.path.join(base, *rel.split("/"))
    if os.path.commonpath([os.path.abspath(full), base]) != base:
        return None
    return full


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # keep the console clean; errors still surface below

    # ---------------------------------------------------------------- utils
    def send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, path, cacheable=False):
        if not path or not os.path.isfile(path):
            return self.send_json({"error": "not found"}, 404)
        ext = os.path.splitext(path)[1].lower()
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            return self.send_json({"error": "unreadable"}, 500)
        self.send_response(200)
        self.send_header("Content-Type", TYPES.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        # Slide images never change once downloaded; the app shell should not
        # be cached or edits would not show up on reload.
        self.send_header("Cache-Control",
                         "public, max-age=31536000" if cacheable else "no-store")
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------------ GET
    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        path = url.path

        # Container healthcheck target; returns nothing but liveness.
        if path == "/healthz":
            return self.send_json({"ok": True})

        if path == "/api/scores":
            q = urllib.parse.parse_qs(url.query).get("quiz", [None])[0]
            rows = read_scores()
            if q:
                rows = [r for r in rows if r.get("quiz") == q]
            rows.sort(key=lambda r: (-r.get("score", 0), r.get("ts", "")))
            return self.send_json(rows)

        if path.startswith("/data/"):
            return self.send_file(safe_path(DATA, path[len("/data/"):]),
                                  cacheable=True)

        if path in ("/", "/index.html"):
            return self.send_file(os.path.join(WEB, "index.html"))

        target = safe_path(WEB, path)
        if target and os.path.isfile(target):
            return self.send_file(target)
        # Unknown path: fall back to the app shell so deep links work.
        return self.send_file(os.path.join(WEB, "index.html"))

    # ----------------------------------------------------------------- POST
    def do_POST(self):
        if urllib.parse.urlparse(self.path).path != "/api/scores":
            return self.send_json({"error": "not found"}, 404)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > 64_000:
                raise ValueError("bad length")
            payload = json.loads(self.rfile.read(n).decode("utf-8"))
        except (ValueError, json.JSONDecodeError):
            return self.send_json({"error": "bad request"}, 400)

        name = str(payload.get("name", "")).strip()[:40]
        quiz = str(payload.get("quiz", "")).strip()
        if not name or not re.fullmatch(r"[\w.\-]{1,80}", quiz or ""):
            return self.send_json({"error": "name and quiz are required"}, 400)
        try:
            score = float(payload.get("score", 0))
            maximum = float(payload.get("max", 0))
        except (TypeError, ValueError):
            return self.send_json({"error": "score must be a number"}, 400)

        row = {
            "quiz": quiz,
            "quiz_title": str(payload.get("quiz_title", ""))[:200],
            "name": name,
            "score": round(score, 2),
            "max": round(maximum, 2),
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        with _lock:
            rows = read_scores()
            rows.append(row)
            write_scores(rows)
        return self.send_json(row, 201)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print("Pub quiz server running at http://%s:%d/  (Ctrl+C to stop)"
          % (a.host, a.port))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")


if __name__ == "__main__":
    main()
