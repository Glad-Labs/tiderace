"""Deterministic parser for RIDEM's minimum sizes & possession limits table.

This is the other half of `ridem.py`, and it exists to retire the last job on
the regulation path that still needed a person. The in-season notices have been
read by template, played forward and applied unattended since early September;
the annual table was hand-typed into `regs.py`, so a change to it raised a flag
on the desk and then waited for somebody to retype it. Matt, 18 September 2026:
"nothing should require a human, regs included."

WHY A TABLE CAN BE MIRRORED WITHOUT A PERSON

`ridem.py` earns its licence with a redundancy checksum -- RIDEM writes "four
hundred (400)", the number twice, so a parse that disagrees with itself is
caught. This table does not repeat itself, so it needs a different guarantee,
and it has one: **structure**. Every value sits in a labelled cell of a grid.
The column header says what the number means, and `fetch.tables_in` recovers
the grid from the markup rather than from flattened text, so "400 lbs/day" is
known to be a possession limit because of where it is, not because of what it
looks like.

That is a genuinely different kind of evidence from a regex over prose, and it
is why this is mirroring rather than interpreting. What it is NOT is a licence
to guess: a row this module cannot read completely is refused, counted, and
shown. Refusing loudly is the whole safety model, because the failure that
costs money is a rule that comes out *looser* than the page said.

WHAT THE TABLE WILL NOT TELL YOU, AND SAYS SO ITSELF

The page carries its own disclaimer -- "Possession limits and open fisheries
are subject to change" and "For current COMMERCIAL POSSESSION LIMITS call
423-1920". So even a perfect parse of this table is not a guarantee about
today. That is a property of the source, not of the parser, and it is exactly
why the notices overlay exists and why the hotline stays on the strip. This
module supplies the annual baseline; `reconcile` and `applied` amend it with
anything RIDEM has published since, by effective date.

THE NAME IS NOT THE KEY

`SPECIES` maps RIDEM's common names to this project's keys explicitly, and
there is no fuzzy fallback anywhere in it. On 17 September 2026 the alias
lists this project already had resolved "False Albacore" to an Indo-Pacific
kawakawa and "grey trout" to a lake trout; a substring match against a table
that contains both "Cod" and "Coastal Sharks- Blacknose" would be worse. An
unrecognised row is refused by name, not approximated.

One row maps to three keys on purpose. "Coastal Sharks- Pelagic Group -
Porbeagle, common thresher, blue" is one rule covering three fish this project
scores, so it yields three records citing the one cell they came from.
"""

from __future__ import annotations

import re
from datetime import date

# The commercial table's species column, as RIDEM writes it, to this project's
# keys. Only fish the project actually knows are here; everything else on the
# page -- eel, shad, salmon, sturgeon, horseshoe crab, skate, herring, the
# shark groups with no project species in them -- is refused as `unknown
# species`, counted and listed rather than silently dropped, so that a fish
# being added to the project shows up as a row already waiting for it.
#
# Keys are matched against the species cell normalised by `_norm`: lowercased,
# collapsed whitespace, trailing "-" and punctuation removed. Matching is
# EXACT against this table. A near miss is a refusal.
SPECIES: dict[str, tuple[str, ...]] = {
    "black sea bass": ("black_sea_bass",),
    "bluefish": ("bluefish",),
    "cod": ("cod",),
    "spiny dogfish": ("dogfish",),
    "summer flounder (fluke)": ("fluke",),
    "haddock": ("haddock",),
    "monkfish": ("monkfish",),
    "pollock": ("pollock",),
    "scup": ("scup",),
    "striped bass": ("striped_bass",),
    "tautog": ("tautog",),
    "weakfish (squeteague)": ("weakfish",),
    "winter flounder": ("winter_flounder",),
    # Menhaden is split by the Management Area boundary rather than by gear,
    # and the two halves carry different numbers -- 120,000 lb/day inside was
    # the 14 September notice. The area rides in `sub_fishery`.
    "menhaden inside management area": ("menhaden",),
    "menhaden outside management area": ("menhaden",),
    # The shark groups. Only the three rows naming fish this project scores
    # are here; "Aggregated Large Coastal Sharks Group" and the rest name no
    # project species and are refused.
    "coastal sharks- pelagic shark group - shortfin mako": ("mako",),
    "coastal sharks- pelagic group - porbeagle, common thresher, blue":
        ("porbeagle", "thresher", "blue_shark"),
}

