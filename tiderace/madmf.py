"""Deterministic parser for Massachusetts DMF MarineFisheries Advisories.

Written as a portability test for `reconcile.py`: if the effective-state
logic is genuinely state-agnostic, a second extractor should be able to feed
it without the reconciler changing at all. What the reconciler consumes is a
notice dict, not text, so this module's only job is to produce the same shape
`ridem.parse_notice` does.

**MA is not RI, and four differences cost real work:**

  1. **No checksum.** RIDEM spells every number twice -- "four hundred (400)"
     -- which lets `ridem.parse_amount` cross-check the words against the
     digits. DMF writes "1,000 pounds" once. The single best property of the
     RI parser does not survive the border, and `cross_checked` is False on
     every record here. That is a real loss of confidence, not a formatting
     quibble, and it is why nothing in this module should ever auto-apply.

  2. **The year is usually missing.** "effective Tuesday, June 9." The year
     lives in the advisory's dateline at the top of the page. So a notice
     cannot be parsed from its own sentence the way a RIDEM notice can --
     `parse_advisory` needs the whole document, and a sentence-level API
     would silently guess the wrong year every January.

  3. **Limits are per gear, not per fishery.** One advisory sets 600 lb for
     pot fishers and 300 lb for hook and line in the same sentence. So one
     document yields *several* notice records where a RIDEM sentence yields
     exactly one. Gear rides in `sub_fishery`, which is already part of
     `reconcile._key`, so the reconciler keeps them apart for free.

  4. **Successors are conditional.** RIDEM says a limit runs "until the next
     sub period begins on May 1, 2026 at ten thousand (10,000) pounds per
     week" -- a promise. DMF says the limit "may increase to 5,000 pounds if
     at least 10% of the quota remains available" -- a forecast. Promoting
     that the way `_promote` promotes a RIDEM successor would assert a limit
     that may never take effect. Conditional successors are therefore parsed,
     marked `conditional`, and deliberately NOT offered as successors.

Everything the templates do not cover is reported as unparsed rather than
guessed at, exactly as in `ridem.py`.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from .ridem import MONTHS, SPECIES_HINTS

SOURCE = "https://www.mass.gov/marine-fisheries-advisories-and-legal-notices"
HOTLINE = "(617) 626-1520"

# DMF publishes advisories as PDFs, where RIDEM publishes an HTML page. The
# text has to come from somewhere upstream; this module takes it already
# extracted so the parser stays testable without a PDF dependency.

_DAY = r"(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day"
_MONTH = ("January|February|March|April|May|June|July|August|September|"
          "October|November|December")

DATELINE = re.compile(rf"^\s*(?P<month>{_MONTH})\s+(?P<day>\d{{1,2}}),\s+(?P<year>\d{{4}})\s*$",
                      re.I | re.M)

# "Effective Tuesday, September 1, 2026," / "effective at 0001 hours on
# Wednesday, August 5" / "effective Tuesday, June 9." / "opens on Wednesday,
# July 1" / "will open on Tuesday, June 16".
EFFECTIVE = re.compile(
    rf"(?i)\b(?:effective|will\s+open\s+on|opens\s+on|will\s+close\s+on)\b"
    rf"(?:\s+at\s+[\d:]+\s*(?:hours|[ap]\.?m\.?))?"
    rf"(?:\s+on)?\s+(?:{_DAY},?\s+)?"
    rf"(?P<month>{_MONTH})\s+(?P<day>\d{{1,2}})(?:,\s*(?P<year>\d{{4}}))?")

# A bare date used for successor clauses: "increases to 600 pounds on
# September 1 if at least 15% of the quota remains".
ON_DATE = re.compile(
    rf"(?i)\bon\s+(?:{_DAY},?\s+)?(?P<month>{_MONTH})\s+(?P<day>\d{{1,2}})"
    rf"(?:,\s*(?P<year>\d{{4}}))?")

# DMF hyphenates attributive amounts ("a 500-pound daily trip limit",
# "15-fish") and spaces predicative ones ("to 600 pounds"). The lookahead
# keeps annual quotas out: "a 683,773-pound quota" is the size of the whole
# fishery, and reading it as a trip limit is off by four orders of magnitude.
AMOUNT = re.compile(
    r"(?i)(?P<value>\d[\d,]*(?:\.\d+)?)[\s-]*(?P<unit>pounds?|lbs?|fish|inches|inch)\b"
    r"(?!\s+(?:quota|set-aside))")

# Gear and permit class carry the limit in Massachusetts.
#
# Order matters, and it bit hard: "hook and line fishers (and other non-trawl
# gear)" matched `trawl` first and reported the 600 lb hook-and-line limit as
# a trawler limit. Trawlers get 100 lb incidental. A parser that is wrong by
# 6x in the permissive direction writes someone a violation, so the negated
# forms are excluded explicitly and the specific gears are tested first.
GEAR_HINTS = [
    (r"all gear types", "all_gear"),
    (r"purse sein", "purse_seine"),
    (r"weir", "weir"),
    (r"hook and line", "hook_and_line"),
    (r"rod and reel", "rod_and_reel"),
    (r"(?<!non-)(?<!non )trawl", "trawl"),
    (r"\bpot(?:ter|s|\b)", "pot"),
    (r"limited access|limited entry", "limited_access"),
    (r"open access", "open_access"),
    (r"boat-based", "boat_based"),
]

# The quota-use conditions DMF attaches to almost every forward-looking
# change. Their presence is the whole reason a successor cannot be promoted.
CONDITIONAL = re.compile(
    r"(?i)\b(?:if|provided|should|unless)\b[^.]{0,120}?"
    r"(?:\d+%|quota|remains?\s+available|otherwise\s+notified)")

# "until the quota is taken", "until 100% of the annual quota is taken",
# "until it is scheduled to reopen in 2027" -- an end with no date on it.
UNDATED_END = re.compile(
    r"(?i)\buntil\b[^.]{0,80}?(?:quota\s+is\s+taken|scheduled\s+to\s+reopen"
    r"|further\s+notice)")

# A sentence describing what DMF *might* do later, not what is in force now:
# "At that time, the trip limit may increase to 5,000 pounds if at least 10%
# of the quota remains available." Read as current, that puts a 5x limit on
# the boat a month before anyone has decided it applies.
FORWARD_LOOKING = re.compile(
    r"(?i)\b(?:may|might|could)\s+(?:increase|decrease|be\s+"
    r"(?:increased|decreased|reduced|added))|^\s*at\s+that\s+time\b")


def _mkdate(month: str, day: str, year: str | None, fallback_year: int) -> str | None:
    m = MONTHS.get(month.lower())
    if not m:
        return None
    try:
        return date(int(year) if year else fallback_year, m, int(day)).isoformat()
    except ValueError:
        return None


def dateline_year(text: str) -> int:
    """The advisory's own date. MA notices omit the year in the body."""
    m = DATELINE.search(text)
    if m:
        try:
            return int(m.group("year"))
        except ValueError:
            pass
    return datetime.now().year


