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

import json
import os
from collections import defaultdict
from datetime import date, datetime, timedelta

from . import extract

# A report is a snapshot of one week. Beyond this it stops describing "now".
FRESH_DAYS = 10

# Distinct outlets covering the same week are the corroboration that matters;
# two articles from one outlet are closer to one witness than two.
def _outlet(url: str) -> str:
    try:
        return url.split("/")[2].lower().removeprefix("www.")
    except (IndexError, AttributeError):
        return "unknown"


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
            idx[(r["species"], r["week"])].add(r["outlet"])
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
    outlets = {r["outlet"] for r in recent}
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
