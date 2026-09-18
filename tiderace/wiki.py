"""What is known about each fish as an animal, read off Wikipedia.

Matt, 17 September 2026: "I would also like to get as much info as we can for
each species on the app, I'm sure even wikipedia has the info we need." He is
right, and the reason this module can exist at all is that the thing it
fetches is a *different kind of claim* from everything else in the project.

`score.py` and `pelagic.py` hold bands that decide a forecast. `regs.py` holds
rules that decide whether a fish is a fine. Neither may come from here and
neither does. What this holds is natural history -- what the fish looks like,
where it lives, what it eats, when it spawns -- which is reference material
for a person holding one, and nothing computes on it. That separation is the
whole licence for reading a tertiary source, so it is enforced rather than
merely intended:

  * Nothing in this module is imported by `score`, `pelagic`, `prospect` or
    `regs`, and a test asserts that.
  * Sections about fishing are refused outright. This is not a hypothetical:
    the striped bass article carries a section headed "Current fishing
    regulations", and a size limit nobody read out of a RIDEM notice, sitting
    on the same card as the legal strip, is exactly the failure this project
    is built to avoid. `_wanted_section` is a default-deny allowlist and
    `_regulatory` is a second net over every surviving paragraph.
  * Every section carries the article, the revision number it was read at,
    and the date. A Wikipedia revision id is a permanent citable object, so
    "where did this sentence come from" has an answer that does not rot.

**The lookup is by binomial and by nothing else.** Wikipedia is a far better
encyclopaedia than it is a key-value store for common names, and searching it
by the name on a boat gets the wrong animal with a straight face. Measured on
2026-09-17, before `species.SCIENTIFIC` was completed:

    "False Albacore"  -> Euthynnus affinis     kawakawa, Indo-Pacific
    "grey trout"      -> Salvelinus namaycush  lake trout
    "sea mullet"      -> Mugil cephalus        flathead grey mullet
    "Weakfish"        -> Cynoscion             the genus, not a species

Three wrong fish and one genus, from names this project already had in its
own alias lists. It is the monkfish failure again -- `fishpic` records it --
and the answer is the same one: resolve through the binomial a document
printed, verify what you landed on, and record what the verification was.

The verification here is structured rather than textual: the article's
Wikidata item must carry P105 (taxon rank) = species and P225 (taxon name)
equal to the binomial we asked for. The genus case above fails that test
loudly, which is the behaviour to preserve.

Text is CC BY-SA 4.0 and the images are whatever Commons says they are, which
is not always free enough -- so the licence is read per file and the ones that
are not open are refused, exactly as `fishpic` refuses an all-rights-reserved
photograph. Nothing is committed: the cache lives in the gitignored
`data/species_wiki.json` and the images beside the iNaturalist ones.
"""

from __future__ import annotations

import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import cache

WP = "https://en.wikipedia.org/w/api.php"
WD = "https://www.wikidata.org/w/api.php"
UA = "tiderace/0.1 (+https://github.com/Glad-Labs/tiderace)"

CACHE = os.path.join(os.path.dirname(__file__), "..", "data",
                     "species_wiki.json")

LICENCE = "CC BY-SA 4.0"
LICENCE_URL = "https://creativecommons.org/licenses/by-sa/4.0/"

# Wikidata item ids. P105 is taxon rank and Q7432 is "species"; P225 is the
# taxon name. Together they are the difference between landing on a fish and
# landing on the genus it belongs to.
P_RANK, P_TAXON, Q_SPECIES = "P105", "P225", "Q7432"

# One request at a time, unhurried. The Wikimedia API asks for a descriptive
# User-Agent and serial requests rather than a rate limit in so many words.
PAUSE = 0.3

# Commons licence codes this app will keep a copy of. Public-domain NOAA and
# FAO plates are the best reference images there are for a fish, and they live
# under `pd`. Anything not matched here is refused and the card says so.
OPEN_PREFIXES = ("cc0", "cc-by", "pd", "publicdomain")


