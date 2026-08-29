"""Rhode Island marine fishing regulations.

A forecast that ranks a species during a closed season is not merely wrong,
it is telling you to break the law and pressure a fishery when it is supposed
to be left alone. The scorer knows about water temperature and current; it has
no idea what is legal. This module is that missing half.

IMPORTANT -- these values are transcribed by hand, they change every year, and
they are not authoritative. RIDEM amends them mid-season. Treat what follows
as a prompt to go and check, never as the answer. `SOURCE` and `CHECKED_ON`
exist so that staleness is visible rather than silent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

SOURCE = "https://www.eregulations.com/rhodeisland/fishing/saltwater/size-season-possession-limits"
CHECKED_ON = date(2026, 8, 28)
STALE_AFTER_DAYS = 120

# --------------------------------------------------------------- commercial
#
# Commercial is not a variant of recreational, it is a different regime, and it
# is far more dangerous to hardcode.
#
# Recreational limits are set annually and hold for the season. Commercial
# limits are quota-managed and move *mid-season, on days of notice*: the
# general-category striped bass fishery closed on 23 June 2026 "until further
# notice", and the summer flounder limit steps from 300 lb/day to 100 lb/day
# on 16 September. RIDEM states plainly that keeping up with those changes is
# the licence holder's responsibility, and publishes a phone line for the
# current numbers.
#
# So the split below is deliberate: **minimum sizes are reasonably stable and
# are encoded; possession limits and open/closed state are volatile and are
# treated as advisory.** The staleness window is two weeks rather than four
# months, and the hotline is printed every single time.

COMMERCIAL_SOURCE = ("https://dem.ri.gov/natural-resources-bureau/marine-fisheries/"
                     "marine-fisheries-minimum-sizes-possession-limits")
COMMERCIAL_HOTLINE = "(401) 423-1920"
COMMERCIAL_CHECKED_ON = date(2026, 8, 28)
COMMERCIAL_STALE_AFTER_DAYS = 14


@dataclass(frozen=True)
class Rule:
    species: str
    open_periods: tuple[tuple[tuple[int, int], tuple[int, int]], ...]  # ((m,d),(m,d))
    min_inches: float | None = None
    max_inches: float | None = None
    slot: tuple[float, float] | None = None
    bag: str = ""
    note: str = ""

    def is_open(self, when: date) -> bool:
        md = (when.month, when.day)
        return any(a <= md <= b for a, b in self.open_periods)

    def next_change(self, when: date) -> str:
        """Human description of the next season boundary."""
        md = (when.month, when.day)
        for a, b in self.open_periods:
            if a <= md <= b:
                return f"open through {b[0]:02d}/{b[1]:02d}"
        upcoming = [a for a, _ in self.open_periods if a > md]
        if upcoming:
            n = min(upcoming)
            return f"closed until {n[0]:02d}/{n[1]:02d}"
        return "closed for the rest of the year"


YEAR_ROUND = (((1, 1), (12, 31)),)

RULES: dict[str, Rule] = {
    "striped_bass": Rule(
        "striped_bass", YEAR_ROUND, slot=(28, 31),
        bag="1 fish/person/day",
        note="Slot limit. Anything outside 28–31 in must be released."),
    "bluefish": Rule(
        "bluefish", YEAR_ROUND,
        bag="5/person/day shore or private; 7 party/charter",
        note="No minimum size."),
    "tautog": Rule(
        "tautog", (((4, 1), (5, 31)), ((8, 1), (12, 31))),
        min_inches=16,
        bag="3/person/day Apr–May and Aug–14 Oct; 5/person/day 15 Oct–Dec",
        note="Closed 1 June – 31 July. Max one fish over 21 in."),
    "fluke": Rule(
        "fluke", (((4, 1), (12, 31)),), min_inches=19,
        bag="6/person/day"),
    "scup": Rule(
        "scup", (((5, 1), (12, 31)),), min_inches=11,
        bag="30/person/day; 40 in Sept–Oct",
        note="Shore minimum is 9.5 in at designated shore sites."),
    "black_sea_bass": Rule(
        "black_sea_bass", (((5, 16), (12, 31)),), min_inches=16,
        bag="3/person/day shore or private; more for party/charter"),
}


@dataclass(frozen=True)
class CommercialRule:
    species: str
    min_inches: float | None
    periods: tuple[tuple[tuple[int, int], tuple[int, int]], ...]
    limit: str = ""
    closed_weekdays: tuple[int, ...] = ()       # 0 = Monday
    quota_closed: bool = False                  # closed in-season until notice
    note: str = ""

    def is_open(self, when: date) -> bool:
        if self.quota_closed:
            return False
        if when.weekday() in self.closed_weekdays:
            return False
        md = (when.month, when.day)
        return any(a <= md <= b for a, b in self.periods)

    def why_closed(self, when: date) -> str | None:
        if self.quota_closed:
            return "quota closed until further notice"
        if when.weekday() in self.closed_weekdays:
            names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            return (f"closed on {names[when.weekday()]} — this fishery is closed "
                    + "/".join(names[d] for d in sorted(self.closed_weekdays)))
        md = (when.month, when.day)
        if not any(a <= md <= b for a, b in self.periods):
            upcoming = [a for a, _ in self.periods if a > md]
            if upcoming:
                n = min(upcoming)
                return f"between sub-periods — next opens {n[0]:02d}/{n[1]:02d}"
            return "closed for the rest of the year"
        return None


COMMERCIAL: dict[str, CommercialRule] = {
    "striped_bass": CommercialRule(
        "striped_bass", 34.0, (((6, 2), (12, 31)),),
        limit="general category — see hotline",
        closed_weekdays=(4, 5, 6, 0),          # Fri, Sat, Sun, Mon
        quota_closed=True,
        note="General category closed 23 Jun 2026 until further notice. "
             "Note the minimum is 34 in — LARGER than the recreational slot, "
             "not smaller."),
    "tautog": CommercialRule(
        "tautog", 16.0,
        (((4, 1), (5, 31)), ((8, 1), (9, 15)), ((10, 15), (12, 31))),
        limit="10 fish/day",
        note="Sub-periods differ from the recreational season."),
    "fluke": CommercialRule(
        "fluke", 14.0,
        (((1, 1), (4, 30)), ((5, 1), (9, 15)), ((9, 16), (12, 31))),
        limit="300 lb/day with Exemption Certificate, 200 lb/day without; "
              "steps down 16 Sep",
        note="Minimum is 14 in commercially against 19 in recreationally."),
    "scup": CommercialRule(
        "scup", 9.0, (((1, 1), (12, 31)),),
        limit="10,000 lb/week general category; floating traps unlimited",
        note="Sub-periods vary by category."),
    "black_sea_bass": CommercialRule(
        "black_sea_bass", 11.0, (((1, 1), (12, 31)),),
        limit="300 lb/day",
        note="Minimum is 11 in commercially against 16 in recreationally."),
    "bluefish": CommercialRule(
        "bluefish", 18.0,
        (((1, 1), (4, 30)), ((5, 1), (11, 15)), ((11, 16), (12, 31))),
        limit="6,000 lb/week",
        note="Commercial carries an 18 in minimum where recreational has none."),
}


# ------------------------------------------------------- the Aggregate Program
#
# A permit-required commercial programme that pools a daily limit into a longer
# landing window. It appears nowhere on RIDEM's limits table -- everything below
# is transcribed from in-season notices, which is a weaker source than the rest
# of this file and should be treated accordingly.
#
# The Summer/Fall limit is deliberately stored as a **multiplier, not a
# poundage**. The notices say "seven (7) times the daily limit, or two thousand
# eight hundred (2,800) pounds per week" -- the 2,800 is derived from a 400
# lb/day base, so hardcoding it would go stale the moment the daily limit moves,
# which it does several times a season. Storing the multiplier makes the weekly
# figure follow the daily one automatically.
#
# Participation is opt-in and permitted annually, so nothing here applies unless
# `aggregate_program` is set in config. An unenrolled vessel fishing to these
# numbers would be over its limit.

@dataclass(frozen=True)
class AggregatePeriod:
    key: str
    name: str
    species: tuple[str, ...]
    window: tuple[tuple[int, int], tuple[int, int]] | None
    multiplier: float | None = None          # x the daily limit
    fixed_amount: str | None = None          # when not a multiple of the daily
    unit: str = "per week"
    note: str = ""

    def is_open(self, when: date) -> bool:
        if self.window is None:
            return False
        md = (when.month, when.day)
        return self.window[0] <= md <= self.window[1]


AGGREGATE: dict[str, AggregatePeriod] = {
    "summer_fall": AggregatePeriod(
        "summer_fall", "Summer/Fall Aggregate Program",
        species=("fluke", "black_sea_bass"),
        # The notices give no explicit start; the winter programme closes
        # 30 April, and the summer/fall notices run into December.
        window=((5, 1), (12, 31)),
        multiplier=7.0, unit="per week",
        note="Weekly limit is seven times the daily limit, permitted vessels "
             "only. Black sea bass was amended from six to seven times daily "
             "for the 16 Oct - 31 Dec sub-period."),
    "winter": AggregatePeriod(
        "winter", "Winter Aggregate Program",
        species=("fluke",),
        window=((3, 15), (4, 30)),
        fixed_amount="6,000 lb", unit="per bi-week",
        note="Winter I was closed from 1 January 2026 and reopened 15 March at "
             "6,000 lb per bi-week; the programme closes 30 April. Summer "
             "flounder only."),
}


def aggregate_status(species: str, program: str,
                     when: date | None = None) -> dict:
    """What the Aggregate Program adds for a species, if enrolled."""
    when = when or date.today()
    ap = AGGREGATE.get(program)
    if not ap or species not in ap.species:
        return {"applies": False}

    base = COMMERCIAL.get(species)
    daily = None
    if base and ap.multiplier:
        m = re.search(r"(\d[\d,]*)\s*lb/day", base.limit or "")
        if m:
            daily = int(m.group(1).replace(",", ""))

    if ap.multiplier:
        derived = (f"{ap.multiplier:g}x daily"
                   + (f" = {int(daily * ap.multiplier):,} lb {ap.unit}"
                      if daily else f" {ap.unit}"))
    else:
        derived = f"{ap.fixed_amount} {ap.unit}"

    return {
        "applies": True,
        "program": ap.name,
        "open": ap.is_open(when),
        "limit": derived,
        "multiplier": ap.multiplier,
        "note": ap.note,
        "permit_required": True,
    }


def commercial_status(species: str, when: date | None = None,
                      program: str | None = None) -> dict:
    when = when or date.today()
    r = COMMERCIAL.get(species)
    if not r:
        return {"known": False}
    age = (date.today() - COMMERCIAL_CHECKED_ON).days
    closed_reason = r.why_closed(when)
    return {
        "known": True,
        "mode": "commercial",
        "open": closed_reason is None,
        "season": closed_reason or "open",
        "min_inches": r.min_inches,
        "slot": None,
        "bag": r.limit,
        "note": r.note,
        "quota_closed": r.quota_closed,
        "source": COMMERCIAL_SOURCE,
        "hotline": COMMERCIAL_HOTLINE,
        "checked_on": COMMERCIAL_CHECKED_ON.isoformat(),
        "stale": age > COMMERCIAL_STALE_AFTER_DAYS,
        "days_since_checked": age,
        # Unlike recreational, this is never presented as settled.
        "advisory": True,
        "aggregate": (aggregate_status(species, program, when)
                      if program and program != "none" else {"applies": False}),
    }


def status(species: str, when: date | None = None,
           mode: str = "recreational", program: str | None = None) -> dict:
    if mode == "commercial":
        return commercial_status(species, when, program)

    when = when or date.today()
    r = RULES.get(species)
    if not r:
        return {"known": False}
    age = (date.today() - CHECKED_ON).days
    return {
        "known": True,
        "mode": "recreational",
        "open": r.is_open(when),
        "season": r.next_change(when),
        "min_inches": r.min_inches,
        "slot": r.slot,
        "bag": r.bag,
        "note": r.note,
        "source": SOURCE,
        "checked_on": CHECKED_ON.isoformat(),
        "stale": age > STALE_AFTER_DAYS,
        "days_since_checked": age,
    }


def summary_line(species: str, when: date | None = None,
                 mode: str = "recreational", program: str | None = None) -> str:
    s = status(species, when, mode, program)
    if not s["known"]:
        return ""
    bits = [s["season"]]
    if s.get("slot"):
        bits.append(f'slot {s["slot"][0]:.0f}–{s["slot"][1]:.0f}"')
    elif s.get("min_inches"):
        bits.append(f'min {s["min_inches"]:.0f}"')
    if s.get("bag"):
        bits.append(s["bag"])
    agg = s.get("aggregate") or {}
    if agg.get("applies") and agg.get("open"):
        bits.append(f"{agg['program']}: {agg['limit']}")
    return " · ".join(bits)


def differences(species: str, when: date | None = None) -> list[str]:
    """Where the two regimes disagree. Showing the wrong column is the whole
    risk of adding commercial rules at all."""
    rec, com = status(species, when), status(species, when, "commercial")
    if not rec.get("known") or not com.get("known"):
        return []
    out = []
    if rec.get("slot") and com.get("min_inches"):
        out.append(f'size: rec slot {rec["slot"][0]:.0f}–{rec["slot"][1]:.0f}" '
                   f'vs commercial min {com["min_inches"]:.0f}"')
    elif rec.get("min_inches") != com.get("min_inches"):
        r = f'{rec["min_inches"]:.0f}"' if rec.get("min_inches") else "none"
        c = f'{com["min_inches"]:.0f}"' if com.get("min_inches") else "none"
        out.append(f"size: rec {r} vs commercial {c}")
    if rec.get("open") != com.get("open"):
        out.append(f'open: rec {"yes" if rec["open"] else "no"} '
                   f'vs commercial {"yes" if com["open"] else "no"}')
    return out
