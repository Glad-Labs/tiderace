"""Third-party fishing reports as evidence about seasonal timing.

The forecast knows two things about when a fish is around. Sixty-five years of
GSO temperature says when the bay is inside a species' thermal band, and a
hand-written `peak_months` tuple says when the migratory push happens. The
first is measurement. The second is me guessing, and no temperature series can
check it -- stripers peak in May and October because they are *moving through*,
which is not a thermal fact.

Fishing reports are the only source that can check it. They are direct
observation of fish being caught, dated, by someone who was there.

Three rules, each learned the hard way elsewhere in this project:

**One article is one witness.** A weekly report naming seven species in four
places is a single observation event, not twenty-eight. Counting rows instead
of sources is how you manufacture a consensus out of one person's Thursday.
Everything here dedupes to (source, species, week) before it counts anything.

**Reports never outrank first-hand observation.** They corroborate. A report is
SECONDHAND in the provenance model, below your own eyes and below an
instrument, and this module deliberately returns evidence rather than a score
so that nothing here can quietly overwrite what you saw yourself.

**Absence is not evidence of absence.** A report that does not mention tautog
is not a report that tautog were missing. Only an explicit statement of absence
counts as a negative, and the extractor is told to record those separately.
Silence is silence.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime, timedelta

from . import extract

# A report is a snapshot of one week. Beyond this it stops describing "now".
FRESH_DAYS = 10

def _outlet(url: str) -> str:
    """The publisher. Used only as a fallback identity -- see _witness."""
    try:
        return url.split("/")[2].lower().removeprefix("www.")
    except (IndexError, AttributeError):
        return "unknown"


# Rhode Island has a handful of magazines and a handful of tackle shops, and
# the magazines all phone the same shops. A single On The Water column quotes
# Ocean State Tackle in one paragraph and The Saltwater Edge in the next, while
# On The Water and The Fisherman may both be relaying Snug Harbor in the same
# week. So the publisher is the wrong unit of independence in BOTH directions:
# it splits one article into too few witnesses and merges two magazines into
# too many.
#
# The witness is whoever actually saw the fish. Fall back to the publisher only
# when a paragraph credits nobody, and keep the two namespaced apart so an
# unattributed On The Water item never silently merges with an attributed one.
_NOISE = {"the", "at", "in", "of", "inc", "llc", "co", "and", "bait", "tackle",
          "marina", "outfitters", "outfitter", "shop", "store", "charters",
          "guide", "guides", "capt", "captain", "mr", "ms"}


def _norm_name(name: str) -> str:
    """Collapse a credited source to a stable identity.

    Reports name the same shop several ways across a season -- "Ocean State
    Tackle", "Ocean State Tackle in Providence", "Dave at Ocean State". Keeping
    the first two significant words absorbs the trailing town and the dropped
    suffix, which is what actually varies. Two words rather than one because
    "Watch Hill" and "Watch anything else" should not merge.
    """
    raw = (name or "").lower()
    # "Dave at Ocean State Tackle" -- the person moves jobs, the shop is the
    # stable identity, and the article writes it both ways across a season.
    if " at " in raw:
        raw = raw.rsplit(" at ", 1)[1]
    words = re.findall(r"[a-z0-9]+", raw)
    keep = [w for w in words if w not in _NOISE]
    return "".join(keep[:2])


def _witness(row: dict) -> str:
    """Stable identity for whoever actually saw the fish.

    A two-word credit -- "The Saltwater Edge", "Frances Fleet", "Rob Taylor" --
    identifies a business or a named person well enough to recognise across
    outlets, so it merges globally. A bare first name does not: the "Dave" in
    one magazine and the "Dave" in another are not evidently the same Dave, and
    merging them would invent corroboration out of a common name. Those stay
    namespaced to the publisher that printed them, which costs us a real merge
    occasionally and never fabricates one.
    """
    raw = row.get("attributed_to", "")
    who = _norm_name(raw)
    if not who:
        return f"pub:{_outlet(row.get('source_url', ''))}"
    tokens = [w for w in re.findall(r"[a-z0-9]+", raw.lower()) if w not in _NOISE]
    if len(tokens) < 2:
        return f"pub:{_outlet(row.get('source_url', ''))}/{who}"
    return f"who:{who}"


def _parse_day(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(str(s)[:10]).date()
    except ValueError:
        return None


def catch_reports(path: str | None = None) -> list[dict]:
    """Every dated catch observation extracted from a report.

    Undated rows are dropped rather than defaulted. A catch report with no date
    cannot speak to timing, which is the only question this module asks, and
    silently stamping it with today's date would invent evidence.
    """
    rows = extract.load_queue(path) if path else extract.load_queue()

    # The queue is append-only, so re-scraping an article on Tuesday and again
    # on Friday writes the same observation twice. Left alone that would look
    # like fresh corroboration -- the same writer's same sentence, counted
    # again.
    #
    # But collapsing on (article, species, place, day) alone is too aggressive:
    # one column often has Ocean State and The Saltwater Edge both reporting
    # sea bass off the south shore, and that IS two witnesses. So attribution
    # is part of the identity, and unattributed rows are dropped only when an
    # attributed row covers the same observation -- which is what a re-run with
    # better extraction produces.
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("kind") != "catch_report":
            continue
        groups[(r.get("source_url", ""), r.get("species_key"),
                r.get("place", ""), str(r.get("observed_on")))].append(r)

    rows = []
    for grp in groups.values():
        attributed = [r for r in grp if r.get("attributed_to")]
        pool = attributed or grp[:1]
        newest: dict[str, dict] = {}
        for r in pool:
            who = r.get("attributed_to", "")
            if str(r.get("queued_at", "")) >= str(newest.get(who, {}).get("queued_at", "")):
                newest[who] = r
        rows.extend(newest.values())

    out = []
    for r in rows:
        if r.get("kind") != "catch_report":
            continue
        day = _parse_day(r.get("observed_on"))
        if not day:
            continue
        out.append({
            "species": r.get("species_key"),
            "species_raw": r.get("species_raw") or r.get("species", ""),
            "day": day,
            "week": int(day.strftime("%V")),
            "place": r.get("place", ""),
            "spot": r.get("matched_spot"),
            "outlet": _outlet(r.get("source_url", "")),
            "attributed_to": r.get("attributed_to", ""),
            "witness": _witness(r),
            "url": r.get("source_url", ""),
            "confidence": r.get("confidence", "medium"),
            "quote": r.get("quote", ""),
        })
    return out


def witnesses(rows: list[dict] | None = None) -> dict[tuple, set]:
    """(species, week) -> set of outlets that reported it.

    The set is the point. Its *size* is the number of independent witnesses;
    the number of rows behind it is not evidence of anything.
    """
    rows = catch_reports() if rows is None else rows
    idx: dict[tuple, set] = defaultdict(set)
    for r in rows:
        if r["species"]:
            idx[(r["species"], r["week"])].add(r["witness"])
    return idx


def weekly_presence(species: str, rows: list[dict] | None = None) -> dict[int, int]:
    """week-of-year -> number of independent outlets reporting this species.

    This is the curve that can eventually be laid against `peak_months`. It
    needs a season of reports before it says anything; with one week of data it
    is one bar, and reading a season into one bar is exactly the mistake this
    project keeps trying not to make.
    """
    idx = witnesses(rows)
    return {wk: len(o) for (sp, wk), o in sorted(idx.items()) if sp == species}


def corroborate(species: str, on: date | None = None,
                rows: list[dict] | None = None) -> dict:
    """Does recent third-party reporting agree this species is being caught?

    Returns evidence, not a multiplier. Nothing in the scorer consumes this --
    it is here to be read by a person deciding where to go, which is the job
    Matt actually asked the reports to do.
    """
    on = on or date.today()
    rows = catch_reports() if rows is None else rows
    recent = [r for r in rows
              if r["species"] == species and 0 <= (on - r["day"]).days <= FRESH_DAYS]
    outlets = {r["witness"] for r in recent}
    places = sorted({r["place"] for r in recent if r["place"]})
    newest = max((r["day"] for r in recent), default=None)
    return {
        "species": species,
        "outlets": sorted(outlets),
        "witnesses": len(outlets),
        "observations": len(recent),
        "places": places,
        "newest": newest.isoformat() if newest else None,
        "verdict": ("reported caught" if outlets else "no recent report"),
    }


def unmodelled(rows: list[dict] | None = None) -> dict[str, int]:
    """Species that showed up in reports but that we do not model.

    Worth surfacing rather than discarding: a bonito run appearing in the
    reports is real information about what is in the water, and the fact that
    the scorer has nothing to say about it is a gap in the scorer, not in the
    report.
    """
    rows = catch_reports() if rows is None else rows
    out: dict[str, int] = defaultdict(int)
    for r in rows:
        if not r["species"] and r["species_raw"]:
            out[r["species_raw"].lower()] += 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def disagreements(on: date | None = None,
                  rows: list[dict] | None = None) -> list[dict]:
    """Where third-party reports contradict the model's seasonal presence.

    This is the whole point of pulling reports in. The model's warm-end cutoffs
    are the least defensible numbers in `score.py` -- hand-set, uncited, and
    unfalsifiable without exactly this kind of outside observation. A report
    saying a species is being caught in a week the model calls impossible is
    the model being wrong out loud.

    It deliberately does NOT retune anything. One outlet saying tog are biting
    is one witness, and quietly refitting a curve to one witness is how you
    launder an anecdote into a parameter. This surfaces the conflict and leaves
    the decision to a person.

    A caveat that belongs next to every result: our thermometers read surface
    water, and structure species sit deeper and colder than the surface gauge.
    A disagreement here may mean the band is wrong, or it may mean we are
    measuring the wrong water.
    """
    on = on or date.today()
    rows = catch_reports() if rows is None else rows
    from . import gso, score

    out = []
    for sp in sorted({r["species"] for r in rows if r["species"]}):
        if sp not in score.PROFILES:
            continue
        ev = corroborate(sp, on, rows)
        if not ev["witnesses"]:
            continue
        season = gso.thermal_season(sp)
        if not season:
            continue
        wk = int(on.strftime("%V"))
        modelled = season.get(wk)
        if modelled is None or modelled > 0.25:
            continue
        out.append({
            "species": sp,
            "model_presence": modelled,
            "witnesses": ev["witnesses"],
            "observations": ev["observations"],
            "newest": ev["newest"],
            "quotes": [r["quote"] for r in rows
                       if r["species"] == sp and r["quote"]][:2],
            "note": ("model says absent this week; reports say caught. "
                     "Check whether the warm-end cutoff is wrong or whether "
                     "the surface thermometer is reading the wrong water."),
        })
    return out
