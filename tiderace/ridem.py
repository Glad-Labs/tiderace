"""Deterministic parser for RIDEM in-season notices.

No model touches this. RIDEM writes its quota notices to a template:

    Beginning 12:00AM on Sunday, August 30, 2026, the commercial possession
    limit for Black Sea Bass will be four hundred (400) pounds per day until
    further notice.

Two properties make rules strictly better than an LLM here:

  1. **It is a template.** Most notices differ only in date, species and
     number, so a regex reads them with perfect reproducibility and zero
     compute. Extraction never drifts between runs.

  2. **The number is written twice.** "four hundred (400)" carries its own
     checksum. Parsing both forms and requiring them to agree catches OCR
     noise, transcription slips and truncation -- a guarantee no language
     model can offer, because a model that misreads the digits will happily
     misread the words to match.

Anything the template does not cover is reported as unparsed rather than
guessed at, and can be passed to the LLM extractor as a fallback.
"""

from __future__ import annotations

import re
from datetime import date, datetime

MONTHS = {m.lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], 1)}

UNITS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
         "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
         "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
         "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
         "nineteen": 19}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
        "seventy": 70, "eighty": 80, "ninety": 90}
SCALES = {"hundred": 100, "thousand": 1000}

# Notices routinely carry their own expiry -- and not only closures. A
# possession limit does it too: "will be two thousand (2,000) pounds per day
# ... or until the next sub period begins on May 1, 2026 at ten thousand
# (10,000) pounds per week". Treating that as still in force in August reports
# an April rule as current. Closures were handled first; limits were not, which
# is why an expired scup notice looked like a disagreement with correct code. "will close, until the next
# sub-period begins on August 1, 2026" or "will close until further notice, or
# until the fishery re-opens on May 1, 2026". Reading only the closure and
# ignoring the reopen date reports a fishery as shut months after it opened --
# which is worse than saying nothing, because it stops you fishing a season
# that is legally open.
# A notice can be ended by something opening *or* closing: "until the next sub
# period begins on May 1" and "or until the program closes on April 30" are the
# same fact expressed from opposite ends.
SUPERSEDE = re.compile(
    r"(?i)\buntil\b[^.]{0,80}?\b(?:begins?|re-?opens?|resumes?|closes?|ends?|expires?)"
    r"\b[^.]{0,20}?\bon\s+"
    r"(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4})"
    # Most notices state the rule that takes over, which is the only place the
    # currently-in-force limit appears at all -- the amendments page lists
    # changes, not current state.
    r"(?P<tail>[^.]{0,120})?")
REOPEN = SUPERSEDE

NOTICE = re.compile(
    r"(?i)beginning\s+[\d:]+\s*[ap]\.?m\.?\s+on\s+"
    r"(?:\w+day,?\s+)?"
    r"(?P<month>[A-Za-z]+)\s+(?P<day>\d{1,2}),?\s+(?P<year>\d{4}),?\s+"
    r"(?P<body>.+?)(?:\.\s|$)")

SPECIES_HINTS = {
    "striped bass": "striped_bass", "bluefish": "bluefish",
    "summer flounder": "fluke", "fluke": "fluke", "scup": "scup",
    "black sea bass": "black_sea_bass", "tautog": "tautog",
}


def words_to_number(text: str) -> int | None:
    """Parse 'four hundred', 'ten thousand', 'twenty-five'."""
    tokens = re.split(r"[\s-]+", text.lower().strip())
    total = current = 0
    seen = False
    for t in tokens:
        if t in UNITS:
            current += UNITS[t]; seen = True
        elif t in TENS:
            current += TENS[t]; seen = True
        elif t in SCALES:
            if not seen and SCALES[t] >= 100:
                current = 1
            current *= SCALES[t]
            if SCALES[t] >= 1000:
                total += current; current = 0
            seen = True
        elif t in ("and", ""):
            continue
        else:
            return None
    return (total + current) if seen else None


# Built from the number vocabulary so the spelled-out group can only ever
# capture number words. A generic [A-Za-z\s-] run swallowed the whole clause
# ("t for Black Sea Bass will be four hundred"), which then failed to parse as
# a number and silently disabled the cross-check on every notice.
_NUMBER_WORD = "|".join(sorted(
    list(UNITS) + list(TENS) + list(SCALES) + ["and"], key=len, reverse=True))
AMOUNT = re.compile(
    rf"((?:\b(?:{_NUMBER_WORD})\b[\s-]*)+)\((?P<digits>\d[\d,]*)\)\s*"
    r"(?P<unit>pounds?|lbs?|fish|inches|inch)\b", re.I)


def parse_amount(body: str) -> dict | None:
    """Find a quantity written as words followed by digits in parentheses.

    Returns the value plus whether the two spellings agree. A disagreement is
    reported, never silently resolved -- if the page says "three hundred (400)"
    a human needs to look at it, not a parser.
    """
    m = AMOUNT.search(body)
    if not m:
        m2 = re.search(r"\b(\d[\d,]*)\s*(pounds?|lbs?|fish|inches|inch)\b", body, re.I)
        if not m2:
            return None
        return {"value": int(m2.group(1).replace(",", "")),
                "unit": m2.group(2).lower(), "cross_checked": False,
                "agrees": None}

    digits = int(m.group("digits").replace(",", ""))
    spelled = words_to_number(m.group(1))
    return {
        "value": digits,
        "unit": m.group("unit").lower(),
        "spelled": spelled,
        "cross_checked": spelled is not None,
        "agrees": (spelled == digits) if spelled is not None else None,
    }


