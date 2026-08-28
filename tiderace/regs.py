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

from dataclasses import dataclass, field
from datetime import date

SOURCE = "https://www.eregulations.com/rhodeisland/fishing/saltwater/size-season-possession-limits"
CHECKED_ON = date(2026, 8, 28)
STALE_AFTER_DAYS = 120


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


def status(species: str, when: date | None = None) -> dict:
    when = when or date.today()
    r = RULES.get(species)
    if not r:
        return {"known": False}
    age = (date.today() - CHECKED_ON).days
    return {
        "known": True,
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


def summary_line(species: str, when: date | None = None) -> str:
    s = status(species, when)
    if not s["known"]:
        return ""
    bits = [s["season"]]
    if s["slot"]:
        bits.append(f'slot {s["slot"][0]:.0f}–{s["slot"][1]:.0f}"')
    elif s["min_inches"]:
        bits.append(f'min {s["min_inches"]:.0f}"')
    if s["bag"]:
        bits.append(s["bag"])
    return " · ".join(bits)
