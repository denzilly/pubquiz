"""Polite HTTP helpers: Reddit throttles hard from most IPs, so every reddit
request goes through an adaptive limiter that backs off on 429 and stays
backed off until requests start succeeding again."""
import gzip
import io
import json
import random
import time
import urllib.error
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")


class Limiter:
    """One limiter per host. `delay` grows on 429 and decays on success."""

    def __init__(self, delay, min_delay=None, max_delay=600.0):
        self.delay = delay
        self.min_delay = min_delay if min_delay is not None else delay
        self.max_delay = max_delay
        self._last = 0.0

    def wait(self):
        gap = time.time() - self._last
        if gap < self.delay:
            time.sleep(self.delay - gap + random.uniform(0, 0.4))
        self._last = time.time()

    def penalise(self):
        self.delay = min(self.delay * 2, self.max_delay)

    def reward(self):
        self.delay = max(self.delay * 0.9, self.min_delay)


def get(url, limiter, headers=None, tries=6, binary=False):
    """GET with retries. Returns bytes (binary) or str, or None if it never
    succeeded. 404/403 are treated as permanent and return None immediately."""
    hdrs = {"User-Agent": UA, "Accept-Encoding": "gzip"}
    if headers:
        hdrs.update(headers)
    for attempt in range(tries):
        limiter.wait()
        req = urllib.request.Request(url, headers=hdrs)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
            limiter.reward()
            return raw if binary else raw.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                limiter.penalise()
                print(f"    {e.code} throttled; delay now {limiter.delay:.0f}s")
                continue
            if e.code in (403, 404, 410):
                print(f"    {e.code} on {url} - skipping")
                return None
            limiter.penalise()
        except Exception as e:
            print(f"    {type(e).__name__}: {e}")
            time.sleep(2 ** attempt)
    print(f"    GAVE UP: {url}")
    return None


def get_json(url, limiter, headers=None):
    txt = get(url, limiter, headers=headers)
    if txt is None:
        return None
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        return None