# The Management Area is a place, and the gear fisheries are gear. Both end up
# in `sub_fishery` because both split one species' rule into concurrent rules
# that must not overwrite each other -- the same reason reconcile's identity
# carries it.
#
# These are `ridem.py`'s spellings, not this module's, and that is the point.
# `reconcile._identity` keys on sub_fishery, so a table saying "general
# category" and a notice saying "general_category" are not the same rule as
# far as it is concerned: both survive, and scup ends up with 10,000 lbs/week
# and 50,000 lbs/day simultaneously in force with nothing to say which is
# live. Measured on the first combined run, 18 September 2026 -- it produced
# exactly that for scup, fluke, striped bass and menhaden. Two parsers reading
# one agency have to agree on the names of things.
SUBS = {
    "with exemption certificate": "with_exemption_certificate",
    "without exemption certificate": "without_exemption_certificate",
    "general category": "general_category",
    "floating trap": "floating_fish_trap",
    "floating traps": "floating_fish_trap",
    "floating fish trap": "floating_fish_trap",
    "floating fish traps": "floating_fish_trap",
    # Named on the page as part of the species, not the size cell.
    "menhaden inside management area": "inside_mma",
    "menhaden outside management area": "outside_mma",
    # Real sub-fisheries of species this project does not score. Mapped so
    # that adding skate or horseshoe crab later does not silently inherit a
    # free-text label that matches nothing the notices ever say.
    "wing fishery": "wing_fishery",
    "bait fishery": "bait_fishery",
    "biomedical fishery": "biomedical_fishery",
}

AREA_SUB = {k: v for k, v in SUBS.items() if k.startswith("menhaden ")}

# A sub-fishery written at the head of the SIZE cell rather than in the
# species cell. RIDEM does this for the species whose rule splits by gear or
# by certificate, and the label is the first line of the cell. The trailing
# ".*" is deliberate -- "Wing Fishery Minimum 22 inches" carries the label and
# then keeps talking -- and whatever it captures is looked up in SUBS rather
# than used as a name.
SIZE_SUB = re.compile(
    r"(?i)^(with(?:out)?\s+exemption\s+certificate"
    r"|general\s+categor\w+"
    r"|floating\s+(?:fish\s+)?traps?"
    r"|wing\s+fishery"
    r"|bait\s+fishery"
    r"|biomedical\s+fishery)\b")

REV = re.compile(r"(?i)\brev\.?\s*:?\s*(\d{1,2})/(\d{1,2})/(\d{4})")

# "9"", "12"", "2 1/4" shell height", "17" whole/ 11" tails". Only the plain
# form is taken; a compound size is refused rather than halved.
SIZE_PLAIN = re.compile(r'^(\d{1,2})(?:\s*(\d)/(\d))?\s*"\s*$')
NO_SIZE = re.compile(r"(?i)^(na|n/a|no\s+minimum(\s+size)?|none)\b")

# "400 lbs/day", "6,000 lbs/wk", "55 sharks/vsl/day", "10,000 lbs/week",
# "60 crabs/day", "25 eels/person/day". The unit and the period are both
# named in the cell, which is what makes this readable without a checksum.
AMOUNT = re.compile(
    r"(?i)^([\d,]+)\s*"
    r"(lbs?|pounds?|sharks?|crabs?|eels?|fish|bushels?|pecks?)\s*"
    r"/\s*([a-z/]+)\s*$")

PERIODS = {
    "day": "per day", "dy": "per day",
    "wk": "per week", "week": "per week",
    "vsl/day": "per vessel per day", "vsl/dy": "per vessel per day",
    "person/day": "per person per day", "vsl/wk": "per vessel per week",
    "trip": "per trip", "yr": "per year", "year": "per year",
}

