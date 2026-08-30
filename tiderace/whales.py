"""Whales and dolphins, because a feeding whale is a bait ball with a address.

`birds.py` exists because birds find bait better than we do. Whales are the
same argument with a higher threshold, and that is the whole reason to add
them: **a tern will work a scattered school; a lunge-feeding humpback will
not.** A rorqual takes a mouthful of water heavier than itself and pays for it
in oxygen, so it does not commit to thin bait. When one is feeding, there is a
real ball there -- and it is the sand eels and bunker that stripers and bluefin
are eating too.

So whales get a lighter discount than birds (0.70 against 0.55). That is not a
claim that whale data is more reliable; it is a claim that a whale sighting
implies *more bait* than a bird sighting does.

What this deliberately does NOT include, having checked rather than assumed:

  * **Sharks.** iNaturalist has 81 shark and ray records for Rhode Island this
    season and they are clearnose skates, cownose rays and smooth-hounds --
    bottom animals that say nothing about bait in the water column. Mackerel
    sharks, the ones that would mean something, returned a single record.
  * **Tagged white sharks (OCEARCH).** White sharks follow *seals*. A live map
    of tagged sharks looks like premium data and tells you where the haul-outs
    are, which is not where the bass are. Being confidently wrong is worse than
    having no layer.
  * **Right whales.** Never a fishing signal here. Approaching within 500 yards
    is a federal offence for any vessel of any size, so they belong with the
    regulations, not the forecast.

Like birds, this is a proxy and stays out of the bait log. It is recomputed on
demand and never written, so it cannot accumulate into something that later
looks like an observation somebody actually made.

Source: iNaturalist, https://api.inaturalist.org/v1/observations — open, no key
required. Observations are citizen science: a whale-watch boat logs a humpback,
not a scientist logging a bait ball. Positions can be obscured for sensitive
taxa and identifications can be wrong, which is what the discount is for.
"""

from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from . import cache

INAT = "https://api.inaturalist.org/v1/observations"
UA = "tiderace/0.1 (+https://github.com/Glad-Labs/tiderace)"
CACHE_TTL = 3 * 3600

# iNaturalist taxon ids, each verified against the taxa endpoint rather than
# guessed. An earlier pass used 47178 for sharks and got mummichogs and gobies,
# which is exactly the sort of wrong that looks fine in aggregate.
RORQUALS = 41546        # Balaenopteridae — humpback, fin, minke, sei
DOLPHINS = 41479        # Delphinidae — oceanic dolphins
RIGHT_WHALE = 41570     # Eubalaena glacialis — legal constraint, not a signal

# How much bait a sighting of this animal implies. Lunge-feeders that need a
# dense ball rank highest; a resident inshore dolphin that eats scattered fish
# all day says the least.
BAIT_WHALES = {
    "Humpback Whale": 1.00,
    "Fin Whale": 0.95,
    "Sei Whale": 0.85,
    "Common Minke Whale": 0.70,
    "Minke Whale": 0.70,
    "Short-beaked Common Dolphin": 0.75,
    "Common Dolphin": 0.75,
    "Atlantic White-sided Dolphin": 0.70,
    "Long-finned Pilot Whale": 0.55,
    "Short-finned Pilot Whale": 0.55,
    "Harbor Porpoise": 0.45,
    # Bottlenose are increasingly resident inshore and feed on scattered fish
    # rather than balled bait, so their presence is much weaker evidence.
    "Common Bottlenose Dolphin": 0.30,
    "Tamanend's Bottlenose Dolphin": 0.30,
    "Bottlenose Dolphin": 0.30,
}

# What each animal is most likely to be eating here. Humpbacks and fin whales
# in southern New England work sand eels and bunker; common dolphins offshore
# are on sand eels and squid. Where the diet is too broad to call, None means
# "something is being eaten" without naming it.
WHALE_IMPLIES_BAIT = {
    "Humpback Whale": "sand eels",
    "Fin Whale": "sand eels",
    "Sei Whale": "sand eels",
    "Common Minke Whale": "sand eels",
    "Minke Whale": "sand eels",
    "Short-beaked Common Dolphin": "sand eels",
    "Common Dolphin": "sand eels",
    "Atlantic White-sided Dolphin": "herring",
    "Long-finned Pilot Whale": "squid",
    "Short-finned Pilot Whale": "squid",
    "Harbor Porpoise": "herring",
    "Common Bottlenose Dolphin": None,
    "Tamanend's Bottlenose Dolphin": None,
    "Bottlenose Dolphin": None,
}

