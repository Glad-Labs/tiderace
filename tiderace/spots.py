"""Narragansett Bay fishing spots, each bound to the NOAA stations that
actually describe it.

The important design choice: every spot carries a *current* station, not just
a tide station. Tide height at Newport tells you almost nothing about whether
water is ripping past Whale Rock. Current does. This is the single biggest
edge over the generic national fishing apps, which key everything off one
tide-height curve.

`quality` and `best_stage` are hand-entered local priors -- conventional
wisdom, not measurement. They exist to be overwritten by your catch log.
Every station id below was verified live against CO-OPS.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Spot:
    key: str
    name: str
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
    private: bool = False                  # your mark, not a public landmark

    @property
    def thermometer(self) -> str:
        return self.temp_station or self.tide_station

    def prior(self, species: str) -> float:
        return self.quality.get(species, 0.6)


NEWPORT, CONIMICUT, PROVIDENCE = "8452660", "8452944", "8454000"

SPOTS: list[Spot] = [
    Spot("whale_rock", "Whale Rock", 41.4408, -71.4228, "ACT2201", NEWPORT,
         "reef", "West Passage mouth. Ledge to 40 ft. The ebb rip is the draw.",
         ("striped_bass", "bluefish", "black_sea_bass"),
         {"striped_bass": 0.98, "bluefish": 0.85, "black_sea_bass": 0.70},
         "ebb", (41.4494, -71.3997)),   # Beavertail SP -- nearest land grid
    Spot("beavertail", "Beavertail Point", 41.4494, -71.3997, "ACT2201", NEWPORT,
         "point", "Rip forms off the point on the drop. Heavy water.",
         ("striped_bass", "bluefish", "tautog"),
         {"striped_bass": 0.94, "bluefish": 0.80, "tautog": 0.85},
         "ebb", (41.4494, -71.3997)),
    Spot("castle_hill", "Castle Hill", 41.4622, -71.3628, "ACT2101", NEWPORT,
         "point", "East Passage mouth. Deep edge tight to shore.",
         ("striped_bass", "bluefish", "tautog"),
         {"striped_bass": 0.92, "bluefish": 0.78, "tautog": 0.80},
         "ebb", (41.4622, -71.3628)),
    Spot("brenton_reef", "Brenton Reef", 41.4256, -71.3611, "ACT2096", NEWPORT,
         "reef", "Open-ocean reef SW of Newport. Exposed to south swell.",
         ("striped_bass", "bluefish", "black_sea_bass"),
         {"striped_bass": 0.86, "bluefish": 0.88, "black_sea_bass": 0.90},
         None, (41.4519, -71.3572)),   # Brenton Point SP -- nearest land grid
    Spot("fort_wetherill", "Fort Wetherill", 41.4761, -71.3617, "ACT2106", NEWPORT,
         "shore", "Deep water from the rocks. Reliable night shore spot.",
         ("striped_bass", "tautog", "scup"),
         {"striped_bass": 0.82, "tautog": 0.92, "scup": 0.80},
         "ebb", (41.4761, -71.3617)),
    # was ACT2201 (Beavertail): there is a station in the cove itself.
    Spot("mackerel_cove", "Mackerel Cove", 41.4750, -71.3800, "ACT2111", NEWPORT,
         "cove", "Sheltered Jamestown cove. Bait stacks up on a SW blow.",
         ("striped_bass", "bluefish", "scup"),
         {"striped_bass": 0.62, "bluefish": 0.70, "scup": 0.75},
         None, (41.4750, -71.3800)),
    Spot("rose_island", "Rose Island", 41.5033, -71.3317, "ACT2121", NEWPORT,
         "island", "Current seams around the island. Boat only.",
         ("striped_bass", "bluefish", "scup"),
         {"striped_bass": 0.74, "bluefish": 0.70, "scup": 0.78},
         None, (41.5033, -71.3317)),
    Spot("gould_island", "Gould Island", 41.5250, -71.3367, "ACT2136", NEWPORT,
         "island", "Rips off both ends. Steady summer striper spot.",
         ("striped_bass", "bluefish", "fluke"),
         {"striped_bass": 0.80, "bluefish": 0.72, "fluke": 0.70},
         None, (41.5250, -71.3367)),
    Spot("dutch_island", "Dutch Island", 41.5050, -71.4100, "ACT2216", NEWPORT,
         "island", "West Passage gut. Big tide push through the narrows.",
         ("striped_bass", "tautog", "fluke", "scup"),
         {"striped_bass": 0.88, "tautog": 0.86, "fluke": 0.72, "scup": 0.76},
         "ebb", (41.5050, -71.4100)),
    Spot("dyer_island", "Dyer Island", 41.5750, -71.2967, "ACT2146", CONIMICUT,
         "island", "Mid-bay. The classic fluke drift; bass work the edges.",
         ("striped_bass", "fluke", "scup"),
         {"striped_bass": 0.70, "fluke": 0.92, "scup": 0.82},
         None, (41.5750, -71.2967)),
    Spot("mount_hope", "Mount Hope Bridge", 41.6400, -71.2583, "ACT2166", CONIMICUT,
         "bridge", "Pilings plus a narrow channel. Night bite under the lights.",
         ("striped_bass", "tautog", "scup"),
         {"striped_bass": 0.90, "tautog": 0.88, "scup": 0.74},
         None, (41.6400, -71.2583)),
    Spot("hog_island", "Hog Island", 41.6467, -71.2950, "ACT2171", CONIMICUT,
         "island", "Upper-bay structure that holds fish through summer.",
         ("striped_bass", "scup", "fluke"),
         {"striped_bass": 0.68, "scup": 0.80, "fluke": 0.66},
         None, (41.6467, -71.2950)),
    Spot("quonset", "Quonset Point", 41.5834, -71.3957, "nb0301", CONIMICUT,
         "point", "West side. Warms early -- good on the spring run.",
         ("striped_bass", "fluke", "scup"),
         {"striped_bass": 0.66, "fluke": 0.74, "scup": 0.78},
         "flood", (41.5834, -71.3957)),
    # was nb0301 (Quonset Point): Wickford Harbor has its own station.
    Spot("wickford", "Wickford Harbor", 41.5667, -71.4333, "ACT2226", CONIMICUT,
         "harbor", "Shallow, warms fast. Spring and fall schoolies.",
         ("striped_bass", "scup", "fluke"),
         {"striped_bass": 0.58, "scup": 0.76, "fluke": 0.60},
         "flood", (41.5667, -71.4333)),
    # was ACT2241: ACT2231 is the entrance itself.
    Spot("greenwich_bay", "Greenwich Bay Entrance", 41.6667, -71.3933, "ACT2231", CONIMICUT,
         "bay", "Shallow warm bay. Early season, then it shuts off in the heat.",
         ("striped_bass", "scup"),
         {"striped_bass": 0.50, "scup": 0.72},
         "flood", (41.6667, -71.3933)),
    Spot("conimicut", "Conimicut Point", 41.7167, -71.3433, "ACT2246", CONIMICUT,
         "point", "Upper-bay shoal. Spring run and fall blitzes.",
         ("striped_bass", "bluefish"),
         {"striped_bass": 0.72, "bluefish": 0.76},
         "flood", (41.7167, -71.3433)),
    Spot("sakonnet_black_pt", "Black Point, Sakonnet", 41.5067, -71.2200, "ACT2071", NEWPORT,
         "point", "Sakonnet River. Less pressure than the passages.",
         ("striped_bass", "bluefish", "tautog"),
         {"striped_bass": 0.78, "bluefish": 0.74, "tautog": 0.82},
         "ebb", (41.5067, -71.2200)),
    Spot("pt_judith_breachway", "Point Judith Pond Breachway", 41.3833, -71.5167,
         "ACT2276", NEWPORT,
         "breachway", "Hard outflow through the breachway -- up to 2 kt.",
         ("striped_bass", "bluefish", "fluke"),
         {"striped_bass": 0.90, "bluefish": 0.82, "fluke": 0.76},
         "ebb", (41.3833, -71.5167)),
    Spot("harbor_of_refuge", "Harbor of Refuge", 41.3580, -71.4958, "ACT2266", NEWPORT,
         "breakwater", "The walls. Ocean access, structure, big fish potential.",
         ("striped_bass", "bluefish", "fluke", "black_sea_bass", "tautog"),
         {"striped_bass": 0.88, "bluefish": 0.86, "fluke": 0.80,
          "black_sea_bass": 0.84, "tautog": 0.86},
         None, (41.3730, -71.4958)),
]

# --------------------------------------------------------------- your marks
#
# The nineteen spots above are public landmarks — they are on every chart and
# in every guidebook, so naming them gives nothing away. Your own marks are a
# different matter entirely, and the first thing anyone says when they hear
# about an app like this is "don't give away my good spots".
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
        try:
            out.append(Spot(
                key=r["key"], name=r["name"],
                lat=float(r["lat"]), lon=float(r["lon"]),
                current_station=r["current_station"],
                tide_station=r.get("tide_station", NEWPORT),
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


SPOTS.extend(load_private())

BY_KEY = {s.key: s for s in SPOTS}


def get(key: str) -> Spot:
    if key not in BY_KEY:
        raise KeyError(f"unknown spot {key!r}; known: {', '.join(sorted(BY_KEY))}")
    return BY_KEY[key]


def for_species(species: str) -> list[Spot]:
    return [s for s in SPOTS if species in s.species]


def public_only() -> list[Spot]:
    """Everything except your own marks. The only set anything shareable
    should ever be built from."""
    return [s for s in SPOTS if not s.private]


# ----------------------------------------------------------- ad-hoc coordinates
#
# A coordinate you type is a spot like any other -- the scorer, the feature
# builder and the window finder all take a Spot and none of them care where it
# came from. The only thing standing between "19 curated places" and "anywhere
# on the water" was binding the stations, which `stations.resolve` now does.

def parse_coord(text: str) -> tuple[float, float]:
    """Accept the forms people actually have on their phone and chartplotter.

        41.4408,-71.4228        41.4408 -71.4228
        41 26.448 N, 71 25.368 W
        41°26'26.9"N 71°25'22.1"W

    Longitude in Rhode Island is negative. A positive one is a typo every
    time, and silently fishing the Yellow Sea is a worse failure than an error.
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


def at_coord(lat: float, lon: float, name: str | None = None,
             resolution: dict | None = None):
    """Build a one-off Spot for a coordinate, with its stations resolved.

    Returns (spot, resolution) so the caller can print the caveats. Marked
    private and deliberately *not* registered in SPOTS or BY_KEY: a coordinate
    you typed is a mark, and marks do not join the public list.

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
        key=f"at:{lat:.5f},{lon:.5f}",
        name=name or f"{lat:.4f}, {lon:.4f}",
        lat=lat, lon=lon,
        current_station=cur["id"],
        tide_station=tide["id"],
        temp_station=temp.get("id"),
        kind="mark",
        notes=f"current from {cur['name']} ({cur['distance_nm']} nm)",
        species=tuple(sorted(__import__("tiderace.score", fromlist=["PROFILES"])
                             .PROFILES)),
        quality={},
        best_stage=None,
        wx_point=None,
        private=True,
    )
    return spot, res
