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

from . import cache
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
        timespec="seconds"), "text": to_text(body), "title": title_of(body),
        "links": links_in(body, url), "tables": tables_in(body)}
    cache.write_json(path, doc)
    return doc


def tables(url: str, ttl: float = CACHE_TTL_S, force: bool = False) -> list:
    """The page's tables, refetching once if the cache predates this field.

    `fetch` gained "tables" on 18 September 2026 and every document cached
    before then lacks it. Absent and empty are different -- one is "this page
    has no tables", the other is "nobody looked" -- and a caller that cannot
    tell them apart reads the limits page as a page with no limits on it. So
    a cached doc with no `tables` key is refetched rather than believed.
    """
    doc = fetch(url, ttl=ttl, force=force)
    if "tables" not in doc:
        doc = fetch(url, ttl=ttl, force=True)
    return doc.get("tables") or []


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


class _Tables(HTMLParser):
    """Every <table> as a rectangular grid of cell text.

    `to_text` is the wrong tool for a table and the RIDEM limits page is why.
    It joins a row's cells with nothing between them, so the only reason
    "American Eel" and '9"' come out on separate lines at all is that RI's
    Drupal theme wraps every cell in a <p>, which IS in BLOCK. That is a
    theming detail, not a contract -- a site redesign that drops the <p>
    silently collapses a whole row onto one line, and a parser reading the
    flattened text would go from right to confidently wrong with no error.

    Worse, it is already ambiguous. A cell can hold several lines --

        <td><p>Closed 9/1 - 12/31<br>for any gear other than<br>
               baited pots or spears</p></td>

    -- and flattened, those three lines are indistinguishable from three
    separate cells. Reading a size limit out of that is exactly the kind of
    guess this project refuses to make.

    So cells are kept as cells and the lines inside one are kept as a list.
    colspan and rowspan are expanded rather than recorded, because the point
    of the grid is that column *index* means something: the commercial table
    spans its size and limit columns across two cells each for layout, and
    without expansion "limit" is column 3 in one row and column 5 in another.
    A spanned cell repeats its content into every slot it covers, which is
    what it visually means.
    """

    CELL = {"td", "th"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[list[str]]]] = []
        self._rows: list | None = None
        self._row: list | None = None
        self._cell: list[str] | None = None
        self._span = 1
        self._rowspan = 1
        # Rowspans owed to LATER rows: column index -> (lines, rows to fill).
        # `_pending` is what the row being read has just declared and `_carry`
        # is what earlier rows declared, and they have to stay apart: merged,
        # a rowspan=2 header filled its own row a second time, so table 2 came
        # out as Species, Minimum size, Season, Species, Minimum size, Season.
        # A cell spans DOWN from the row it is written in, never sideways
        # within it.
        self._carry: dict[int, tuple[list[str], int]] = {}
        self._pending: dict[int, tuple[list[str], int]] = {}
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "table":
            # Nested tables are used for layout and would interleave rows into
            # the parent. Only the outermost is taken; the inner one's text
            # still lands in whatever cell contains it.
            self._depth += 1
            if self._depth == 1:
                self._rows, self._carry, self._pending = [], {}, {}
        elif tag == "tr" and self._depth == 1:
            self._flush_row()
            self._row = []
        elif tag in self.CELL and self._depth == 1 and self._row is not None:
            self._close_cell()
            self._cell = []
            self._span = max(1, min(20, _int(a.get("colspan"), 1)))
            self._rowspan = max(1, min(50, _int(a.get("rowspan"), 1)))
        elif tag == "br" and self._cell is not None:
            self._cell.append("")

    def handle_endtag(self, tag):
        if tag in self.CELL and self._depth == 1:
            self._close_cell()
        elif tag == "tr" and self._depth == 1:
            self._flush_row()
        elif tag == "table":
            if self._depth == 1:
                self._flush_row()
                if self._rows:
                    self.tables.append(self._rows)
                self._rows = None
            self._depth = max(0, self._depth - 1)

    def handle_data(self, data):
        if self._cell is None or not data.strip():
            return
        if not self._cell:
            self._cell.append("")
        self._cell[-1] = (self._cell[-1] + " " + data.strip()).strip()

    def _close_cell(self):
        if self._cell is None or self._row is None:
            return
        lines = [ln for ln in (s.strip() for s in self._cell) if ln]
        for _ in range(self._span):
            self._row.append(lines)
            if self._rowspan > 1:
                self._pending[len(self._row) - 1] = (lines, self._rowspan - 1)
        self._cell = None
        self._span = self._rowspan = 1

    def _flush_row(self):
        if self._row is None:
            return
        self._close_cell()
        # A cell spanning down from an earlier row occupies its column before
        # this row's own cells are placed, the same way a browser lays it out.
        if self._carry:
            out, own = [], list(self._row)
            for i in range(max(self._carry) + 1 + len(own)):
                if i in self._carry:
                    lines, left = self._carry[i]
                    out.append(lines)
                    if left > 1:
                        self._carry[i] = (lines, left - 1)
                    else:
                        del self._carry[i]
                elif own:
                    out.append(own.pop(0))
            out.extend(own)
            self._row = out
        if any(c for c in self._row):
            self._rows.append(self._row)
        self._row = None
        # Only now do this row's own spans start owing anything to the next.
        self._carry.update(self._pending)
        self._pending = {}


