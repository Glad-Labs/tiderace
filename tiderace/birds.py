"""Seabird observations, because birds are how bait is actually found.

You told me you were on fish at Charlestown because there were birds working
the east side of the breachway. No model in this project could have known
that, and the bait layer only knows what you or a report told it.

eBird is thousands of people logging what they saw and where, in near real
time, for free. Filtered to the species that follow bait, it is a bait sensor
with far more coverage than one angler can have.

Not every bird means fish. A cormorant on a rock means nothing. Terns and
shearwaters actively working a patch of water mean bait is up and being
pushed, which is the whole signal. So this weights by species rather than
counting birds, and reports what it saw rather than scoring it.

Needs a free key from https://ebird.org/api/keygen — set it with
`tiderace config --ebird-key`.
"""

from __future__ import annotations

import json
import math
import os
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime

from . import cache as cachemod

API = "https://api.ebird.org/v2"
UA = "tiderace (+https://github.com/Glad-Labs/tiderace)"

# How strongly each species implies bait being actively worked at the surface.
# Plunge-divers and shearwaters are the ones that matter; a heron in a marsh
# is not telling you anything about a school of silversides offshore.
BAIT_BIRDS = {
    "Common Tern": 1.0, "Roseate Tern": 1.0, "Least Tern": 0.9,
    "Arctic Tern": 0.9, "Forster's Tern": 0.9, "Royal Tern": 0.9,
    "Black Tern": 0.7,
    "Northern Gannet": 1.0,
    "Great Shearwater": 0.95, "Sooty Shearwater": 0.95,
    "Cory's Shearwater": 0.95, "Manx Shearwater": 0.9,
    "Wilson's Storm-Petrel": 0.6,
    "Laughing Gull": 0.7, "Bonaparte's Gull": 0.7,
    "Herring Gull": 0.4, "Great Black-backed Gull": 0.35,
    "Double-crested Cormorant": 0.3,
    "Osprey": 0.5,
    "Parasitic Jaeger": 0.8, "Pomarine Jaeger": 0.8,
}


class NoKey(RuntimeError):
    pass


def api_key() -> str:
    from . import config as cfgmod
    k = os.environ.get("EBIRD_API_KEY") or cfgmod.load().get("ebird_key")
    if not k:
        raise NoKey("no eBird key — get a free one at https://ebird.org/api/keygen "
                    "then: tiderace config --ebird-key YOURKEY")
    return k


# eBird "recent observations" move on the order of hours, and a forecast run
# asks once per spot -- nineteen serial round trips on a cold map load. Cached
# on disk like every other source, keyed on the URL only: the API key travels
# in a header, so it never reaches the cache filename or the stored body.
CACHE_TTL = 1800