def _species(text: str) -> tuple[str | None, str | None]:
    low = text.lower()
    # Longest name first so "summer flounder" is not shadowed by a bare
    # "flounder" hint, and "black sea bass" not by "bass".
    for name in sorted(SPECIES_HINTS, key=len, reverse=True):
        if name in low:
            return name, SPECIES_HINTS[name]
    return None, None


def _gear(text: str) -> str | None:
    low = text.lower()
    for pat, key in GEAR_HINTS:
        if re.search(pat, low):
            return key
    return None


def _amount(text: str) -> dict | None:
    """The amount a clause *lands on*.

    DMF states changes as "from 500 pounds to 600 pounds", so the last value
    in a from/to pair is the operative one. Taking the first would report
    every increase as its own predecessor.
    """
    pair = re.search(
        r"(?i)\bfrom\s+(\d[\d,]*)\s*(?:pounds?|lbs?|fish)\s+to\s+"
        r"(\d[\d,]*)\s*(pounds?|lbs?|fish)", text)
    if pair:
        return {"value": int(pair.group(2).replace(",", "")),
                "unit": pair.group(3).lower(), "cross_checked": False,
                "agrees": None, "previous": int(pair.group(1).replace(",", ""))}
    m = AMOUNT.search(text)
    if not m:
        return None
    return {"value": int(float(m.group("value").replace(",", ""))),
            "unit": m.group("unit").lower(),
            # No word-form to check against. See the module docstring.
            "cross_checked": False, "agrees": None}


