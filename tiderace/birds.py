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
import os
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime

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


def _get(path: str, **params) -> list:
    url = f"{API}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={
        "X-eBirdApiToken": api_key(), "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def nearby(lat: float, lon: float, radius_km: int = 25,
           days_back: int = 3) -> list[dict]:
    """Recent observations near a point, newest first."""
    return _get("/data/obs/geo/recent", lat=round(lat, 2), lng=round(lon, 2),
                dist=min(radius_km, 50), back=min(days_back, 30),
                includeProvisional="true")


def bait_activity(lat: float, lon: float, radius_km: int = 25,
                  days_back: int = 3) -> dict:
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
        "hotspots": ranked[:8],
        "radius_km": radius_km, "days_back": days_back,
    }
