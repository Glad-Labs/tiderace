"""Polite fetching. Stdlib only.

Named `fetch` rather than `web` because `tiderace/web/` holds the map UI's
static assets, and a module sharing its name with a package directory resolves
by precedence rules rather than by intent.

Two sources with very different footing, and the difference drives the design:

  * **RIDEM** (dem.ri.gov) is a state agency. Its regulatory notices are public
    records, robots.txt permits the paths we want, and this is the source that
    feeds the volatile half of the commercial rules -- the quota closures that
    move on days of notice.
  * **Fishing reports** are copyrighted editorial writing. Their robots.txt may
    permit crawling, but that is not a licence to their prose. So we extract
    *facts* -- species, date, area, bait -- and never store or republish the
    text. Facts are not copyrightable; paragraphs are.

Everything here is deliberately slow and cached. A hobby forecast has no
business hammering a state web server, and being a good citizen costs nothing
when the data changes weekly.
"""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime
from html.parser import HTMLParser

UA = ("tiderace/0.1 (open-source personal fishing forecast; "
      "+https://github.com/Glad-Labs/tiderace)")

CACHE_DIR = os.environ.get(
    "TIDERACE_WEB_CACHE",
    os.path.join(os.path.dirname(__file__), "..", ".cache", "web"))

MIN_INTERVAL_S = 3.0          # per host, between requests
CACHE_TTL_S = 6 * 3600
TIMEOUT_S = 30

_last_hit: dict[str, float] = {}
_robots: dict[str, urllib.robotparser.RobotFileParser] = {}


class FetchError(RuntimeError):
    pass


class BlockedByRobots(FetchError):
    pass


# ------------------------------------------------------------------- robots

def _robots_for(url: str) -> urllib.robotparser.RobotFileParser:
    parts = urllib.parse.urlparse(url)
    root = f"{parts.scheme}://{parts.netloc}"
    if root in _robots:
        return _robots[root]

    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(root + "/robots.txt")
    try:
        req = urllib.request.Request(root + "/robots.txt", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            rp.parse(r.read().decode("utf-8", "replace").splitlines())
    except Exception:                                             # noqa: BLE001
        # A missing or unreachable robots.txt is not permission to ignore it,
        # but it is also not a prohibition. Default to allowing, which is what
        # the standard says, and keep the rate limit either way.
        rp.parse(["User-agent: *", "Allow: /"])
    _robots[root] = rp
    return rp


def allowed(url: str) -> bool:
    try:
        return _robots_for(url).can_fetch(UA, url)
    except Exception:                                             # noqa: BLE001
        return True


def crawl_delay(url: str) -> float:
    try:
        d = _robots_for(url).crawl_delay(UA)
        return max(float(d), MIN_INTERVAL_S) if d else MIN_INTERVAL_S
    except Exception:                                             # noqa: BLE001
        return MIN_INTERVAL_S


# -------------------------------------------------------------------- fetch

def _cache_path(url: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, hashlib.sha256(url.encode()).hexdigest()[:24] + ".json")


def fetch(url: str, ttl: float = CACHE_TTL_S, force: bool = False) -> dict:
    """Fetch a page, honouring robots.txt and a per-host rate limit."""
    path = _cache_path(url)
    if not force and os.path.exists(path) and time.time() - os.path.getmtime(path) < ttl:
        with open(path) as fh:
            return json.load(fh)

    if not allowed(url):
        raise BlockedByRobots(f"robots.txt disallows {url}")

    host = urllib.parse.urlparse(url).netloc
    wait = crawl_delay(url) - (time.time() - _last_hit.get(host, 0))
    if wait > 0:
        time.sleep(wait)

    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            raw = r.read()
            charset = r.headers.get_content_charset() or "utf-8"
            body = raw.decode(charset, "replace")
            status = r.status
    except urllib.error.HTTPError as e:
        raise FetchError(f"{e.code} from {url}") from e
    except Exception as e:                                        # noqa: BLE001
        raise FetchError(f"{type(e).__name__} for {url}: {e}") from e
    finally:
        _last_hit[host] = time.time()

    doc = {"url": url, "status": status, "fetched_at": datetime.now().isoformat(
        timespec="seconds"), "text": to_text(body), "title": title_of(body)}
    with open(path, "w") as fh:
        json.dump(doc, fh)
    return doc


# ------------------------------------------------------------- html -> text

class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head", "nav", "footer", "form"}
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
             "section", "article", "table", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(data.strip())


def to_text(markup: str) -> str:
    p = _Text()
    try:
        p.feed(markup)
    except Exception:                                             # noqa: BLE001
        pass
    text = " ".join(p.parts)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\s*\n\s*", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def title_of(markup: str) -> str:
    m = re.search(r"<title[^>]*>(.*?)</title>", markup, re.I | re.S)
    return html.unescape(m.group(1)).strip() if m else ""


# ------------------------------------------------------------------ sources

SOURCES = {
    "ridem_amendments": {
        "url": "https://dem.ri.gov/programs/marine-fisheries/fishamnd.php",
        "kind": "regulation",
        "note": "In-season quota notices and rule amendments. The volatile half "
                "of the commercial rules lives here.",
    },
    "ridem_limits": {
        "url": ("https://dem.ri.gov/natural-resources-bureau/marine-fisheries/"
                "marine-fisheries-minimum-sizes-possession-limits"),
        "kind": "regulation",
        "note": "Minimum sizes and possession limits, recreational and commercial.",
    },
    "eastbay_report": {
        "url": "https://www.eastbayri.com/fishing/",
        "kind": "report",
        "note": "East Bay RI weekly column. Local, bay-focused. Facts only.",
    },
    "hooked_ri": {
        "url": "https://hookedfisherman.com/reports/ri",
        "kind": "report",
        "note": "Aggregated RI reports. Facts only.",
    },
    "otw_ri_report": {
        "url": "https://onthewater.com/fishing-reports",
        "kind": "report",
        "note": "Editorial fishing reports. Extract facts only — never store prose.",
    },
}


def check_sources() -> list[dict]:
    """Report robots status and reachability for every configured source."""
    out = []
    for key, src in SOURCES.items():
        row = {"key": key, "url": src["url"], "kind": src["kind"]}
        try:
            row["robots_allowed"] = allowed(src["url"])
            row["crawl_delay_s"] = crawl_delay(src["url"])
        except Exception as e:                                    # noqa: BLE001
            row["robots_allowed"] = None
            row["error"] = str(e)
        out.append(row)
    return out