def _change_type(text: str) -> str:
    low = text.lower()
    if re.search(r"\b(?:is\s+clos|will\s+clos|to\s+close|remain\s+closed)\b", low):
        return "season_close"
    if re.search(r"\b(?:will\s+open|opens\s+on|to\s+open|be\s+added)\b", low):
        return "season_open"
    if re.search(r"minimum\s+size", low):
        return "minimum_size"
    if re.search(r"trip\s+limit|possession\s+and\s+landing\s+limit|daily\s+limit"
                 r"|possession\s+limit|landing\s+limit", low):
        return "possession_limit"
    return "other"


def _period(text: str) -> str | None:
    low = text.lower()
    if "consecutive" in low and "two" in low:
        return "per two days"
    if re.search(r"\bdaily\b|per\s+day|any\s+single\s+calendar\s+day", low):
        return "per day"
    if re.search(r"per\s+week|weekly", low):
        return "per week"
    if re.search(r"bi-?week", low):
        return "per bi-week"
    return None


def _sentences(body: str) -> list[str]:
    # Collapse the PDF's hard-wrapped lines before splitting, or every
    # sentence arrives in three pieces and no clause survives intact.
    flat = re.sub(r"\s*\n\s*", " ", body)
    flat = re.sub(r"\s{2,}", " ", flat)
    return [s.strip() for s in re.split(r"(?<=[.])\s+(?=[A-Z])", flat) if s.strip()]


def _successor(sentence: str, year: int, current: dict | None) -> tuple[dict | None, bool]:
    """A later change named inside this sentence.

    Returns (successor, conditional). A conditional successor is returned so
    it can be surfaced to a human, but callers must not promote it -- see the
    module docstring.
    """
    fwd = re.search(
        r"(?i)\b(?:increase|decrease|reduce)[sd]?\s+to\s+(\d[\d,]*)\s*"
        r"(pounds?|lbs?|fish)([^.]{0,120})", sentence)
    if not fwd:
        return None, False
    value = int(fwd.group(1).replace(",", ""))
    # "will increase to 1,000 pounds" IS the change this notice makes, not a
    # successor to it. Without this the parser hands every notice itself as
    # its own replacement.
    if current and current.get("value") == value:
        return None, False
    tail = fwd.group(3) or ""
    conditional = bool(CONDITIONAL.search(tail) or CONDITIONAL.search(sentence))
    dm = ON_DATE.search(tail)
    when = _mkdate(dm.group("month"), dm.group("day"), dm.group("year"), year) if dm else None
    return ({"effective_date": when,
             "amount": {"value": value, "unit": fwd.group(2).lower(),
                        "cross_checked": False, "agrees": None},
             "period": _period(sentence),
             "unlimited": False,
             "closes": False,
             "conditional": conditional}, conditional)