def _int(v, default: int) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def tables_in(markup: str) -> list[list[list[list[str]]]]:
    """Tables -> rows -> cells -> the lines inside one cell."""
    p = _Tables()
    try:
        p.feed(markup)
    except Exception:                                             # noqa: BLE001
        pass
    p._flush_row()
    if p._rows:
        p.tables.append(p._rows)
    return [[[[html.unescape(ln) for ln in cell] for cell in row]
             for row in tbl] for tbl in p.tables]


class _Links(HTMLParser):
    """Every href on the page, in document order.

    Deliberately not filtered the way `to_text` filters: `to_text` drops nav,
    and on an index page the link you want is often in it.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        for k, v in attrs:
            if k == "href" and v:
                self.hrefs.append(v)
                break


def links_in(markup: str, base: str) -> list[str]:
    """Absolute links from a page, in document order, without duplicates."""
    p = _Links()
    try:
        p.feed(markup)
    except Exception:                                             # noqa: BLE001
        pass
    out, seen = [], set()
    for h in p.hrefs:
        u = urllib.parse.urljoin(base, h.strip())
        if u.startswith(("http://", "https://")) and u not in seen:
            seen.add(u)
            out.append(u)
    return out


def article_url(src: dict, force: bool = False) -> str:
    """The page actually worth reading for a source.

    Most sources are the article. On The Water is an index: its RI page lists
    the week's report and links to it, and the index itself carries a headline
    and a one-line teaser. Reading the index got a table of contents -- region
    names and the other states' headlines -- which is why that source reported
    "0 bait, 0 catch" every week for a month while succeeding. See the note in
    SOURCES.

    Raises rather than falling back to the index, because falling back is what
    it was already doing and the whole problem was that it looked fine.
    """
    pattern = src.get("article")
    if not pattern:
        return src["url"]
    doc = fetch(src["url"], force=force)
    if "links" not in doc:
        # Cached before links were kept. One refetch, then it is there.
        doc = fetch(src["url"], force=True)
    for link in doc.get("links", []):
        if re.search(pattern, link):
            return link
    raise FetchError(
        "no article matching %s on %s -- the index changed shape, or this "
        "week's report is not up yet" % (pattern, src["url"]))


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
        # The region index, and `article` is how the week's report is found
        # from it. The URL here used to be /fishing-reports, which is the
        # national index: every other state's headline and not a word of
        # Rhode Island. The model was handed a table of contents and
        # correctly found nothing in it, so this source reported "0 bait,
        # 0 catch" and ok=True every Thursday from mid-August. Measured 18
        # September 2026: the national index renders 2,319 characters of
        # navigation, the region index 1,782 (a headline and one teaser
        # line), and the report itself 9,116.
        "url": "https://onthewater.com/regions/rhode-island/",
        "article": r"^https://onthewater\.com/fishing-reports/\d{4}/\d{2}/"
                   r"rhode-island-fishing-report-",
        "kind": "report",
        "note": "Editorial fishing reports. Extract facts only — never store prose. "
                "Relays Ocean State Tackle (Providence) and The Saltwater Edge "
                "(Middletown), so it is several witnesses, not one.",
    },
    "fisherman_ri": {
        "url": "https://www.thefisherman.com/area/rhode-island/",
        "kind": "report",
        "note": "The Fisherman, RI area page. Relays Snug Harbor Marina and Watch "
                "Hill Outfitters — expect overlap with On The Water on the same "
                "shops, which is exactly why witnesses are keyed on the shop.",
    },
    "coastal_angler_ri": {
        "url": "https://coastalanglermag.com/rhodeisland/report/",
        "kind": "report",
        "note": "Coastal Angler weekly RI column (Zach Harvey). Independent byline; "
                "Block Island and south shore heavy.",
    },
    "risaa": {
        "url": "https://www.risaa.org/",
        "kind": "report",
        "note": "RI Saltwater Anglers Association. Member reports rather than a "
                "trade column — a genuinely different observer pool from the "
                "tackle-shop circuit the magazines all phone.",
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