OPEN_ENDED = re.compile(r"(?i)^(no\s+limit|unlimited)\b")
CLOSED = re.compile(r"(?i)^(closed|prohibited)\b")

# "1/1 - 12/31", "5/1 - 4/30", "9/16 -12/31", "1/1- 12/31".
RANGE = re.compile(r"\b(\d{1,2})\s*/\s*(\d{1,2})\s*[-–]\s*(\d{1,2})\s*/\s*(\d{1,2})\b")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip().lower().strip(" .")


def _cells(row: list[list[str]]) -> list[list[str]]:
    """Undo the colspan expansion, so column index means something again.

    `fetch.tables_in` repeats a spanned cell into every slot it covers, which
    is what it looks like on screen. The commercial table spans its size and
    limit columns across two slots each for layout, and not consistently: 37
    rows come out 6 wide, 4 come out 5 wide because one span is missing, and
    the full-width note comes out 7. Collapsing runs of identical neighbours
    turns all of them back into the 4 logical columns RIDEM actually drew, and
    the note into the 1 it actually is.
    """
    out: list[list[str]] = []
    for c in row:
        if not out or out[-1] != c:
            out.append(c)
    return out


def table_kind(rows: list[list[list[str]]]) -> str | None:
    """Which of the page's tables this is, by its header rather than its index.

    Reading these by position would be a bug waiting for an editor: the page
    carries three tables and nothing promises their order. The commercial one
    is the one whose header says so.
    """
    if not rows:
        return None
    head = " ".join(" ".join(c) for c in rows[0]).lower()
    if "species" not in head:
        return None
    if "possession" not in head and "limit" not in head:
        return None
    if "commercial" in head:
        return "commercial"
    if "resident limit" in head or "management area" in head:
        return "shellfish"
    return "recreational"


def rev_date(text: str) -> str | None:
    """The table's own revision date -- "Rev. 9/14/2026".

    Worth more than the page fingerprint it supplements. A fingerprint trips
    on a nav change or a new footer link and says "the limits table changed"
    when nothing in the table did; this is RIDEM stating when it last touched
    the content. It becomes the effective date of every rule read here, which
    is what lets `reconcile` decide correctly between the table and a notice
    published after it.
    """
    m = REV.search(text or "")
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(1)), int(m.group(2))).isoformat()
    except ValueError:
        return None


def _size(lines: list[str]) -> dict:
    """The size cell. `known` is the whole point of the return shape.

    "the page says there is no minimum" and "I could not read this cell" are
    different facts that both leave `inches` empty, and collapsing them is how
    a refusal turns into a permissive rule. Monkfish is the live case: its
    cell is '17" whole/' + '11" tail', two sizes for two products with no
    honest way to pick one, and the first version of this module refused it
    and then emitted a rule with no minimum size anyway.
    """
    sub = None
    parts = [ln for ln in lines if ln.strip()]
    if not parts:
        return {"inches": None, "known": False, "sub": None,
                "reason": "empty size cell"}
    m = SIZE_SUB.match(parts[0])
    if m:
        label = _norm(m.group(1))
        # Normalised through SUBS or refused. Passing the label through as
        # free text is what put "general category" beside the notices'
        # "general_category" and left both rules in force.
        sub = SUBS.get(label) or SUBS.get(label.rstrip("s"))
        if not sub:
            return {"inches": None, "known": False, "sub": None,
                    "reason": "unknown sub-fishery: %r" % label[:40]}
        rest = parts[0][m.end():].strip()
        parts = ([rest] if rest else []) + parts[1:]
        if not parts:
            return {"inches": None, "known": False, "sub": sub,
                    "reason": "size cell is only a sub-fishery label"}
    head = parts[0].strip()
    if NO_SIZE.match(head):
        return {"inches": None, "known": True, "sub": sub, "reason": None}
    m = SIZE_PLAIN.match(head)
    if m and len(parts) == 1:
        inches = float(m.group(1))
        if m.group(2) and m.group(3):
            inches += int(m.group(2)) / int(m.group(3))
        return {"inches": inches, "known": True, "sub": sub, "reason": None}
    return {"inches": None, "known": False, "sub": sub,
            "reason": "size not plain: %r" % " / ".join(parts)[:60]}