def parse_advisory(text: str, species_hint: str | None = None) -> dict:
    """Parse one MarineFisheries Advisory into reconcile-shaped notices.

    One advisory yields one record per gear class it sets a limit for.
    """
    year = dateline_year(text)
    sentences = _sentences(text)

    # The effective date is stated once, usually in the first operative
    # sentence, and the rest of the advisory refers back to it.
    eff = None
    for s in sentences:
        m = EFFECTIVE.search(s)
        if m:
            eff = _mkdate(m.group("month"), m.group("day"), m.group("year"), year)
            if eff:
                break

    doc_name, doc_key = _species(text)
    if species_hint:
        doc_key = species_hint

    notices: list[dict] = []
    unparsed: list[str] = []
    unmodelled: list[str] = []
    conditional_changes: list[dict] = []
    warnings: list[str] = []

    for s in sentences:
        change = _change_type(s)
        if change == "other":
            continue
        amt = _amount(s)
        if change in ("possession_limit", "minimum_size") and not amt:
            continue

        name, key = _species(s)
        key = key or doc_key
        name = name or doc_name
        if not key:
            # Menhaden, squid, dogfish and scallops all get DMF advisories.
            # Not modelling a species is a scope fact, not a parse failure,
            # and conflating the two hides the real failures in the noise.
            unmodelled.append(s[:200])
            continue

        s_eff = None
        m = EFFECTIVE.search(s)
        if m:
            s_eff = _mkdate(m.group("month"), m.group("day"), m.group("year"), year)
        s_eff = s_eff or eff
        if not s_eff:
            unparsed.append(s[:200])
            continue

        succ, conditional = _successor(s, year, amt)

        # A purely forward-looking sentence states no limit in force today.
        # It is kept, but out of the notice stream -- the reconciler's job is
        # "what is the rule right now", and a maybe is not a rule.
        if FORWARD_LOOKING.search(s) and CONDITIONAL.search(s):
            conditional_changes.append(
                {"species_key": key, "amount": amt, "quote": s.strip()[:240]})
            continue

        # A per-gear sentence can set two limits at once: "increases from 500
        # pounds to 600 pounds for pot fishers and from 250 pounds to 300
        # pounds for hook and line fishers". The trailing alternation must be
        # a lookahead -- consuming the "and from" ate the start of the second
        # pair, so only the first gear was ever recorded.
        pairs = re.findall(
            r"(?i)from\s+\d[\d,]*\s*(?:pounds?|lbs?|fish)\s+to\s+(\d[\d,]*)\s*"
            r"(pounds?|lbs?|fish)\s+for\s+([^,.]{0,60}?)(?=\s+and\s+from|[,.]|$)", s)
        if len(pairs) < 2:
            # The striped bass rule is stated as "is A for X and B for Y"
            # rather than "from/to", but it is the same fact: one species,
            # several permit classes, different numbers.
            pairs = re.findall(
                r"(?i)(\d[\d,]*)[\s-]*(pounds?|lbs?|fish)\s+for\s+"
                r"([^,.]{0,80}?)(?=,?\s+and\s+\d|[,.]|$)", s)
        if len(pairs) > 1:
            for value, unit, who in pairs:
                notices.append(_record(
                    s_eff, name, key, change,
                    {"value": int(value.replace(",", "")), "unit": unit.lower(),
                     "cross_checked": False, "agrees": None},
                    _gear(who), _period(s), succ, conditional, s))
            continue

        notices.append(_record(s_eff, name, key, change, amt, _gear(s),
                               _period(s), succ, conditional, s))

    notices = _dedupe(notices)

    for n in notices:
        if n["sub_fishery"] is None and n["change_type"] == "possession_limit":
            warnings.append(
                f"{n['species']}: limit with no gear class named — "
                f"MA limits are gear-specific, so this may be incomplete: "
                f"{n['quote'][:70]}")
    if not any(n["amount"] and n["amount"].get("cross_checked") for n in notices):
        warnings.append(
            "no notice carries a word-form cross-check — MA DMF writes numbers "
            "once, so every amount here is single-sourced")

    return {"notices": notices, "unparsed": unparsed,
            "unmodelled_species": unmodelled,
            "conditional_changes": conditional_changes, "warnings": warnings,
            "parsed_at": datetime.now().isoformat(timespec="seconds")}


def _dedupe(notices: list[dict]) -> list[dict]:
    """One advisory restates its own change several ways.

    "the limit will increase to 1,000 pounds" and "the 1,000-pound trip limit
    will remain in effect" are the same fact. Collapse on the rule identity,
    keeping the record that names a gear -- an unattributed limit is the
    weaker reading of the same sentence.
    """
    best: dict[tuple, dict] = {}
    for n in notices:
        k = (n["effective_date"], n["species_key"], n["change_type"],
             (n["amount"] or {}).get("value"), n["period"])
        prev = best.get(k)
        if prev is None:
            best[k] = n
        elif prev["sub_fishery"] is None and n["sub_fishery"] is not None:
            best[k] = n
    return list(best.values())


def _record(eff, name, key, change, amt, gear, period, succ, conditional, quote) -> dict:
    """Assemble a notice in exactly the shape `reconcile` consumes."""
    undated_end = bool(UNDATED_END.search(quote))
    return {
        "effective_date": eff,
        "species": name, "species_key": key,
        # Every advisory in this corpus is commercial. DMF publishes
        # recreational changes separately, so this is not inferred from prose
        # the way RIDEM's is -- an unstated mode would be a parser bug here.
        "license_mode": "commercial" if "commercial" in quote.lower() else "unstated",
        "change_type": change,
        "amount": amt,
        "period": period,
        "aggregate_program": None,
        # Gear is Massachusetts' equivalent of RI's sub-fishery split, and
        # `reconcile._key` already keys on it.
        "sub_fishery": gear,
        # A conditional successor is NOT a supersession date. Leaving this
        # None is what stops `reconcile._promote` from asserting a limit that
        # DMF only said *might* happen.
        "superseded_on": None,
        "reopens_on": None,
        "successor": None if conditional else succ,
        "conditional_successor": succ if conditional else None,
        "state_vessels_only": False,
        "until_further_notice": undated_end,
        "quote": quote.strip()[:240],
        "parser": "rule",
        "jurisdiction": "MA",
    }