def _species(body: str) -> tuple[str | None, str | None]:
    low = body.lower()
    for name, key in SPECIES_HINTS.items():
        if name in low:
            return name, key
    return None, None


def parse_notice(sentence: str) -> dict | None:
    m = NOTICE.search(sentence)
    if not m:
        return None
    month = MONTHS.get(m.group("month").lower())
    if not month:
        return None
    try:
        eff = date(int(m.group("year")), month, int(m.group("day")))
    except ValueError:
        return None

    body = m.group("body")
    low = body.lower()
    name, key = _species(body)

    # Require the verb form. Bare "close" appears inside reopen clauses and
    # in prose about closures, and matching it labelled possession-limit
    # notices as closures.
    if re.search(r"\bwill\s+close\b|\bshall\s+close\b|\bis\s+closed\b", low):
        change = "season_close"
    elif re.search(r"\bwill\s+(?:re-?)?open\b", low):
        change = "season_open"
    elif "possession limit" in low:
        change = "possession_limit"
    elif "minimum size" in low:
        change = "minimum_size"
    else:
        change = "other"

    mode = ("commercial" if "commercial" in low
            else "recreational" if "recreational" in low else "unstated")

    # Sub-fisheries share a species and publish different limits. Scup runs a
    # General Category and a Floating Fish Trap fishery, and on 1 April 2026
    # both were set to 2,000 lb/day -- identical numbers, different fisheries,
    # indistinguishable unless the name is carried through.
    sub = None
    if "floating fish trap" in low or "floating trap" in low:
        sub = "floating_fish_trap"
    elif "general category" in low:
        sub = "general_category"

    reopens = None
    successor = None
    rm = SUPERSEDE.search(body)
    if rm:
        rmonth = MONTHS.get(rm.group("month").lower())
        if rmonth:
            try:
                reopens = date(int(rm.group("year")), rmonth,
                               int(rm.group("day"))).isoformat()
            except ValueError:
                reopens = None
        tail = rm.group("tail") or ""
        if reopens:
            amt = parse_amount(tail)
            low_tail = tail.lower()
            successor = {
                "effective_date": reopens,
                "amount": amt,
                "period": ("per bi-week" if "bi-week" in low_tail
                           else "per day" if "per day" in low_tail
                           else "per week" if "per week" in low_tail else None),
                "unlimited": "unlimited" in low_tail,
                "closes": bool(re.search(r"(?i)\bcloses?\b", tail)) or
                          bool(re.search(r"(?i)program closes", body)),
            }
            if not amt and not successor["unlimited"]:
                successor = None

    amount = parse_amount(body)
    per = ("per bi-week" if "bi-week" in low or "biweek" in low
           else "per day" if re.search(r"per (vessel per )?day", low)
           else "per week" if "per week" in low or "/wk" in low else None)

    # The Aggregate Program is a separate, permit-required fishery. Its limits
    # are not the general commercial ones and must not be compared against them.
    prog = None
    if "aggregate" in low:
        prog = ("winter" if "winter" in low
                else "summer_fall" if "summer" in low or "fall" in low else "unknown")

    return {
        "effective_date": eff.isoformat(),
        "species": name, "species_key": key,
        "license_mode": mode, "change_type": change,
        "amount": amount, "period": per,
        "aggregate_program": prog,
        "sub_fishery": sub,
        # Named `superseded_on` rather than `reopens_on` because it expires
        # possession limits as well as closures.
        "superseded_on": reopens,
        "reopens_on": reopens,
        "successor": successor,
        "state_vessels_only": "state vessels only" in low,
        # "until further notice" only means indefinite when no reopen date is
        # given alongside it -- most notices say both.
        "until_further_notice": "until further notice" in low and not reopens,
        "quote": sentence.strip()[:240],
        "parser": "rule",
    }


def parse_page(text: str) -> dict:
    """Split a RIDEM page into notices and parse each one."""
    sentences = re.split(r"(?<=\.)\s+(?=Beginning)|\n", text)
    parsed, unparsed = [], []
    for s in sentences:
        s = s.strip()
        if not s or not re.match(r"(?i)^beginning\b", s):
            continue
        rec = parse_notice(s)
        (parsed if rec else unparsed).append(rec or s[:200])

    warnings = []
    for r in parsed:
        a = r.get("amount")
        if a and a.get("agrees") is False:
            warnings.append(
                f"{r['species']}: page says {a['spelled']} but writes ({a['value']}) "
                f"— check the source")
        if not r["species"]:
            warnings.append(f"unrecognised species in: {r['quote'][:70]}")

    return {"notices": parsed, "unparsed": unparsed, "warnings": warnings,
            "parsed_at": datetime.now().isoformat(timespec="seconds")}