# A whale implies more bait than a bird does -- see the module docstring. This
# is still well below 1.0 because it remains an inference from a predator,
# never a look at the bait itself.
WHALE_DISCOUNT = 0.70


class WhaleError(RuntimeError):
    pass


def _cache_path(key: str) -> str:
    d = os.path.join(os.path.dirname(__file__), "..", "data", "cache")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f"inat_{key}.json")


def _get(url: str, ttl: float = CACHE_TTL) -> dict:
    key = str(abs(hash(url)))
    path = _cache_path(key)
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < ttl:
        hit = cache.read_json(path)
        if hit is not None:
            return hit
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        raise WhaleError(f"iNaturalist returned {e.code}") from e
    except Exception as e:                                        # noqa: BLE001
        raise WhaleError(str(e)) from e
    cache.write_json(path, data)
    return data


def _bbox(lat: float, lon: float, radius_km: float) -> dict:
    dlat = radius_km / 110.57
    dlon = radius_km / (111.32 * max(0.2, math.cos(math.radians(lat))))
    return {"nelat": lat + dlat, "nelng": lon + dlon,
            "swlat": lat - dlat, "swlng": lon - dlon}


def sightings(lat: float, lon: float, radius_km: float = 40,
              days_back: int = 7, taxa: tuple[int, ...] = (RORQUALS, DOLPHINS),
              per_page: int = 100) -> list[dict]:
    """Recent geolocated cetacean observations near a point.

    Only observations that carry a real position are kept. iNaturalist obscures
    coordinates for some taxa and users, and an obscured record is a fact about
    a rectangle rather than a place -- useless for saying where bait is.
    """
    since = (datetime.now() - timedelta(days=days_back)).date().isoformat()
    out: list[dict] = []
    for tid in taxa:
        q = dict(_bbox(lat, lon, radius_km))
        q.update({"taxon_id": tid, "d1": since, "geo": "true",
                  "order_by": "observed_on", "order": "desc",
                  "per_page": per_page})
        data = _get(f"{INAT}?{urllib.parse.urlencode(q)}")
        for o in data.get("results", []):
            if o.get("obscured") or o.get("geoprivacy") == "obscured":
                continue
            loc = o.get("location")
            if not loc:
                continue
            try:
                olat, olon = (float(v) for v in loc.split(","))
            except ValueError:
                continue
            taxon = o.get("taxon") or {}
            name = taxon.get("preferred_common_name") or taxon.get("name") or ""
            when = o.get("observed_on") or o.get("time_observed_at") or ""
            out.append({
                "species": name,
                "lat": olat, "lon": olon,
                "when": str(when)[:10],
                "count": o.get("observed_on") and 1,
                "quality": o.get("quality_grade", "needs_id"),
                "url": f"https://www.inaturalist.org/observations/{o.get('id')}",
                "place": o.get("place_guess") or "",
            })
    return out


def activity(lat: float, lon: float, radius_km: float = 40,
             days_back: int = 7) -> dict:
    """What the bait-implying cetaceans have been doing near here.

    Reports what was seen. It does not score a spot -- that is `signal_at`, and
    keeping them apart is what lets `tiderace whales` stay honest about a thin
    week instead of dressing it up.
    """
    obs = sightings(lat, lon, radius_km, days_back)
    hits = [o for o in obs if o["species"] in BAIT_WHALES]
    others = sorted({o["species"] for o in obs} - set(BAIT_WHALES))
    by_species: dict[str, int] = {}
    for o in hits:
        by_species[o["species"]] = by_species.get(o["species"], 0) + 1
    return {
        "observations": len(obs),
        "cetacean_records": len(hits),
        "other_species_ignored": others,
        "by_species": dict(sorted(by_species.items(), key=lambda kv: -kv[1])),
        "sightings": sorted(hits, key=lambda o: o["when"], reverse=True),
        "radius_km": radius_km, "days_back": days_back,
    }


