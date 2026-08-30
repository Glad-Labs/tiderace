"""Atlantic Highly Migratory Species — federal rules for the offshore trip.

The inshore regulations module covers what Rhode Island manages. Tuna, marlin
and swordfish are not that: they are federal, managed by NOAA Fisheries under
the HMS programme, and they carry a permit requirement that RI licences do not
satisfy.

This exists because `tiderace offshore` will happily report that 88 bluefin
have been recorded near the wind farm, and saying nothing about whether one may
be kept is exactly the defect the tautog closure exposed inshore.

**Volatility warning, and it is worse here than for the state commercial
rules.** NOAA adjusts Angling-category bluefin retention limits in-season by
notice in the Federal Register, and billfish share a single national landings
limit of 250 fish a year across three species. A number transcribed today can
be wrong next week without anything looking different. So minimum sizes are
encoded — they are stable — and retention is advisory with the source printed
every time.

Nothing here is legal advice, and NOAA says plainly that where a summary and
the Code of Federal Regulations disagree, the CFR wins.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

SOURCE = ("https://www.fisheries.noaa.gov/atlantic-highly-migratory-species/"
          "atlantic-highly-migratory-species-fishery-statuses-minimum-sizes")
PERMIT_URL = "https://hmspermits.noaa.gov/"
LANDINGS_URL = ("https://www.fisheries.noaa.gov/atlantic-highly-migratory-species/"
                "atlantic-highly-migratory-species-landings-updates")
CHECKED_ON = date(2026, 8, 29)
STALE_AFTER_DAYS = 14

PERMIT = ("HMS Angling permit (or HMS Charter/Headboat). It covers the vessel, "
          "not the angler, and a state licence does not substitute.")


@dataclass(frozen=True)
class Rule:
    species: str
    common: str
    min_inches: float | None
    measure: str                       # how the length is taken
    bag: str
    note: str = ""
    size_classes: tuple[tuple[str, float, float | None], ...] = ()
    volatile: bool = False             # retention adjusted in-season


RULES: dict[str, Rule] = {
    "bluefin": Rule(
        "Thunnus thynnus", "bluefin tuna", 27.0, "curved fork length",
        bag="2 per vessel per day, 27 to under 73 in — only ONE of those "
            "may be 47 to under 73 in",
        size_classes=(("school", 27.0, 47.0),
                      ("large school / small medium", 47.0, 73.0),
                      ("trophy", 73.0, None)),
        note="Angling category, private vessel. Limit set 1 Jun 2026 and runs "
             "to 31 Dec unless NOAA adjusts it. Per vessel per day regardless "
             "of trip length. Retained or dead-discarded bluefin must be "
             "reported within 24 hours.",
        volatile=True),
    "yellowfin": Rule(
        "Thunnus albacares", "yellowfin tuna", 27.0, "curved fork length",
        bag="3 per person per day"),
    "bigeye": Rule(
        "Thunnus obesus", "bigeye tuna", 27.0, "curved fork length",
        bag="no limit"),
    "albacore": Rule(
        "Thunnus alalunga", "albacore", None, "—", bag="no limit"),
    "skipjack": Rule(
        "Katsuwonus pelamis", "skipjack", None, "—", bag="no limit"),
    "blue marlin": Rule(
        "Makaira nigricans", "blue marlin", 99.0, "lower-jaw fork length",
        bag="counts against a national limit",
        note="Blue marlin, white marlin and roundscale spearfish share ONE "
             "national landings limit of 250 fish a year. Check landings "
             "before keeping one.",
        volatile=True),
    "white marlin": Rule(
        "Kajikia albida", "white marlin", 66.0, "lower-jaw fork length",
        bag="counts against a national limit",
        note="Shares the 250-fish national limit with blue marlin and "
             "roundscale spearfish.",
        volatile=True),
    "roundscale spearfish": Rule(
        "Tetrapturus georgii", "roundscale spearfish", 66.0,
        "lower-jaw fork length", bag="counts against a national limit",
        note="Shares the 250-fish national limit.", volatile=True),
    "swordfish": Rule(
        "Xiphias gladius", "swordfish", 47.0,
        "lower-jaw fork length (or 25 in cleithrum to caudal keel)",
        bag="1 per person, max 4 per vessel per trip (HMS Angling)",
        note="Either measurement may be used. Swordfish may NOT be retained "
             "if hammerhead or oceanic whitetip sharks are aboard."),
    "sailfish": Rule(
        "Istiophorus platypterus", "sailfish", 63.0, "lower-jaw fork length",
        bag="see current status"),
}

# Managed elsewhere, and worth saying so rather than staying silent.
NOT_HMS = {
    "mahi": "Dolphin (mahi) and wahoo are not HMS — they sit under the "
            "Dolphin Wahoo FMP. A 20 in fork length minimum applies through "
            "much of the Atlantic; confirm what applies off Rhode Island "
            "before keeping one, because this module has not verified it.",
    "wahoo": "See mahi — Dolphin Wahoo FMP, not HMS.",
}


def status(species: str, when: date | None = None) -> dict:
    when = when or date.today()
    key = species.lower().strip()
    if key in NOT_HMS:
        return {"known": False, "managed_elsewhere": True,
                "note": NOT_HMS[key], "source": SOURCE}
    r = RULES.get(key)
    if not r:
        return {"known": False}
    age = (date.today() - CHECKED_ON).days
    return {
        "known": True, "common": r.common, "scientific": r.species,
        "min_inches": r.min_inches, "measure": r.measure, "bag": r.bag,
        "note": r.note, "size_classes": r.size_classes,
        "permit": PERMIT, "permit_url": PERMIT_URL,
        "volatile": r.volatile,
        "source": SOURCE, "landings": LANDINGS_URL,
        "checked_on": CHECKED_ON.isoformat(),
        "days_since_checked": age,
        "stale": age > STALE_AFTER_DAYS,
        "advisory": True,
    }


def classify(species: str, inches: float) -> str | None:
    """Which size class a bluefin falls in — the distinction the bag limit
    turns on, and the one that is easy to get wrong on a rolling deck."""
    r = RULES.get(species.lower().strip())
    if not r or not r.size_classes:
        return None
    for name, lo, hi in r.size_classes:
        if inches >= lo and (hi is None or inches < hi):
            return name
    return "under the minimum — must be released"


def summary_line(species: str) -> str:
    s = status(species)
    if not s.get("known"):
        return s.get("note", "")
    bits = []
    if s["min_inches"]:
        bits.append(f'min {s["min_inches"]:.0f}" {s["measure"]}')
    else:
        bits.append("no minimum size")
    bits.append(s["bag"])
    return " · ".join(bits)
