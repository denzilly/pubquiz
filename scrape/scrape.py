"""Archive the r/KerigorricalQuiz pub quizzes for local, offline play.

Each quiz is a Reddit post linking an Imgur album of slide images; the answers
live in a second Imgur album linked from the author's own comment on the post.
Nothing is OCR'd - the slides are kept as images and played as a slideshow.

Stages (each is resumable; rerunning skips work already done):
  discover  paginate the subreddit's Atom feed  -> data/posts.json
  resolve   read each post's comments for album -> data/posts.json (enriched)
  download  pull album images from Imgur        -> data/quizzes/<slug>/...
  index     build the manifest the web app uses -> data/index.json
"""
import argparse
import html
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from net import Limiter, get, get_json  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
QUIZ_DIR = os.path.join(DATA, "quizzes")
POSTS = os.path.join(DATA, "posts.json")
INDEX = os.path.join(DATA, "index.json")

SUB = "https://www.reddit.com/r/KerigorricalQuiz"
NS = {"a": "http://www.w3.org/2005/Atom"}
# Imgur's own public web client id - the same one imgur.com uses in-browser.
IMGUR_CLIENT = "546c25a59c58ad7"

reddit = Limiter(delay=20.0, min_delay=8.0)
imgur = Limiter(delay=1.5, min_delay=0.8)

ALBUM_RE = re.compile(r"https?://imgur\.com/(?:a|gallery)/(?:[\w-]*-)?(\w+)", re.I)
ANSWER_RE = re.compile(r"answers?\s*[:\-]?\s*$", re.I)


def load(path, default):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return default


def save(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def album_id(url):
    m = ALBUM_RE.search(url or "")
    return m.group(1) if m else None


def parse_entries(xml_text):
    root = ET.fromstring(xml_text)
    out = []
    for e in root.findall("a:entry", NS):
        link = e.find("a:link", NS)
        out.append({
            "id": (e.findtext("a:id", "", NS) or "").replace("t3_", ""),
            "title": html.unescape(e.findtext("a:title", "", NS) or ""),
            "permalink": link.get("href") if link is not None else "",
            "date": e.findtext("a:updated", "", NS) or "",
            "content": html.unescape(e.findtext("a:content", "", NS) or ""),
            "author": e.findtext("a:author/a:name", "", NS) or "",
        })
    return out


def outbound_link(content):
    """The [link] anchor in a listing entry - where the post points."""
    for m in re.finditer(r'<a href="([^"]+)"[^>]*>\s*\[link\]\s*</a>', content):
        return m.group(1)
    return None


# ---------------------------------------------------------------- discover
def discover(max_pages=12):
    posts = {p["id"]: p for p in load(POSTS, [])}
    after = None
    for page in range(max_pages):
        url = SUB + "/new/.rss?limit=100"
        if after:
            url += "&count=%d&after=t3_%s" % (page * 100, after)
        print("[discover] page %d (after=%s)" % (page + 1, after))
        xml_text = get(url, reddit)
        if not xml_text:
            print("  no data; stopping")
            break
        try:
            entries = parse_entries(xml_text)
        except ET.ParseError as e:
            print("  bad XML (%s); stopping" % e)
            break
        if not entries:
            print("  empty page; done")
            break
        fresh = 0
        for e in entries:
            if e["id"] not in posts:
                fresh += 1
            rec = posts.setdefault(e["id"], {"id": e["id"]})
            rec.update({
                "title": e["title"],
                "permalink": e["permalink"],
                "date": e["date"],
                "author": e["author"],
                "link": outbound_link(e["content"]),
            })
        print("  %d entries (%d new); total %d" % (len(entries), fresh, len(posts)))
        after = entries[-1]["id"]
        save(POSTS, sorted(posts.values(), key=lambda p: p["date"], reverse=True))
        if len(entries) < 100:
            print("  short page; reached the end")
            break
    return list(posts.values())


# ----------------------------------------------------------------- resolve
def resolve(force=False, limit=None, retry_empty=False):
    """Find each post's question album and answer album.

    The question album is usually the post's own outbound link. The answers are
    linked from a comment by the quiz author, labelled 'Answers:'.
    """
    posts = load(POSTS, [])
    if retry_empty:
        # Posts that look like quizzes but resolved to nothing - usually a
        # request that failed on an earlier, heavily throttled run.
        todo = [p for p in posts
                if not p.get("questions_album")
                and re.match(r"\s*quiz\s*[0-9]", p.get("title", ""), re.I)]
    else:
        todo = [p for p in posts if force or "answers_album" not in p]
    if limit:
        todo = todo[:limit]
    print("[resolve] %d of %d posts need resolving" % (len(todo), len(posts)))
    for i, p in enumerate(todo, 1):
        print("[resolve] %d/%d %s" % (i, len(todo), p.get("title", "")[:55]))
        xml_text = get(SUB + "/comments/%s/.rss?limit=100" % p["id"], reddit)
        if xml_text is None:
            # Never reached Reddit. Leave the post unresolved so that a later
            # run retries it, rather than recording a false "no albums here".
            print("    unreachable; leaving for a later run")
            continue
        p["questions_album"] = album_id(p.get("link"))
        p["answers_album"] = None
        try:
            entries = parse_entries(xml_text)
        except ET.ParseError:
            entries = []
        author = entries[0]["author"] if entries else None
        for e in entries:
            # Only trust the quiz author's own comments.
            if author and e["author"] != author:
                continue
            for m in re.finditer(r'<a href="([^"]+)"', e["content"]):
                aid = album_id(m.group(1))
                if not aid:
                    continue
                before = re.sub(r"<[^>]+>", " ", e["content"][:m.start()])
                before = html.unescape(before).strip()
                if ANSWER_RE.search(before[-40:]):
                    p["answers_album"] = aid
                elif not p.get("questions_album"):
                    p["questions_album"] = aid
        save(POSTS, posts)
    return posts


# ---------------------------------------------------------------- download
def slugify(title, post_id):
    m = re.match(r"\s*quiz\s*([0-9]+(?:\.5)?)", title, re.I)
    if m:
        return "quiz-" + m.group(1).replace(".", "_")
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:48]
    return "%s-%s" % (base or "post", post_id)