def _abundance(weight: float) -> str:
    """Map an animal's implied-bait weight onto the bait vocabulary.

    Deliberately coarse. One humpback is evidence of a ball, not evidence of
    how big it is, and pretending otherwise would put a precision on this that
    a citizen-science record cannot carry.
    """
    if weight >= 0.95:
        return "decent"
    if weight >= 0.70:
        return "scattered"
    return "trace"


def derived_sightings(lat: float, lon: float, radius_km: float = 40,
                      days_back: int = 7) -> list[dict]:
    """Turn cetacean records into bait-shaped records the bait math can read.

    Confidence never exceeds medium, and drops to low for a record iNaturalist
    has not community-verified. A whale is strong evidence that bait was there;
    it is not evidence that the identification was right.
    """
    out = []
    for o in sightings(lat, lon, radius_km, days_back):
        w = BAIT_WHALES.get(o["species"])
        if not w:
            continue
        implied = WHALE_IMPLIES_BAIT.get(o["species"])
        if not implied:
            continue
        out.append({
            "bait": implied,
            "lat": o["lat"], "lon": o["lon"],
            "when": o["when"],
            "abundance": _abundance(w),
            "confidence": "medium" if o["quality"] == "research" else "low",
            "source": "whales",
            "species": o["species"],
            "notes": f"{o['species']} — {o['place'][:40]}",
            "url": o["url"],
        })
    return out


# ------------------------------------------------------- one query, shared
#
# Same reasoning as birds.prime: a forecast asks about twenty-one spots and one
# iNaturalist box covers all of them. Kept in-process only, with the same TTL,
# so `tiderace serve` running for days cannot pin one afternoon's whales to
# every forecast after it.

REGION_KM = 60
_REGIONS: list[tuple[float, float, int, float, list[dict]]] = []


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    mid = math.radians((lat1 + lat2) / 2)
    dx = (lon2 - lon1) * 111.32 * math.cos(mid)
    dy = (lat2 - lat1) * 110.57
    return math.hypot(dx, dy)


def region_reuse_km() -> float:
    from .bait import MAX_NM
    return REGION_KM - MAX_NM * 1.852


def sightings_near(lat: float, lon: float, days_back: int = 7) -> list[dict]:
    """Whale-derived bait records covering a point, reusing a wider query."""
    margin = region_reuse_km()
    now = time.time()
    for clat, clon, back, at, found in _REGIONS:
        if (back == days_back and now - at < CACHE_TTL
                and _km(lat, lon, clat, clon) <= margin):
            return found
    try:
        found = derived_sightings(lat, lon, REGION_KM, days_back)
    except Exception:                                             # noqa: BLE001
        # Whales are a bonus layer. The forecast is physics and must not fail
        # because iNaturalist is down.
        found = []
    _REGIONS.append((lat, lon, days_back, now, found))
    return found


def prime(points, days_back: int = 7) -> bool:
    pts = [(float(a), float(b)) for a, b in points]
    if not pts:
        return False
    clat = sum(p[0] for p in pts) / len(pts)
    clon = sum(p[1] for p in pts) / len(pts)
    if max(_km(clat, clon, a, b) for a, b in pts) > region_reuse_km():
        return False
    sightings_near(clat, clon, days_back)
    return True


def signal_at(lat: float, lon: float, species: str,
              radius_km: float = 40, days_back: int = 7,
              when: datetime | None = None,
              derived: list[dict] | None = None) -> dict:
    """A bait-like signal derived from cetaceans, on the same -1..1 scale.

    Never written anywhere, for the same reason the bird signal is not: it is
    an inference, and an inference that gets logged eventually gets mistaken
    for an observation.
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
        v = (w * r * ABUNDANCE.get(d["abundance"], 0.4)
             * CONFIDENCE.get(d["confidence"], 0.7) * WHALE_DISCOUNT)
        if v > best:
            best, top = v, d

    return {"signal": round(min(1.0, best), 3), "known": bool(top), "top": top}


def describe(sig: dict) -> str:
    if not sig.get("known"):
        return "no whale or dolphin activity on record nearby"
    t = sig["top"]
    return (f"{t['abundance']} {t['bait']} implied by {t['species'].lower()} "
            f"({t['when']})")
