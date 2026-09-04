"""Your own marks, and the Spot every scorer takes.

Until 3 September 2026 this file was a list of nineteen named landmarks --
reef, point, bridge -- and the app ranked those. Matt: that is not the goal.
The goal is for the system to come up with the coordinates itself, for a
species and the conditions, and a curated list cannot do that: every entry
was somebody's choice, and a piece of bottom two hundred metres from one
that nobody named was invisible to a ranking built from the list.

So the list is gone. `prospect.candidates_for` finds the positions now, from
the charted soundings, and binds and scores each one like any other Spot.
What is left here is the type they all share, the parser for a coordinate
you typed, the resolver that turns one into a Spot with its stations bound,
and your own marks -- the one set of positions that is still a person's
choice, because they are yours.

`quality`, `best_stage` and `species` survive on the dataclass for marks:
hand-entered local priors, conventional wisdom, never measurement, waiting
on the catch log. A prospected candidate carries none of them and scores on
the water and the bottom alone.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


def coord_key(lat: float, lon: float) -> str:
    """The one key scheme. A curated position, a private mark you saved
    without naming it, and a point you tapped on the map all key the same
    way, so the same piece of water is the same key however you got there."""
    return f"at:{lat:.5f},{lon:.5f}"


@dataclass(frozen=True)
class Spot:
    lat: float
    lon: float
    current_station: str          # CO-OPS current-prediction station (verified live)
    tide_station: str             # CO-OPS water-level station
    kind: str
    notes: str = ""
    species: tuple[str, ...] = field(default_factory=tuple)
    quality: dict[str, float] = field(default_factory=dict)   # species -> 0..1 prior
    best_stage: str | None = None          # "ebb" | "flood" | None
    wx_point: tuple[float, float] | None = None  # land point for NWS grid
    # Water temperature rides on the water-level stations, but not all of them
    # carry a thermometer. Defaults to the tide station, which is right for
    # everything in the bay and wrong up the Providence River.
    temp_station: str | None = None
    private: bool = False                  # your mark, not a prospected candidate
    # Charted depth at a prospected candidate, feet. None for a mark. It is
    # the one term the scorer reads per position rather than per station,
    # and only for a species with a published depth band.
    depth_ft: float | None = None
    # Defaults to the coordinate. A private mark may carry the handle you
    # typed at `--save`, because that is what the catch log links it by; a
    # prospected candidate never does.
    key: str = ""

    def __post_init__(self):
        if not self.key:
            object.__setattr__(self, "key", coord_key(self.lat, self.lon))

    @property
    def label(self) -> str:
        """What every ranking, listing and card calls this place."""
        return f"{self.lat:.4f}, {self.lon:.4f}"

    @property
    def thermometer(self) -> str:
        return self.temp_station or self.tide_station

    def prior(self, species: str) -> float:
        return self.quality.get(species, 0.6)


# --------------------------------------------------------------- your marks
#
# The first thing anyone says when they hear about an app like this is "don't
# give away my good spots". The positions the forecast ranks are prospected
# from public soundings and give nothing away; your own marks are a
# different matter entirely.
#
# So private marks live in a gitignored file that nothing in this project ever
# transmits: no sharing, no sync, no export by default. Weather lookups for
# them are coarsened to ~1 km before they reach NOAA (see sources._coarse), so
# even the one unavoidable outbound call does not carry the real position.

PRIVATE_PATH = os.environ.get(
    "TIDERACE_SPOTS",
    os.path.join(os.path.dirname(__file__), "..", "data", "my_spots.json"))


def load_private(path: str | None = None) -> list[Spot]:
    """Load your own marks. Missing or malformed file is never fatal."""
    path = path or PRIVATE_PATH
    if not os.path.exists(path):
        return []
    try:
        with open(path) as fh:
            raw = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return []

    out = []
    for r in raw if isinstance(raw, list) else raw.get("spots", []):
        # A "name" in the file is ignored. Older files carry one; it never
        # reaches a ranking, a card or a listing -- the position does.
        try:
            out.append(Spot(
                key=r.get("key") or "",
                lat=float(r["lat"]), lon=float(r["lon"]),
                current_station=r["current_station"],
                tide_station=r.get("tide_station", "8452660"),   # Newport
                kind=r.get("kind", "mark"), notes=r.get("notes", ""),
                species=tuple(r.get("species", ())),
                quality=r.get("quality", {}),
                best_stage=r.get("best_stage"),
                wx_point=tuple(r["wx_point"]) if r.get("wx_point") else None,
                temp_station=r.get("temp_station"),
                private=True,
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return out


# Everything in SPOTS is yours. There is no public list any more.
SPOTS: list[Spot] = load_private()
BY_KEY = {s.key: s for s in SPOTS}


def get(key: str) -> Spot:
    if key not in BY_KEY:
        raise KeyError(f"unknown spot {key!r}; known: {', '.join(sorted(BY_KEY))}")
    return BY_KEY[key]


# ----------------------------------------------------------- ad-hoc coordinates
#
# A coordinate you type is a spot like any other -- the scorer, the feature
# builder and the window finder all take a Spot and none of them care where it
# came from. Binding the stations is the whole job, and `stations.resolve`
# does it.

def parse_coord(text: str) -> tuple[float, float]:
    """Accept the forms people actually have on their phone and chartplotter.

        41.4408,-71.4228        41.4408 -71.4228
        41 26.448 N, 71 25.368 W
        41°26'26.9"N 71°25'22.1"W

    Longitude in Rhode Island is negative, and a positive one is nearly always
    a dropped minus sign -- but "nearly" is not "always", so this parses what
    you typed rather than second-guessing it. `stations.resolve` is where a
    mark outside the charted area gets said out loud, because that is the
    layer that knows how far away the nearest real data is.
    """
    import re
    t = text.strip().replace("°", " ").replace("'", " ").replace('"', " ")
    t = t.replace("’", " ").replace("′", " ").replace("″", " ")

    hemis = re.findall(r"[NSEWnsew]", t)
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", t)]
    if len(nums) < 2:
        raise ValueError(f"could not read a coordinate from {text!r}")

    def dms(parts: list[float]) -> float:
        v = abs(parts[0]) + (parts[1] if len(parts) > 1 else 0) / 60.0 \
            + (parts[2] if len(parts) > 2 else 0) / 3600.0
        return -v if parts[0] < 0 else v

    if len(nums) in (4, 6):                     # two groups of dm or dms
        half = len(nums) // 2
        lat, lon = dms(nums[:half]), dms(nums[half:])
    elif len(nums) == 2:
        lat, lon = nums
    else:
        raise ValueError(f"ambiguous coordinate {text!r}")

    if len(hemis) >= 2:
        if hemis[0].upper() == "S":
            lat = -abs(lat)
        if hemis[1].upper() == "W":
            lon = -abs(lon)

    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError(f"{lat},{lon} is not a coordinate")
    return round(lat, 6), round(lon, 6)


def at_coord(lat: float, lon: float, resolution: dict | None = None,
             kind: str = "mark", notes: str | None = None,
             depth_ft: float | None = None, private: bool = True):
    """Build a one-off Spot for a coordinate, with its stations resolved.

    Returns (spot, resolution) so the caller can print the caveats. Marked
    private and deliberately *not* registered in SPOTS or BY_KEY: a coordinate
    you typed is not a saved mark until you save it.

    No prior and no preferred tide stage, because there is no local knowledge
    for a point nobody has fished yet. `Spot.prior` returns 0.6 by default,
    which is the honest answer.
    """
    from . import stations
    res = resolution or stations.resolve(lat, lon)
    cur = res.get("current") or {}
    tide = res.get("tide") or {}
    temp = res.get("temp") or {}
    if not cur or not tide:
        raise ValueError(f"no NOAA stations near {lat},{lon}")

    spot = Spot(
        lat=lat, lon=lon,
        current_station=cur["id"],
        tide_station=tide["id"],
        temp_station=temp.get("id"),
        kind=kind,
        notes=notes or f"current from {cur['name']} ({cur['distance_nm']} nm)",
        depth_ft=depth_ft,
        species=tuple(sorted(__import__("tiderace.score", fromlist=["PROFILES"])
                             .PROFILES)),
        quality={},
        best_stage=None,
        wx_point=None,
        # A coordinate you typed or tapped is yours. A prospected candidate
        # is public soundings and says so, which is what lets the page tell
        # "your mark" from "prospected structure" on the card.
        private=private,
    )
    return spot, res