def fetch_album(aid):
    url = ("https://api.imgur.com/post/v1/albums/%s"
           "?client_id=%s&include=media" % (aid, IMGUR_CLIENT))
    d = get_json(url, imgur, headers={"Authorization": "Client-ID " + IMGUR_CLIENT})
    if not d:
        return None
    media = d.get("media") or []
    # Imgur returns media in album order; keep that order verbatim.
    return {
        "title": d.get("title") or "",
        "images": [{"id": m["id"], "url": m.get("url"),
                    "w": m.get("width"), "h": m.get("height"),
                    "mime": m.get("mime_type", "image/png")}
                   for m in media if m.get("type") == "image"],
    }


EXT = {"image/png": ".png", "image/jpeg": ".jpg",
       "image/gif": ".gif", "image/webp": ".webp"}


def download_album(aid, dest):
    """Download an album into dest/. Returns the ordered file list."""
    os.makedirs(dest, exist_ok=True)
    meta_path = os.path.join(dest, "_album.json")
    album = load(meta_path, None)
    if not album:
        album = fetch_album(aid)
        if not album:
            return []
        save(meta_path, album)
    files = []
    for n, img in enumerate(album["images"]):
        name = "%03d%s" % (n, EXT.get(img["mime"], ".png"))
        path = os.path.join(dest, name)
        if not os.path.exists(path) or os.path.getsize(path) == 0:
            blob = get(img["url"], imgur, binary=True)
            if not blob:
                continue
            with open(path, "wb") as f:
                f.write(blob)
        files.append(name)
    return files


def download(only=None, limit=None):
    posts = load(POSTS, [])
    quizzes = [p for p in posts if p.get("questions_album")]
    quizzes.sort(key=lambda p: p.get("date", ""), reverse=True)
    if only:
        quizzes = [p for p in quizzes if only in slugify(p["title"], p["id"])]
    if limit:
        quizzes = quizzes[:limit]
    print("[download] %d quizzes" % len(quizzes))
    for i, p in enumerate(quizzes, 1):
        slug = slugify(p["title"], p["id"])
        base = os.path.join(QUIZ_DIR, slug)
        print("[download] %d/%d %s - %s" % (i, len(quizzes), slug, p["title"][:50]))
        q = download_album(p["questions_album"], os.path.join(base, "questions"))
        a = []
        if p.get("answers_album"):
            a = download_album(p["answers_album"], os.path.join(base, "answers"))
        print("    %d question slides, %d answer slides" % (len(q), len(a)))
        save(os.path.join(base, "meta.json"), {
            "slug": slug, "id": p["id"], "title": p["title"],
            "date": p.get("date"), "permalink": p.get("permalink"),
            "questions": q, "answers": a,
        })
    build_index()


# ------------------------------------------------------------------- index
def quiz_sort_key(meta):
    m = re.match(r"quiz-(\d+)(_5)?$", meta["slug"])
    if m:
        return (float(m.group(1)) + (0.5 if m.group(2) else 0), meta.get("date", ""))
    return (-1, meta.get("date", ""))


def build_index():
    items = []
    slugs = sorted(os.listdir(QUIZ_DIR)) if os.path.isdir(QUIZ_DIR) else []
    for slug in slugs:
        meta = load(os.path.join(QUIZ_DIR, slug, "meta.json"), None)
        if meta and meta.get("questions"):
            items.append(meta)
    items.sort(key=quiz_sort_key, reverse=True)
    save(INDEX, {"quizzes": items, "count": len(items)})
    print("[index] %d quizzes -> %s" % (len(items), INDEX))
    return items


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage", choices=["discover", "resolve", "download",
                                      "index", "all"])
    ap.add_argument("--limit", type=int, help="cap work (resolve/download)")
    ap.add_argument("--only", help="slug substring filter (download)")
    ap.add_argument("--pages", type=int, default=12, help="feed pages (discover)")
    ap.add_argument("--force", action="store_true", help="re-resolve everything")
    ap.add_argument("--retry-empty", action="store_true",
                    help="re-resolve only quiz posts that found no album")
    a = ap.parse_args()

    if a.stage in ("discover", "all"):
        discover(a.pages)
    if a.stage in ("resolve", "all"):
        resolve(a.force, a.limit, a.retry_empty)
    if a.stage in ("download", "all"):
        download(a.only, a.limit)
    if a.stage == "index":
        build_index()


if __name__ == "__main__":
    main()