# ------------------------------------------------------------------ sections
#
# Default deny. A heading has to earn its way in on one of these words, and
# the deny list is checked FIRST so that "Commercial fishing, angling, and
# food quality" cannot get in on the word "quality" -- or, worse, so that
# "Current fishing regulations" cannot get in at all.
#
# The surveyed headings across all thirty-seven articles (2026-09-17) are what
# these two lists were built from, not a guess at what Wikipedia looks like:
# Description appears on 27 of them, Distribution and habitat on 10,
# Taxonomy on 10, Reproduction on 7, and Fisheries -- denied -- on 7.
DENY_WORDS = (
    "fishing", "fishery", "fisheries", "angling", "angler", "regulation",
    "management", "quota", "commercial", "recreational", "sport", "catch",
    "as food", "food", "cuisine", "culinary", "cooking", "aquaculture",
    "economic", "human", "culture", "market", "uses", "utilisation",
    "utilization", "reference", "external link", "see also",
    "further reading", "note", "bibliograph", "gallery", "citation",
)
ALLOW_WORDS = (
    "description", "appearance", "morpholog", "anatom", "identif",
    "similar", "characteristic", "about",
    "distribution", "habitat", "range", "biology", "ecolog", "diet",
    "feeding", "prey", "predator", "parasit", "reproduc", "spawn",
    "life cycle", "lifecycle", "life history", "breeding", "growth",
    "behavior", "behaviour", "habits", "migration", "physiolog", "sensory",
    "taxonom", "phylogen", "evolution", "etymolog", "nomenclature", "names",
    "conservation", "status", "threat",
)

# The second half of that list is not a guess at what Wikipedia calls things.
# The first pass ran against all thirty-seven articles and the refusals were
# read; these are the headings it was throwing away that a person holding a
# fish would want:
#
#   "Similar species"  spanish mackerel -- how to tell it from the next fish
#                      along, which is the single most useful thing a card
#                      can say and was being discarded
#   "About"            red hake -- its distribution, its 5-12 C preference
#                      and its spawning months; the article's only substantial
#                      section, leaving the card with 471 characters
#   "Characteristics"  menhaden        "Habits"      bonito
#   "Lifecycle"        blue marlin, which is "life cycle" with the space taken
#                      out and was missing the allowlist by one character
#   "Physiology",
#   "Threats"          bigeye          "Sensory"     blue shark
#   "Nomenclature"     mahi
#
# "about" is the loose one and it is safe only because deny is checked first:
# nothing in DENY_WORDS is a substring of it, and a section called "About the
# fishery" is refused on "fishery" before this list is consulted.

# The order a card reads in. What the fish looks like comes first because that
# is the question somebody with one in their hands is actually asking; the
# name story comes last because it is the only part that keeps until you are
# ashore. Anything allowed but unlisted keeps its article order, after these.
SECTION_ORDER = (
    "description", "appearance", "characteristic", "morpholog", "identif",
    "anatom", "similar", "about",
    "distribution", "habitat", "range", "diet", "feeding", "prey",
    "biology", "ecolog", "behavior", "behaviour", "habits", "migration",
    "physiolog", "sensory",
    "reproduc", "spawn", "breeding", "life cycle", "lifecycle",
    "life history", "growth",
    "predator", "parasit", "threat", "conservation", "status",
    "taxonom", "phylogen", "evolution", "nomenclature", "etymolog",
)

# A paragraph that reads like a rule, whatever section it turned up in. The
# allowlist keeps whole sections about fishing out; this catches the sentence
# in a Conservation section that happens to name a minimum size. Refused
# paragraphs are counted and reported rather than dropped quietly.
REGULATORY = re.compile(
    r"\b(?:bag|size|creel|possession|slot|catch)\s+limits?\b"
    r"|\bminimum\s+(?:size|length)\b"
    r"|\b(?:open|closed)\s+season\b"
    r"|\bsize\s+restrictions?\b"
    r"|\blegal(?:ly)?\s+(?:size|minimum|to\s+(?:keep|retain|land))\b"
    r"|\bmay\s+not\s+be\s+(?:kept|retained|landed)\b"
    r"|\bper\s+(?:angler|person|vessel)\s+per\s+day\b"
    r"|\bquotas?\b|\bmoratorium\b|\bpermit\s+is\s+required\b",
    re.I)


def _norm(s: str) -> str:
    return re.sub(r"[^a-z]", "", (s or "").lower())


def _wanted_section(heading: str) -> bool:
    h = (heading or "").lower()
    if any(w in h for w in DENY_WORDS):
        return False
    return any(w in h for w in ALLOW_WORDS)


