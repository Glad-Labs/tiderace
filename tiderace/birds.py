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


# ---------------------------------------------------------------- inference
#
# Birds feed the forecast the same way your own sightings do -- as bait
# observations, through the existing decay -- rather than as a separate score
# term. That is deliberate on three counts:
#
#   * It IS the same fact. A tern working a patch and you seeing silversides
#     are two reports of one thing, and the bait layer already knows how to
#     age a report and weigh it per predator.
#   * A new multiplicative term would double-count. Birds are over bait; bait
#     is already in the score. Multiplying both would say the same thing twice
#     and call it agreement.
#   * Provenance survives. Every derived sighting is tagged `source="ebird"`,
#     so the evaluation can ask whether the model works because of physics or
#     because of birds -- a question it could not ask if these arrived
#     indistinguishable from your own.
#
# What birds cannot tell you is WHAT the bait is. That is inferred from the
# bird, which is defensible but is an inference, and it is recorded as one.

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
                      days_back: int = 3) -> list[dict]:
    """Turn bird activity into bait sightings the forecast can use.

    Confidence is capped at medium: a bird tells you something was being
    eaten near a checklist location, and eBird locations are named places that
    can cover a lot of water. That is weaker than standing there and looking
    at the bait, and it is recorded as weaker.
    """
    r = bait_activity(lat, lon, radius_km, days_back)
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


def sync_to_bait_log(lat: float, lon: float, radius_km: int = 25,
                     days_back: int = 3, apply: bool = False) -> dict:
    """Add derived sightings to the bait log, skipping ones already there.

    Deduplicated on place and day: re-running this must not stack the same
    checklist into the log five times and manufacture a bait pile out of one
    observation.
    """
    from . import bait as baitmod
    derived = derived_sightings(lat, lon, radius_km, days_back)
    existing = baitmod.load()

    def seen(d):
        for e in existing:
            if e.get("source") != "ebird":
                continue
            if (abs(e.get("lat", 0) - d["lat"]) < 0.002
                    and abs(e.get("lon", 0) - d["lon"]) < 0.002
                    and (e.get("when") or "")[:10] == d["when"][:10]):
                return True
        return False

    new = [d for d in derived if not seen(d)]
    if apply:
        for d in new:
            baitmod.record(baitmod.Sighting(
                bait=d["bait"], lat=d["lat"], lon=d["lon"], when=d["when"],
                abundance=d["abundance"], source="ebird",
                confidence=d["confidence"], notes=d["notes"]))
    return {"found": len(derived), "new": len(new),
            "already_logged": len(derived) - len(new),
            "applied": len(new) if apply else 0, "sightings": new}
