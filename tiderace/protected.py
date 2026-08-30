"""Protected species constraints. Rules, never signals.

`whales.py` treats a humpback as evidence about bait. This module is the other
half of the same subject and it does the opposite job: it says what you are
not allowed to do, and it never touches the score. A right whale is not a
fishing opportunity, and a module that let one raise a number would be exactly
the kind of quietly wrong this project keeps trying to avoid.

Two different rules, and the difference matters because only one of them
actually binds a small boat:

  **500 yards, all vessels.** 50 CFR 224.103(c). It is illegal to approach
  within 500 yards of a North Atlantic right whale by vessel or aircraft, of
  any size, anywhere in US waters. If you find yourself inside it you must
  steer away and leave at a slow safe speed. This one applies to you.

  **10 knots, vessels 65 ft and over.** 50 CFR 224.105. The Seasonal
  Management Areas below carry a mandatory 10-knot limit for vessels "greater
  than or equal to 65 ft (19.8 m) in overall length". A recreational boat is
  under that, so the speed limit is very probably not binding on you -- and
  saying so plainly is better than implying a rule that does not apply.

So why carry the SMAs at all? Because the polygon is the government telling
you where right whales are expected in a given season. For a small boat the
useful reading is not "slow down", it is "the 500-yard rule is live here, and
a dark back surfacing near you is more likely to be the one you must not
approach".

The dynamic Slow Zones are deliberately not modelled. They move on days of
notice from acoustic detections, and the live feed (WhaleMap / the Right Whale
Sighting Advisory System) needs per-contributor permission rather than being
open data. A stale polygon presented as current is worse than no polygon, so
this ships the part that is fixed in regulation and points at the live source
for the part that is not.

Boundaries transcribed from 50 CFR 224.105 via Cornell LII, checked 2026-08-30.
"""

from __future__ import annotations

from datetime import date

# Where to look for what this module deliberately does not model.
SLOW_ZONE_SOURCE = "https://www.fisheries.noaa.gov/national/endangered-species-conservation/reducing-vessel-strikes-north-atlantic-right-whales"
WHALEMAP = "https://whalemap.org/"

APPROACH_YARDS = 500
APPROACH_NM = 500 / 2025.372          # yards to nautical miles
SPEED_RULE_MIN_LOA_FT = 65
SPEED_LIMIT_KT = 10


def _dms(d: float, m: float, s: float, hemi: str) -> float:
    v = d + m / 60.0 + s / 3600.0
    return -v if hemi in ("S", "W") else v


# Seasonal Management Areas, northeast US. Each is (polygon, first day, last
# day) with the season given as (month, day) so it can be tested in any year.
# A season that wraps the new year is handled in `_in_season`.
#
# Polygons are the regulation's coordinates in order. Cape Cod Bay and Off
# Race Point are bounded in part by the mean high water line, which is not a
# coordinate list -- their polygons here close across the water instead, which
# is very slightly larger than the true area. That errs toward warning, which
# is the right direction for a rule.
SMAS = [
    {
        "name": "Block Island Sound",
        "season": ((11, 1), (4, 30)),
        "polygon": [
            (_dms(40, 51, 53.7, "N"), _dms(70, 36, 44.9, "W")),
            (_dms(41, 20, 14.1, "N"), _dms(70, 49, 44.1, "W")),
            (_dms(41, 4, 16.7, "N"), _dms(71, 51, 21.0, "W")),
            (_dms(40, 35, 56.5, "N"), _dms(71, 38, 25.1, "W")),
        ],
        "note": "Covers the Block Island wind farm and the run out to it.",
    },
    {
        "name": "Cape Cod Bay",
        "season": ((1, 1), (5, 15)),
        "polygon": [
            (_dms(42, 4, 56.5, "N"), _dms(70, 12, 0.0, "W")),
            (_dms(42, 12, 0.0, "N"), _dms(70, 12, 0.0, "W")),
            (_dms(42, 12, 0.0, "N"), _dms(70, 40, 0.0, "W")),
            (_dms(41, 47, 0.0, "N"), _dms(70, 40, 0.0, "W")),
        ],
        "note": "Closed westward on the mean high water line; approximated here.",
    },
    {
        "name": "Off Race Point",
        "season": ((3, 1), (4, 30)),
        "polygon": [
            (_dms(42, 30, 0.0, "N"), _dms(69, 45, 0.0, "W")),
            (_dms(42, 30, 0.0, "N"), _dms(70, 30, 0.0, "W")),
            (_dms(42, 12, 0.0, "N"), _dms(70, 30, 0.0, "W")),
            (_dms(42, 12, 0.0, "N"), _dms(70, 12, 0.0, "W")),
            (_dms(42, 4, 56.5, "N"), _dms(70, 12, 0.0, "W")),
            (_dms(41, 40, 0.0, "N"), _dms(70, 12, 0.0, "W")),
            (_dms(41, 41, 0.0, "N"), _dms(69, 45, 0.0, "W")),
        ],
        "note": "Partly bounded by mean high water; approximated here.",
    },
    {
        "name": "Great South Channel",
        "season": ((4, 1), (7, 31)),
        "polygon": [
            (_dms(42, 30, 0.0, "N"), _dms(69, 45, 0.0, "W")),
            (_dms(41, 40, 0.0, "N"), _dms(69, 45, 0.0, "W")),
            (_dms(41, 0, 0.0, "N"), _dms(69, 5, 0.0, "W")),
            (_dms(42, 9, 0.0, "N"), _dms(67, 8, 24.0, "W")),
            (_dms(42, 30, 0.0, "N"), _dms(67, 27, 0.0, "W")),
        ],
        "note": "",
    },
]