def _rank(heading: str) -> int:
    h = (heading or "").lower()
    for i, w in enumerate(SECTION_ORDER):
        if w in h:
            return i
    return len(SECTION_ORDER)


def _get(api: str, params: dict) -> dict:
    params = dict(params, format="json", formatversion="2")
    req = urllib.request.Request(
        api + "?" + urllib.parse.urlencode(params), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as fh:
        return json.loads(fh.read().decode("utf-8"))


def _plain(s: str) -> str:
    """Commons metadata is HTML fragments -- an <a> round the photographer's
    name, a <span> round the licence. The card renders escaped text, so the
    markup has to come off here or it shows up as angle brackets."""
    txt = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(txt)).strip()


# ------------------------------------------------------------------- lookup

def article(binomial: str) -> dict | None:
    """The English Wikipedia article for this binomial, verified, or None.

    Verified means the article's Wikidata item says it is a species and says
    its taxon name is the one we asked for. A redirect is followed -- that is
    how "Tautoga onitis" reaches the article headed "Tautog" -- but the thing
    at the end of it still has to prove what it is.
    """
    if not binomial:
        return None
    try:
        d = _get(WP, {"action": "query", "titles": binomial, "redirects": "1",
                      "prop": "pageprops|revisions", "rvprop": "ids|timestamp",
                      "rvslots": "main"})
    except (urllib.error.URLError, OSError, ValueError):
        return {"error": "wikipedia lookup failed"}
    pages = (d.get("query") or {}).get("pages") or []
    if not pages or pages[0].get("missing"):
        return None
    page = pages[0]
    qid = (page.get("pageprops") or {}).get("wikibase_item")
    if not qid:
        return None
    time.sleep(PAUSE)
    try:
        ent = _get(WD, {"action": "wbgetentities", "ids": qid,
                        "props": "claims"})
    except (urllib.error.URLError, OSError, ValueError):
        return {"error": "wikidata lookup failed"}
    claims = ((ent.get("entities") or {}).get(qid) or {}).get("claims") or {}

    def vals(prop):
        out = []
        for c in claims.get(prop, []):
            v = (c.get("mainsnak") or {}).get("datavalue", {}).get("value")
            out.append(v.get("id") if isinstance(v, dict) else v)
        return [v for v in out if v]

    if Q_SPECIES not in vals(P_RANK):
        # "Weakfish" redirects to the genus Cynoscion. A genus is not a fish
        # and a card headed "Weakfish" showing the genus would be a quiet lie.
        return None
    taxa = vals(P_TAXON)
    want = _norm(binomial)
    verified = None
    if any(_norm(t) == want for t in taxa):
        verified = "taxon name"
    else:
        # A genus revision, handled the way `fishpic` handles it: the epithet
        # has to match and the record has to say the genus moved. NMFS-NE-146
        # prints *Loligo pealeii*; the accepted combination is *Doryteuthis
        # pealeii*, and both are the same animal.
        epithet = binomial.split()[-1].lower()
        for t in taxa:
            parts = (t or "").split()
            if len(parts) == 2 and parts[1].lower() == epithet:
                verified = ("taxon name (genus revised since the document was "
                            "written)")
                binomial = t
                break
    if not verified:
        return None
    rev = (page.get("revisions") or [{}])[0]
    return {"title": page["title"], "pageid": page.get("pageid"), "qid": qid,
            "revid": rev.get("revid"), "revised_on": (rev.get("timestamp") or "")[:10],
            "taxon": binomial, "verified": verified,
            "url": "https://en.wikipedia.org/wiki/" +
                   urllib.parse.quote(page["title"].replace(" ", "_")),
            "permalink": "https://en.wikipedia.org/w/index.php?oldid=%s"
                         % rev.get("revid")}