# "CLOSED Fri/Sat/Sun/Mon" -- the striped bass general-category fishery is
# shut four days a week all season, and `regs.CommercialRule` has
# `closed_weekdays` for exactly this. A season read without it says the
# fishery is open on a Saturday when it is not, which is a loosening.
DAYS = {"mon": 0, "tue": 1, "tues": 1, "wed": 2, "thu": 3, "thur": 3,
        "thurs": 3, "fri": 4, "sat": 5, "sun": 6}
CLOSED_DAYS = re.compile(r"(?i)closed\s+((?:%s)(?:\s*/\s*(?:%s))*)"
                         % ("|".join(DAYS), "|".join(DAYS)))
# Words that carry no date and are safe to ignore when deciding whether the
# cell was fully understood. Anything NOT in here and not a range is residue.
SEASON_FILLER = re.compile(
    r"(?i)\b(sub-?periods?|fed\s+quota|thru-?out|throughout|open|and|or|"
    r"season|all\s+year|year\s*round)\b|[()/,.:;-]|\s+")


def _season(lines: list[str]) -> dict:
    text = " ".join(lines)
    periods, residue = [], text
    for m in RANGE.finditer(text):
        a = (int(m.group(1)), int(m.group(2)))
        b = (int(m.group(3)), int(m.group(4)))
        if 1 <= a[0] <= 12 and 1 <= b[0] <= 12 and 1 <= a[1] <= 31 and 1 <= b[1] <= 31:
            periods.append((a, b))
    residue = RANGE.sub(" ", residue)

    days: list[int] = []
    for m in CLOSED_DAYS.finditer(text):
        for d in re.split(r"\s*/\s*", m.group(1)):
            if d.strip().lower() in DAYS:
                days.append(DAYS[d.strip().lower()])
    residue = CLOSED_DAYS.sub(" ", residue)

    left = SEASON_FILLER.sub("", residue).strip()
    return {"periods": tuple(periods), "closed_weekdays": tuple(sorted(set(days))),
            "known": bool(periods) and not left,
            "reason": None if (periods and not left) else
                      ("no date range in %r" % text[:60] if not periods
                       else "unread text in season: %r" % left[:40])}


def _limit(lines: list[str]) -> dict:
    """The possession-limit cell.

    `kind` is explicit for the same reason `_size` has `known`: "No limit" is
    a rule RIDEM published and "I could not read this" is not, and rendering
    both as an absent amount is how monkfish's 4,900 lbs/wk became no limit
    at all.
    """
    parts = [ln for ln in lines if ln.strip()]
    if not parts:
        return {"kind": "unreadable", "reason": "empty limit cell"}
    head = parts[0].strip()
    # A second line is a second rule -- "4,900 lbs/wk tails or" + "14,259
    # lbs/week whole fish" -- so a cell with more than one is refused even
    # when its first line parses perfectly.
    if len(parts) > 1:
        return {"kind": "unreadable",
                "reason": "more than one limit: %r" % " / ".join(parts)[:60]}
    if CLOSED.match(head):
        return {"kind": "closed", "reason": None}
    if OPEN_ENDED.match(head):
        return {"kind": "none", "reason": None}
    m = AMOUNT.match(head)
    if m:
        try:
            value = int(m.group(1).replace(",", ""))
        except ValueError:
            return {"kind": "unreadable", "reason": "unreadable number: %r" % head[:60]}
        unit = m.group(2).lower().rstrip("s") + "s"
        per = PERIODS.get(_norm(m.group(3)).replace(" ", ""))
        if per is None:
            return {"kind": "unreadable", "reason": "unknown period: %r" % head[:60]}
        return {"kind": "amount", "amount": {"value": value, "unit": unit},
                "period": per, "reason": None}
    return {"kind": "unreadable", "reason": "limit not plain: %r" % head[:60]}