def _in_polygon(lat: float, lon: float, poly: list[tuple[float, float]]) -> bool:
    """Ray casting. Points are (lat, lon); the ray is cast in longitude.

    These polygons are tens of miles across at 41N, where treating lat/lon as
    a plane is wrong by a fraction of a percent -- far inside the slop already
    introduced by closing two of them across open water.
    """
    inside = False
    n = len(poly)
    for i in range(n):
        alat, alon = poly[i]
        blat, blon = poly[(i + 1) % n]
        if (alat > lat) != (blat > lat):
            x = alon + (lat - alat) * (blon - alon) / (blat - alat)
            if lon < x:
                inside = not inside
    return inside


def _in_season(on: date, season: tuple[tuple[int, int], tuple[int, int]]) -> bool:
    (m1, d1), (m2, d2) = season
    start, end, cur = (m1, d1), (m2, d2), (on.month, on.day)
    if start <= end:
        return start <= cur <= end
    return cur >= start or cur <= end          # wraps the new year


def _season_text(season) -> str:
    (m1, d1), (m2, d2) = season
    mon = ("", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
    return f"{mon[m1]} {d1} – {mon[m2]} {d2}"


def areas_at(lat: float, lon: float, on: date | None = None) -> list[dict]:
    """Seasonal Management Areas containing this point.

    Returns every area whose polygon contains the point, in season or not, so
    a caller can say "you are in one, but not until November" rather than
    silently reporting nothing in August.
    """
    on = on or date.today()
    out = []
    for sma in SMAS:
        if not _in_polygon(lat, lon, sma["polygon"]):
            continue
        out.append({
            "name": sma["name"],
            "season": _season_text(sma["season"]),
            "active": _in_season(on, sma["season"]),
            "note": sma["note"],
        })
    return out


def advisory(lat: float, lon: float, on: date | None = None,
             vessel_loa_ft: float | None = None) -> dict:
    """What the protected-species rules mean at this place, on this day.

    `vessel_loa_ft` is optional and only changes whether the 10-knot rule is
    reported as binding. Left unset, the answer says the rule exists and names
    the threshold rather than guessing at your boat.
    """
    on = on or date.today()
    areas = areas_at(lat, lon, on)
    active = [a for a in areas if a["active"]]
    speed_binds = (None if vessel_loa_ft is None
                   else vessel_loa_ft >= SPEED_RULE_MIN_LOA_FT)

    rules = [
        f"Approach: {APPROACH_YARDS} yards from any North Atlantic right whale. "
        "All vessels, any size, all US waters (50 CFR 224.103(c)). Inside it, "
        "steer away and leave at slow safe speed."
    ]
    if active:
        names = ", ".join(a["name"] for a in active)
        if speed_binds is True:
            rules.append(f"Speed: 10 kt or less in {names} — your vessel is at or "
                         f"over the {SPEED_RULE_MIN_LOA_FT} ft threshold.")
        elif speed_binds is False:
            rules.append(f"Speed: the 10 kt limit in {names} applies to vessels "
                         f"{SPEED_RULE_MIN_LOA_FT} ft and over, so not to yours. "
                         "The 500-yard rule still does.")
        else:
            rules.append(f"Speed: 10 kt or less in {names} for vessels "
                         f"{SPEED_RULE_MIN_LOA_FT} ft and over.")

    return {
        "areas": areas,
        "active": active,
        "in_active_sma": bool(active),
        "approach_yards": APPROACH_YARDS,
        "approach_nm": round(APPROACH_NM, 4),
        "speed_rule_min_loa_ft": SPEED_RULE_MIN_LOA_FT,
        "speed_rule_binds": speed_binds,
        "rules": rules,
        "not_modelled": ("Dynamic Slow Zones move on days of notice and are not "
                         "modelled here — check " + SLOW_ZONE_SOURCE),
        "live_sightings": WHALEMAP,
    }


def describe(adv: dict) -> list[str]:
    """Lines for a human. Deliberately plain: this is law, not a forecast."""
    out = list(adv["rules"])
    dormant = [a for a in adv["areas"] if not a["active"]]
    for a in dormant:
        out.append(f"In the {a['name']} SMA, but out of season ({a['season']}).")
    return out