def sections(title: str) -> dict:
    """The article as plain text, cut into the sections a card may show.

    Returns the lead summary, the kept sections in reading order, and -- not
    optionally -- what was refused and why. A card that showed only what
    survived would look like the whole article, and the one thing worth
    knowing about a filtered source is that it was filtered.
    """
    try:
        d = _get(WP, {"action": "query", "titles": title, "prop": "extracts",
                      "explaintext": "1", "exsectionformat": "wiki",
                      "redirects": "1"})
    except (urllib.error.URLError, OSError, ValueError):
        return {"error": "extract failed"}
    pages = (d.get("query") or {}).get("pages") or []
    if not pages or pages[0].get("missing"):
        return {"error": "no article"}
    text = pages[0].get("extract") or ""

    # Split on top-level headings only. `== Description ==` opens a section;
    # `=== Juveniles ===` stays inside it, because a subsection promoted to a
    # section of its own loses the heading that says what it is about.
    parts = re.split(r"^== *([^=].*?) *==$", text, flags=re.M)
    lead = _paragraphs(parts[0])
    kept, refused = [], []
    for i in range(1, len(parts) - 1, 2):
        head, body = parts[i], parts[i + 1]
        if not _wanted_section(head):
            refused.append(head)
            continue
        paras, dropped = [], 0
        for p in _paragraphs(body):
            # Subsection headings survive the split as `=== x ===` lines;
            # keep them as their own short line so the text does not run two
            # topics together.
            p = re.sub(r"^=+ *(.+?) *=+$", r"\1:", p)
            if REGULATORY.search(p):
                dropped += 1
                continue
            paras.append(p)
        if not paras:
            refused.append(head)
            continue
        kept.append({"heading": head, "paragraphs": paras,
                     "dropped_paragraphs": dropped})
    kept.sort(key=lambda s: _rank(s["heading"]))
    lead_kept = [p for p in lead if not REGULATORY.search(p)]
    return {"summary": lead_kept,
            "summary_dropped": len(lead) - len(lead_kept),
            "sections": kept, "refused": refused,
            "chars": sum(len(p) for s in kept for p in s["paragraphs"])}


def _paragraphs(block: str) -> list[str]:
    out = []
    for p in (block or "").split("\n"):
        p = p.strip()
        if len(p) > 1:
            out.append(p)
    return out


# -------------------------------------------------------------------- image

def image(title: str) -> dict | None:
    """The article's lead image, if Commons licenses it openly enough to keep.

    This is the taxobox image, and choosing it over iNaturalist's top-voted
    observation photo is the whole point -- see `fishpic` for the tautog that
    prompted it. An editor picked this one to show what the species looks
    like; iNaturalist's is the photograph other users liked most, which is a
    different question with a different answer.
    """
    try:
        d = _get(WP, {"action": "query", "titles": title, "redirects": "1",
                      "prop": "pageimages", "piprop": "name|thumbnail",
                      "pithumbsize": "800"})
    except (urllib.error.URLError, OSError, ValueError) as exc:
        # An error dict, not None, and the distinction earns its keep: None
        # means "Commons has nothing free for this fish" and sends the caller
        # on to iNaturalist, which is a worse source for this job. A network
        # blip must not quietly demote every card it touches.
        return {"error": "commons lookup failed: %s" % exc}
    pages = (d.get("query") or {}).get("pages") or []
    if not pages:
        return None
    name = pages[0].get("pageimage")
    thumb = (pages[0].get("thumbnail") or {}).get("source")
    if not name or not thumb:
        return None
    time.sleep(PAUSE)
    try:
        f = _get(WP, {"action": "query", "titles": "File:" + name,
                      "prop": "imageinfo",
                      "iiprop": "extmetadata|url|mime|size"})
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"error": "commons licence lookup failed: %s" % exc}
    fpages = (f.get("query") or {}).get("pages") or []
    if not fpages or not fpages[0].get("imageinfo"):
        return None
    page = fpages[0]
    info = page["imageinfo"][0]
    meta = info.get("extmetadata") or {}

    def m(k):
        return _plain((meta.get(k) or {}).get("value") or "")

    code = (m("License") or "").lower()
    short = m("LicenseShortName")
    if not any(code.startswith(p) for p in OPEN_PREFIXES) and \
            "public domain" not in short.lower():
        return None
    # A file stored locally on en.wikipedia rather than shared from Commons is
    # usually there *because* it is non-free. Taxobox images never are, so
    # requiring the shared repository costs nothing and closes the hole.
    if page.get("imagerepository") not in ("shared", ""):
        return None
    artist = m("Artist") or m("Credit") or "unknown"
    return {"url": thumb, "file": name, "licence": short or code or "?",
            "licence_code": code, "attribution": artist,
            "credit_url": info.get("descriptionurl") or "",
            "mime": info.get("mime") or ""}