def parse_commercial(rows: list[list[list[str]]], url: str,
                     effective: str | None) -> dict:
    """The commercial table -> rules, notes and refusals.

    Everything returned carries the cell it was read from. Nothing here is
    anonymous, because a number of unknown origin sitting beside a cited one
    is the failure this whole path exists to avoid.
    """
    rules: list[dict] = []
    notes: list[dict] = []
    refused: list[dict] = []

    for row in rows[1:]:
        cells = _cells(row)
        # A single cell spanning the full width is a note about the table, not
        # a row of it -- the winter flounder spatial closure in Narragansett
        # Bay is one, and dropping it would lose a rule that applies to the
        # water this app is about.
        if len(cells) == 1:
            text = " ".join(cells[0]).strip()
            if len(text) > 30:
                notes.append({"text": text, "source_url": url})
            continue
        if len(cells) != 4:
            refused.append({"reason": "row is not 4 columns",
                            "cells": len(cells),
                            "quote": " ".join(" ".join(c) for c in cells)[:160]})
            continue

        sp_cell, size_cell, season_cell, limit_cell = cells
        name = _norm(" ".join(sp_cell))
        keys = SPECIES.get(name)
        if not keys:
            refused.append({"reason": "unknown species", "species": name[:80],
                            "quote": " ".join(" ".join(c) for c in cells)[:160]})
            continue

        size = _size(size_cell)
        lim = _limit(limit_cell)
        season = _season(season_cell)
        sub = AREA_SUB.get(name) or size["sub"]
        quote = " · ".join(" ".join(c) for c in cells)[:400]

        for field, why in (("size", size["reason"]), ("limit", lim["reason"]),
                           ("season", season["reason"])):
            if why:
                refused.append({"reason": why, "species": name[:80],
                                "field": field, "quote": quote})

        for key in keys:
            rules.append({
                "species_key": key,
                "species": " ".join(sp_cell)[:80],
                "license_mode": "commercial",
                "sub_fishery": sub,
                "aggregate_program": None,
                "effective_date": effective,
                # Each field says whether it was READ, not merely whether it
                # has a value. A consumer that ignores these flags will turn
                # every refusal above into a rule with no minimum size, no
                # closed season and no possession limit -- the most permissive
                # reading possible of a page it failed to understand.
                "min_inches": size["inches"],
                "size_known": size["known"],
                "periods": season["periods"],
                "closed_weekdays": season["closed_weekdays"],
                "season_known": season["known"],
                "limit_kind": lim["kind"],
                "amount": lim.get("amount"),
                "period": lim.get("period"),
                "closed": lim["kind"] == "closed",
                "limit_known": lim["kind"] != "unreadable",
                "limit_text": " ".join(limit_cell)[:120],
                "size_text": " ".join(size_cell)[:120],
                "season_text": " ".join(season_cell)[:160],
                "source_url": url,
                "quote": quote,
                "parser": "table",
            })

    return {"rules": rules, "notes": notes, "refused": refused}


def parse_page(tables: list, text: str, url: str) -> dict:
    """Every table on the limits page, classified and read.

    The `refused` list is not diagnostics. It is the part of the page this
    module declined to turn into a rule, and the interface shows its size: a
    parser that quietly read 30 of 41 rows and reported success would be the
    most dangerous thing in the project.
    """
    out = {"rev": rev_date(text), "url": url, "commercial": None,
           "kinds": [], "rules": [], "notes": [], "refused": [],
           "warnings": []}

    for rows in tables or []:
        kind = table_kind(rows)
        out["kinds"].append(kind)
        if kind != "commercial":
            continue
        if out["commercial"] is not None:
            out["warnings"].append("more than one commercial table on the page")
            continue
        got = parse_commercial(rows, url, out["rev"])
        out["commercial"] = len(rows) - 1
        out["rules"] = got["rules"]
        out["notes"] = got["notes"]
        out["refused"] = got["refused"]

    if out["commercial"] is None:
        out["warnings"].append(
            "no commercial table found — the page shape changed, and nothing "
            "was read rather than something being guessed")
    if not out["rev"]:
        out["warnings"].append(
            "no 'Rev. m/d/yyyy' on the page — rules have no effective date and "
            "cannot be ordered against the notices, so none were applied")
        out["rules"] = []
    return out