def _get(path: str, **params) -> list:
    from . import sources

    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    cache = sources._cache_path(url)
    if os.path.exists(cache) and time.time() - os.path.getmtime(cache) < CACHE_TTL:
        with open(cache) as fh:
            return json.load(fh)

    req = urllib.request.Request(url, headers={
        "X-eBirdApiToken": api_key(), "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            payload = json.loads(r.read())
    except Exception:                                             # noqa: BLE001
        # Stale birds beat no birds: the layer is a proxy either way, and the
        # age is carried on every observation so the decay still discounts it.
        if os.path.exists(cache):
            with open(cache) as fh:
                return json.load(fh)
        raise

    cachemod.write_json(cache, payload)
    return payload


def nearby(lat: float, lon: float, radius_km: int = 25,
           days_back: int = 3) -> list[dict]:
    """Recent observations near a point, newest first."""
    return _get("/data/obs/geo/recent", lat=round(lat, 2), lng=round(lon, 2),
                dist=min(radius_km, 50), back=min(days_back, 30),
                includeProvisional="true")


def bait_activity(lat: float, lon: float, radius_km: int = 25,
                  days_back: int = 3, limit: int = 8) -> dict:
    """What the bait-following species have been doing near here.

    Returns counts and a weighted total. It does not return a score for a
    fishing spot -- birds tell you bait was up somewhere near a checklist
    location on some day, which is a hint, not a forecast.
    """
    obs = nearby(lat, lon, radius_km, days_back)
    hits, others = [], 0
    by_species: dict[str, int] = defaultdict(int)
    spots: dict[tuple, dict] = {}

    for o in obs:
        name = o.get("comName", "")
        w = BAIT_BIRDS.get(name)
        if w is None:
            others += 1
            continue
        n = o.get("howMany") or 1
        by_species[name] += n
        hits.append(o)
        key = (round(o["lat"], 3), round(o["lng"], 3))
        s = spots.setdefault(key, {"lat": o["lat"], "lon": o["lng"],
                                   "place": o.get("locName", ""),
                                   "weighted": 0.0, "birds": 0,
                                   "species": set(), "last": ""})
        s["weighted"] += w * min(n, 500)
        s["birds"] += n
        s["species"].add(name)
        s["last"] = max(s["last"], o.get("obsDt", ""))

    ranked = sorted(spots.values(), key=lambda s: -s["weighted"])
    for s in ranked:
        s["species"] = sorted(s["species"])

    return {
        "observations": len(obs), "bait_bird_records": len(hits),
        "other_species_ignored": others,
        "by_species": dict(sorted(by_species.items(), key=lambda kv: -kv[1])),
        "hotspots": ranked[:limit],
        "radius_km": radius_km, "days_back": days_back,
    }


# ---------------------------------------------------------------- inference
#
# Birds are kept OUT of the bait log, and the distinction is not pedantry.
#
#   Seeing bait is an observation. Seeing birds is a guess about bait.
#
# Birds are over bait often enough to be worth having, and not often enough to
# be the same thing: they also loaf, rest, follow boats, and pass through. An
# earlier version wrote them into the bait log with a lower confidence, which
# quietly made a certainty and an inference the same kind of record differing
# by a tag. It produced exactly the failure that framing invites -- a single
# `trace` tern record DILUTED a `loaded` sighting of silversides that had been
# made by eye, dropping the signal from +0.56 to +0.44.
#
# A weak inference must never weaken a direct observation. So birds live in
# their own layer, and the rule between them is precedence rather than blend:
#
#   observed bait present  ->  birds add nothing, the real thing is already known
#   no observed bait       ->  birds stand in, at a discount
#
# A proxy is worth something when you lack the measurement and worth nothing
# when you have it.
#
# What birds cannot tell you at all is WHAT the bait is. That is inferred from
# the bird, which is defensible and is still an inference.

BIRD_IMPLIES_BAIT = {
    # small terns plunge from low down onto small stuff
    "Common Tern": "silversides", "Roseate Tern": "silversides",
    "Least Tern": "silversides", "Forster's Tern": "silversides",
    "Arctic Tern": "silversides", "Black Tern": "silversides",
    "Royal Tern": "peanut bunker",
    # gannets dive from height and take bigger baitfish
    "Northern Gannet": "bunker",
    # shearwaters work offshore, on sand eels and squid
    "Great Shearwater": "sand eels", "Sooty Shearwater": "sand eels",
    "Cory's Shearwater": "sand eels", "Manx Shearwater": "sand eels",
    # gulls follow whatever is already being pushed
    "Laughing Gull": "peanut bunker", "Bonaparte's Gull": "silversides",
    # jaegers rob other birds, so they mark active feeding rather than a bait type
    "Parasitic Jaeger": None, "Pomarine Jaeger": None,
    "Wilson's Storm-Petrel": None,
    "Herring Gull": None, "Great Black-backed Gull": None,
    "Double-crested Cormorant": None, "Osprey": None,
}

# Weighted activity at a location, mapped to the abundance vocabulary the bait
# model already uses. These thresholds are a judgement, not a measurement.
def _abundance(weighted: float) -> str:
    if weighted >= 150:
        return "loaded"
    if weighted >= 40:
        return "decent"
    if weighted >= 8:
        return "scattered"
    return "trace"


def derived_sightings(lat: float, lon: float, radius_km: int = 25,
                      days_back: int = 3, limit: int = 8) -> list[dict]:
    """Turn bird activity into bait sightings the forecast can use.

    Confidence is capped at medium: a bird tells you something was being
    eaten near a checklist location, and eBird locations are named places that
    can cover a lot of water. That is weaker than standing there and looking
    at the bait, and it is recorded as weaker.
    """
    r = bait_activity(lat, lon, radius_km, days_back, limit)
    out = []
    for spot in r["hotspots"]:
        # Pick the bait implied by the most informative bird present.
        best_bait, best_w = None, 0.0
        for name in spot["species"]:
            b = BIRD_IMPLIES_BAIT.get(name)
            w = BAIT_BIRDS.get(name, 0)
            if b and w > best_w:
                best_bait, best_w = b, w
        if not best_bait:
            continue                      # active birds, but nothing implied
        out.append({
            "bait": best_bait,
            "lat": spot["lat"], "lon": spot["lon"],
            "when": spot["last"][:16].replace(" ", "T"),
            "abundance": _abundance(spot["weighted"]),
            "source": "ebird",
            "confidence": "medium" if best_w >= 0.9 else "low",
            "notes": f"{spot['birds']} birds at {spot['place'][:60]} — "
                     f"{', '.join(spot['species'])[:80]}",
            "weighted": round(spot["weighted"], 1),
            "inferred": True,
        })
    return out




# ------------------------------------------------------- one query, shared
#
# A forecast asks about twenty-one spots, and asking eBird separately for each
# was twenty-one round trips describing largely the same water -- the bay is
# about 40 km across and eBird will answer for a 50 km radius in one request.
#
# So a query is treated as covering a CIRCLE, and any spot far enough inside
# that circle reuses it. "Far enough" means the query still reaches every
# observation the spot could care about: bait stops counting past
# `bait.MAX_NM`, so a spot within (radius - MAX_NM) of the centre sees exactly
# what a query centred on it would have seen.
#
# Nothing here is bay-specific. The first spot asked fetches a circle around
# itself, its neighbours fall inside it, and a spot on another coast simply
# opens a second circle.

REGION_KM = 50          # eBird's maximum radius for one geo query
REGION_LIMIT = 60       # hotspots kept from a regional query, not 8

# (lat, lon, days_back, fetched_at, sightings). In-process only, and
# deliberately so: the disk cache in `_get` already spans runs, and this exists
# to collapse one forecast's worth of spots into one request. It carries the
# same TTL, because `tiderace serve` runs for days and a cache with no expiry
# would pin one afternoon's birds to every forecast after it.
_REGIONS: list[tuple[float, float, int, float, list[dict]]] = []


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle-ish distance in km. Uses cos(lat) rather than a constant
    per-degree figure, because a spot can be anywhere, not just at 41.5N."""
    mid = math.radians((lat1 + lat2) / 2)
    dx = (lon2 - lon1) * 111.32 * math.cos(mid)
    dy = (lat2 - lat1) * 110.57
    return math.hypot(dx, dy)


def region_reuse_km() -> float:
    """How far inside a query circle a spot has to be to reuse it."""
    from .bait import MAX_NM
    return REGION_KM - MAX_NM * 1.852


def sightings_near(lat: float, lon: float, days_back: int = 3) -> list[dict]:
    """Bird-derived bait sightings covering a point, reusing a wider query.

    Returns everything the regional query found, not a filtered subset:
    `bait.bait_at` and `signal_at` already apply the distance falloff, and
    pre-filtering here would only duplicate it less accurately.
    """
    margin = region_reuse_km()
    now = time.time()
    for clat, clon, back, at, found in _REGIONS:
        if (back == days_back and now - at < CACHE_TTL
                and _km(lat, lon, clat, clon) <= margin):
            return found
    try:
        found = derived_sightings(lat, lon, REGION_KM, days_back, REGION_LIMIT)
    except Exception:                                             # noqa: BLE001
        # No key, no network, or eBird is down. Birds are a bonus layer; the
        # forecast is physics and must not fail with them.
        found = []
    _REGIONS.append((lat, lon, days_back, now, found))
    return found


def prime(points, days_back: int = 3) -> bool:
    """Fetch one query covering a whole set of spots, before any is asked.

    Without this the first spot in the loop opens a circle around itself, and
    a spot at the far end of the bay can fall outside it -- two requests where
    one centred between them would do. Returns whether one circle sufficed.
    """
    pts = [(float(a), float(b)) for a, b in points]
    if not pts:
        return False
    clat = sum(p[0] for p in pts) / len(pts)
    clon = sum(p[1] for p in pts) / len(pts)
    if max(_km(clat, clon, a, b) for a, b in pts) > region_reuse_km():
        return False              # too spread out; each opens its own circle
    sightings_near(clat, clon, days_back)
    return True


def forget_regions() -> None:
    """Drop the in-process region cache. For tests and long-lived servers."""
    _REGIONS.clear()


# How much a pure-bird signal is worth against a seen-it-yourself one. Birds
# are a good proxy, not a great one, and this is the discount for that.
BIRD_DISCOUNT = 0.55


def signal_at(lat: float, lon: float, species: str,
              radius_km: int = 25, days_back: int = 3,
              when: datetime | None = None,
              derived: list[dict] | None = None) -> dict:
    """A bait-like signal derived from birds, on the same -1..1 scale.

    Deliberately never written anywhere. It is recomputed from eBird when
    asked, so it cannot accumulate in a log and cannot be mistaken later for
    something anybody saw.

    `when` is the time being forecast, not the time of asking -- a tern seen
    this morning says much less about Tuesday than about this afternoon, and
    the bait layer has always discounted for that. Pass `derived` to score
    many hours against one fetch.
    """
    from .bait import RELEVANCE
    rel = RELEVANCE.get(species, {})
    if not rel:
        return {"signal": 0.0, "known": False}

    if derived is None:
        try:
            derived = derived_sightings(lat, lon, radius_km, days_back)
        except Exception:                                         # noqa: BLE001
            return {"signal": 0.0, "known": False}
    if not derived:
        return {"signal": 0.0, "known": False}

    from .bait import ABUNDANCE, CONFIDENCE, HALF_LIFE_DAYS, MAX_NM, SIGMA_NM, _nm
    import math
    from datetime import datetime

    now = when or datetime.now()
    best, top = 0.0, None
    for d in derived:
        r = rel.get(d["bait"])
        if not r:
            continue
        dist = _nm(lat, lon, d["lat"], d["lon"])
        if dist > MAX_NM:
            continue
        try:
            age = max(0.0, (now - datetime.fromisoformat(d["when"])).total_seconds() / 86400)
        except ValueError:
            continue
        w = (0.5 ** (age / HALF_LIFE_DAYS)) * math.exp(-(dist ** 2) / (2 * SIGMA_NM ** 2))
        v = w * r * ABUNDANCE.get(d["abundance"], 0.4) \
            * CONFIDENCE.get(d["confidence"], 0.7) * BIRD_DISCOUNT
        if v > best:
            best, top = v, d

    return {"signal": round(min(1.0, best), 3), "known": bool(top), "top": top}


def describe(sig: dict) -> str:
    if not sig.get("known"):
        return "no bird activity on record nearby"
    t = sig["top"]
    return (f"{t['abundance']} {t['bait']} implied by birds "
            f"({t['notes'].split(chr(8212))[0].strip()[:38]})")
