"""Positions on Narragansett Bay, each bound to the NOAA stations that
actually describe it.

The important design choice: every position carries a *current* station, not
just a tide station. Tide height at Newport tells you almost nothing about
whether water is ripping over a ledge at the mouth of the West Passage.
Current does. This is the single biggest edge over the generic national
fishing apps, which key everything off one tide-height curve.

There are no names here, and that is deliberate (3 September 2026). The app
began as a ranking of nineteen named landmarks -- reef, point, bridge, each
with a name off the chart -- and the name was doing work the coordinate should
have been doing: the rankings said a landmark when what you need on the boat
is a position to steer to. A name is also a claim about identity that a
coordinate is not: two marks a few hundred metres apart are two pieces of
water, and one name straddling both hid that. So a spot is a coordinate. Its
key IS its coordinate (`coord_key`), the same scheme `at_coord` uses for a
point you tap, and every ranking reports the position and nothing else.

What each position still carries: the hand-verified station binding, a `kind`,
a note about the water, and the local priors below. `quality` and
`best_stage` are hand-entered -- conventional wisdom, not measurement. They
exist to be overwritten by your catch log. Every station id below was
verified live against CO-OPS.

`species` is the same tier of claim as `quality`, and it became load-bearing
on 2026-09-02 when score.PROFILES went from six species to fourteen. Two
things follow, and they pull in opposite directions on purpose:

  * `for_species` no longer returns an empty list for a fish nobody listed.
    It returns every position, because "nobody wrote down where this one is"
    and "this one is nowhere" are different facts and the empty list said the
    second while meaning the first. See the docstring on that function.
  * Bonito and false albacore ARE listed, on six positions, and that is a
    deliberate exception rather than the start of filling all fourteen in.
    They are the one group whose distribution inside this bay is sharply
    uneven in a way conventional wisdom is confident about: a mouth-and-ocean
    fish, effectively never caught above the bridges. Letting them fall back
    to every position would put albies seven miles up a bay they do not enter.

    What that claim rests on, stated so it can be argued with: the six
    positions given them are the ocean-facing structures at or outside the
    mouth. It is angling knowledge, not measurement. The one piece of
    published support is indirect: [ASGA-LT] tabulates Rhode Island little
    tunny catch as 85% state waters and 63% shore-based, which says the
    fishery is inshore and structure-bound without saying which structure.
    The `quality` numbers are pure priors, like every other number in this
    file. Nothing else was curated, because for weakfish, winter flounder,
    mackerel, squid, dogfish and searobin the honest answer is that the
    distribution is either broad or unrecorded.
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
    private: bool = False                  # your mark, not a public position
    # Defaults to the coordinate. A private mark may carry the handle you
    # typed at `--save`, because that is what the catch log links it by; the
    # public positions never do.
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


NEWPORT, CONIMICUT, PROVIDENCE = "8452660", "8452944", "8454000"
# The north-east arm is its own water. The upper-bay gauge sits around the
# corner in the Providence River and reads about a degree cooler; Fall River
# is in the same water as the bridge.
FALL_RIVER = "8447386"

SPOTS: list[Spot] = [
    Spot(41.4408, -71.4228, "ACT2201", NEWPORT,
         "reef", "West Passage mouth. Ledge to 40 ft. The ebb rip is the draw.",
         ("striped_bass", "bluefish", "black_sea_bass",
          "bonito", "false_albacore"),
         {"striped_bass": 0.98, "bluefish": 0.85, "black_sea_bass": 0.70,
          "bonito": 0.70, "false_albacore": 0.72},
         "ebb", (41.4494, -71.3997)),   # state park on the point -- nearest land grid
    Spot(41.4494, -71.3997, "ACT2201", NEWPORT,
         "point", "Rip forms off the point on the drop. Heavy water.",
         ("striped_bass", "bluefish", "tautog",
          "bonito", "false_albacore"),
         {"striped_bass": 0.94, "bluefish": 0.80, "tautog": 0.85,
          "bonito": 0.78, "false_albacore": 0.80},
         "ebb", (41.4494, -71.3997)),
    Spot(41.4622, -71.3628, "ACT2101", NEWPORT,
         "point", "East Passage mouth. Deep edge tight to shore.",
         ("striped_bass", "bluefish", "tautog",
          "bonito", "false_albacore"),
         {"striped_bass": 0.92, "bluefish": 0.78, "tautog": 0.80,
          "bonito": 0.74, "false_albacore": 0.76},
         "ebb", (41.4622, -71.3628)),
    Spot(41.4256, -71.3611, "ACT2096", NEWPORT,
         "reef", "Open-ocean reef SW of Newport. Exposed to south swell.",
         ("striped_bass", "bluefish", "black_sea_bass",
          "bonito", "false_albacore"),
         {"striped_bass": 0.86, "bluefish": 0.88, "black_sea_bass": 0.90,
          "bonito": 0.86, "false_albacore": 0.88},
         None, (41.4519, -71.3572)),   # state park on the shore -- nearest land grid
    Spot(41.4761, -71.3617, "ACT2106", NEWPORT,
         "shore", "Deep water from the rocks. Reliable night shore spot.",
         ("striped_bass", "tautog", "scup"),
         {"striped_bass": 0.82, "tautog": 0.92, "scup": 0.80},
         "ebb", (41.4761, -71.3617)),
    # was ACT2201 (the point to the south): there is a station in the cove itself.
    Spot(41.4750, -71.3800, "ACT2111", NEWPORT,
         "cove", "Sheltered island cove. Bait stacks up on a SW blow.",
         ("striped_bass", "bluefish", "scup"),
         {"striped_bass": 0.62, "bluefish": 0.70, "scup": 0.75},
         None, (41.4750, -71.3800)),
    Spot(41.5033, -71.3317, "ACT2121", NEWPORT,
         "island", "Current seams around the island. Boat only.",
         ("striped_bass", "bluefish", "scup"),
         {"striped_bass": 0.74, "bluefish": 0.70, "scup": 0.78},
         None, (41.5033, -71.3317)),
    Spot(41.5250, -71.3367, "ACT2136", NEWPORT,
         "island", "Rips off both ends. Steady summer striper spot.",
         ("striped_bass", "bluefish", "fluke"),
         {"striped_bass": 0.80, "bluefish": 0.72, "fluke": 0.70},
         None, (41.5250, -71.3367)),
    Spot(41.5050, -71.4100, "ACT2216", NEWPORT,
         "island", "West Passage gut. Big tide push through the narrows.",
         ("striped_bass", "tautog", "fluke", "scup"),
         {"striped_bass": 0.88, "tautog": 0.86, "fluke": 0.72, "scup": 0.76},
         "ebb", (41.5050, -71.4100)),
    Spot(41.5750, -71.2967, "ACT2146", CONIMICUT,
         "island", "Mid-bay. The classic fluke drift; bass work the edges.",
         ("striped_bass", "fluke", "scup"),
         {"striped_bass": 0.70, "fluke": 0.92, "scup": 0.82},
         None, (41.5750, -71.2967)),
    Spot(41.6400, -71.2583, "ACT2166", CONIMICUT,
         "bridge", "Pilings plus a narrow channel. Night bite under the lights.",
         ("striped_bass", "tautog", "scup"),
         {"striped_bass": 0.90, "tautog": 0.88, "scup": 0.74},
         None, (41.6400, -71.2583), temp_station=FALL_RIVER),
    Spot(41.6467, -71.2950, "ACT2171", CONIMICUT,
         "island", "Upper-bay structure that holds fish through summer.",
         ("striped_bass", "scup", "fluke"),
         {"striped_bass": 0.68, "scup": 0.80, "fluke": 0.66},
         None, (41.6467, -71.2950)),
    Spot(41.5834, -71.3957, "nb0301", CONIMICUT,
         "point", "West side. Warms early -- good on the spring run.",
         ("striped_bass", "fluke", "scup"),
         {"striped_bass": 0.66, "fluke": 0.74, "scup": 0.78},
         "flood", (41.5834, -71.3957)),
    # was nb0301 (the point to the north): the harbor has its own station.
    Spot(41.5667, -71.4333, "ACT2226", CONIMICUT,
         "harbor", "Shallow, warms fast. Spring and fall schoolies.",
         ("striped_bass", "scup", "fluke"),
         {"striped_bass": 0.58, "scup": 0.76, "fluke": 0.60},
         "flood", (41.5667, -71.4333)),
    # was ACT2241: ACT2231 is the entrance itself.
    Spot(41.6667, -71.3933, "ACT2231", CONIMICUT,
         "bay", "Shallow warm bay. Early season, then it shuts off in the heat.",
         ("striped_bass", "scup"),
         {"striped_bass": 0.50, "scup": 0.72},
         "flood", (41.6667, -71.3933)),
    Spot(41.7167, -71.3433, "ACT2246", CONIMICUT,
         "point", "Upper-bay shoal. Spring run and fall blitzes.",
         ("striped_bass", "bluefish"),
         {"striped_bass": 0.72, "bluefish": 0.76},
         "flood", (41.7167, -71.3433)),
    Spot(41.5067, -71.2200, "ACT2071", NEWPORT,
         "point", "The eastern river. Less pressure than the passages.",
         ("striped_bass", "bluefish", "tautog"),
         {"striped_bass": 0.78, "bluefish": 0.74, "tautog": 0.82},
         "ebb", (41.5067, -71.2200)),
    Spot(41.3833, -71.5167,
         "ACT2276", NEWPORT,
         "breachway", "Hard outflow through the breachway -- up to 2 kt.",
         ("striped_bass", "bluefish", "fluke",
          "bonito", "false_albacore"),
         {"striped_bass": 0.90, "bluefish": 0.82, "fluke": 0.76,
          "bonito": 0.80, "false_albacore": 0.84},
         "ebb", (41.3833, -71.5167)),
    Spot(41.3580, -71.4958, "ACT2266", NEWPORT,
         "breakwater", "The walls. Ocean access, structure, big fish potential.",
         ("striped_bass", "bluefish", "fluke", "black_sea_bass", "tautog",
          "bonito", "false_albacore"),
         {"striped_bass": 0.88, "bluefish": 0.86, "fluke": 0.80,
          "black_sea_bass": 0.84, "tautog": 0.86,
          "bonito": 0.88, "false_albacore": 0.92},
         None, (41.3730, -71.4958)),
]

# --------------------------------------------------------------- your marks
#
# The nineteen positions above are public water — every one is on the chart
# and in every guidebook, so listing them gives nothing away. Your own marks
# are a different matter entirely, and the first thing anyone says when they
# hear about an app like this is "don't give away my good spots".
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


def curated_for(species: str) -> bool:
    """Has anyone said which of these spots hold this fish?

    `species` on a Spot is local knowledge of the same tier as `quality` and
    `best_stage` -- conventional wisdom, not measurement -- so an empty answer
    means nobody wrote it down, never that the fish is absent.
    """
    return any(species in s.species for s in SPOTS)


def for_species(species: str) -> list[Spot]:
    """Spots to consider for this fish, and never an empty list.

    This returned [] for anything no spot named, which was harmless while the
    six scored species were exactly the six that appeared in the listings
    above. Adding eight profiles broke that coupling and turned a silent
    filter into a silent outage: `cli._cmd_forecast` printed "no spots carry
    bonito" and exited 1, and `server.build_grid` -- which only takes the
    unfiltered `spots.SPOTS` path for species the model does NOT score -- built
    a grid with an empty spot list, so a newly modelled fish came out worse
    than an unmodelled one.

    So an uncurated species falls back to every spot rather than to none, and
    that is the honest answer: nobody has narrowed the list, so the app does
    not narrow it either. `curated_for` says which case a caller is holding.

    Two species ARE curated below and it is worth knowing why only two.
    Bonito and false albacore are the one group whose distribution inside this
    bay is sharply uneven in a way local knowledge is confident about -- they
    are a mouth-and-ocean fish and are effectively never caught above the
    bridges -- and listing them everywhere would put albies seven miles up
    the bay in the forecast. For weakfish, winter flounder, mackerel, squid, dogfish
    and searobin the bay-wide distribution is either genuinely broad or nobody
    has recorded it, so the fallback is the correct answer rather than a
    placeholder.
    """
    hits = [s for s in SPOTS if species in s.species]
    return hits or list(SPOTS)


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


def at_coord(lat: float, lon: float, resolution: dict | None = None):
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