# --------------------------------------------------------------------- cache

def load() -> dict:
    """The cache, or an empty one. `cache.read_json` treats a corrupt file as
    absent, which is this project's one deliberate exception to no-silent-
    fallbacks: a truncated write should cost one refetch, not an exception."""
    return cache.read_json(CACHE, default={}) or {}


def has_content(entry: dict) -> bool:
    """Is there anything in this cache entry worth showing?

    Summary OR sections, not sections alone. The scup article puts all of it
    in the lead -- how big they get, how long they live, where they spawn,
    that they were the most abundant fish in colonial Narragansett Bay -- and
    has no section this allowlist wants. Gating on sections threw all four
    paragraphs away and the card said "not fetched yet" about a fish that had
    been fetched, which is the wrong kind of absence for the second time in
    one file.

    **One function because that fix was applied in one of the two places that
    needed it.** `get` learned the rule and `fetch_all`'s cache check did not,
    so scup was served correctly and re-fetched on every single run --
    "1 read · 36 already cached", for ever, three round trips to answer a
    question already on disk. The bug was not the predicate, it was that the
    predicate was written twice; so now it is written once and both callers
    ask it.
    """
    return bool(entry.get("sections") or entry.get("summary"))


def get(key: str) -> dict | None:
    """What the card should show for this fish, or None if nothing is cached
    or the last look found nothing. The caller says which -- `entry()` keeps
    the reason."""
    e = load().get(key) or {}
    return e if has_content(e) else None


def entry(key: str) -> dict:
    return load().get(key) or {}


def fetch_all(species_list, refresh: bool = False, log=print) -> dict:
    """Read each fish's article and keep the natural history. A small report.

    Not called by the server or by any forecast path, for the same reason
    `fishpic.fetch_all` is not: this is thirty-seven fish and a hundred-odd
    requests, and a boat asking for a card must never wait on a network.
    `tiderace species --info` is the only caller.
    """
    from . import species as speciesmod
    have = load()
    report = {"read": 0, "kept": 0, "no_article": [], "no_binomial": [],
              "failed": [], "refused_sections": 0, "dropped_paragraphs": 0}

    for sp in species_list:
        if has_content(have.get(sp.key) or {}) and not refresh:
            report["kept"] += 1
            continue
        binomial = speciesmod.scientific(sp.key)
        if not binomial:
            # Never a common-name search. The three wrong fish in this
            # module's docstring are what that costs.
            report["no_binomial"].append(sp.key)
            log("  %-22s no sourced binomial — not looked up" % sp.key)
            continue
        art = article(binomial)
        time.sleep(PAUSE)
        if art and art.get("error"):
            # A network failure is a fact about the network. Recording it as
            # "no article" would make it a claim about the fish, which is the
            # bug `fishpic` carried until today.
            report["failed"].append(sp.key)
            log("  %-22s %s" % (sp.key, art["error"]))
            continue
        if not art:
            have[sp.key] = {"binomial": binomial, "found": False,
                            "checked_on": time.strftime("%Y-%m-%d")}
            report["no_article"].append(sp.key)
            log("  %-22s no verified article for %s" % (sp.key, binomial))
            continue
        sec = sections(art["title"])
        time.sleep(PAUSE)
        if sec.get("error"):
            report["failed"].append(sp.key)
            log("  %-22s %s" % (sp.key, sec["error"]))
            continue
        img = image(art["title"])
        time.sleep(PAUSE)
        have[sp.key] = dict(art, found=True, summary=sec["summary"],
                            sections=sec["sections"],
                            refused=sec["refused"],
                            summary_dropped=sec["summary_dropped"],
                            image=img,
                            checked_on=time.strftime("%Y-%m-%d"))
        report["read"] += 1
        report["refused_sections"] += len(sec["refused"])
        report["dropped_paragraphs"] += sec["summary_dropped"] + sum(
            s["dropped_paragraphs"] for s in sec["sections"])
        log("  %-22s %-26s %2d sections · %5d chars · %s"
            % (sp.key, art["title"][:26], len(sec["sections"]), sec["chars"],
               "image" if img else "no free image"))

    cache.write_json(CACHE, have)
    return report
