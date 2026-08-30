"""Bait: the dominant variable, and the one you cannot compute.

Tide and light come out of an equation. Bait does not. You know bait was
somewhere because somebody saw it there — so this is an *observation* layer
that decays in space and time, not another physics term.

Three things the model gets right that a naive "bait: yes/no" flag would not:

  1. **Relevance is per predator.** A wall of adult bunker is everything to a
     bass and nearly nothing to a tautog, which wants crabs. A sighting is
     scored through what the target actually eats.

  2. **Absence is evidence, but only when observed.** No data means unknown
     and scores neutral. Somebody explicitly reporting "nothing around" is a
     real negative signal and scores below neutral. Conflating those two is
     how you end up penalising every spot nobody has visited.

  3. **It decays.** Bait moves. A sighting four days old is worth roughly half
     a fresh one, and one two miles away is worth much less than one on the
     mark.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta

BAIT_PATH = os.environ.get(
    "TIDERACE_BAIT",
    os.path.join(os.path.dirname(__file__), "..", "data", "bait_log.jsonl"))

HALF_LIFE_DAYS = 4.0     # a sighting is worth half as much four days on
SIGMA_NM = 1.2           # spatial falloff
MAX_NM = 3.5             # beyond this, ignore entirely

ABUNDANCE = {"none": 0.0, "trace": 0.2, "scattered": 0.45,
             "decent": 0.75, "loaded": 1.0}

# What each predator actually eats, 0..1. Absent means irrelevant.
RELEVANCE: dict[str, dict[str, float]] = {
    "striped_bass": {
        "bunker": 1.0, "peanut bunker": 0.95, "herring": 0.9, "mackerel": 0.8,
        "silversides": 0.7, "sand eels": 0.7, "squid": 0.6, "crabs": 0.4,
        "worms": 0.3, "shrimp": 0.3,
    },
    "bluefish": {
        "peanut bunker": 1.0, "bunker": 0.95, "silversides": 0.85,
        "mackerel": 0.85, "herring": 0.8, "sand eels": 0.7, "squid": 0.7,
    },
    "fluke": {
        "sand eels": 1.0, "squid": 0.95, "silversides": 0.85,
        "peanut bunker": 0.6, "shrimp": 0.5, "crabs": 0.3,
    },
    "black_sea_bass": {
        "crabs": 1.0, "squid": 0.9, "shrimp": 0.7, "sand eels": 0.5,
        "silversides": 0.45, "worms": 0.4,
    },
    "scup": {
        "worms": 1.0, "crabs": 0.7, "shrimp": 0.7, "squid": 0.6,
        "silversides": 0.3,
    },
    "tautog": {
        "crabs": 1.0, "mussels": 0.95, "shrimp": 0.5, "worms": 0.4,
    },
}

BAIT_TYPES = sorted({b for m in RELEVANCE.values() for b in m})


@dataclass
class Sighting:
    bait: str
    lat: float
    lon: float
    when: str                      # ISO local
    abundance: str = "decent"      # see ABUNDANCE; "none" is a real signal
    spot: str | None = None
    source: str = "own"            # own | report | voice
    confidence: str = "high"       # high | medium | low
    notes: str | None = None
    logged_at: str = ""


def record(s: Sighting, path: str = BAIT_PATH) -> Sighting:
    s.logged_at = datetime.now().isoformat(timespec="seconds")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a") as fh:
        fh.write(json.dumps(asdict(s)) + "\n")
    return s


def load(path: str = BAIT_PATH) -> list[dict]:
    if not os.path.exists(path):
        return []
    out = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def _nm(lat1, lon1, lat2, lon2) -> float:
    """Flat-earth distance in nautical miles. Ample at bay scale."""
    dx = (lon2 - lon1) * 45.0      # nm per degree lon near 41.5N
    dy = (lat2 - lat1) * 60.0
    return math.sqrt(dx * dx + dy * dy)


CONFIDENCE = {"high": 1.0, "medium": 0.7, "low": 0.45}


def bait_at(lat: float, lon: float, when: datetime, species: str,
            sightings: list[dict] | None = None,
            exclude_sources: set[str] | None = None) -> dict:
    """Weighted bait signal for a predator at a place and time.

    Returns `signal` in roughly -1..+1: positive means relevant bait has been
    seen nearby and recently, negative means somebody looked and found nothing,
    zero means nobody knows.
    """
    rows = sightings if sightings is not None else load()
    # Lets the evaluation score the same trip with and without a source, which
    # is the only way to ask whether the model works because of the physics or
    # because of the birds.
    if exclude_sources:
        rows = [r for r in rows if r.get("source") not in exclude_sources]
    rel = RELEVANCE.get(species, {})
    if not rows or not rel:
        return {"signal": 0.0, "observations": 0, "top": None, "known": False}

    num = 0.0
    den = 0.0
    strength = 0.0          # how much is actually known, 0..1
    best = None
    used = 0

    for r in rows:
        relevance = rel.get(str(r.get("bait", "")).lower())
        if not relevance:
            continue
        try:
            t = datetime.fromisoformat(r["when"])
        except (KeyError, ValueError):
            continue

        age_days = (when - t).total_seconds() / 86400.0
        if age_days < -0.5:            # sighting is in the future; ignore
            continue
        age_days = max(0.0, age_days)

        dist = _nm(lat, lon, float(r["lat"]), float(r["lon"]))
        if dist > MAX_NM:
            continue

        decay = 0.5 ** (age_days / HALF_LIFE_DAYS)
        near = math.exp(-(dist ** 2) / (2 * SIGMA_NM ** 2))
        conf = CONFIDENCE.get(r.get("confidence", "high"), 0.7)

        weight = decay * near * conf * relevance
        if weight < 0.01:
            continue

        amount = ABUNDANCE.get(r.get("abundance", "decent"), 0.5)
        # "none seen" is a genuine negative, not merely a zero.
        value = -0.6 if amount == 0.0 else amount

        num += weight * value
        den += weight
        # The weighted *mean* says what was seen; it cannot say how much you
        # know, because dividing by the same weights cancels the decay out
        # entirely — a fortnight-old rumour two miles away scored identically
        # to a wall of bunker on the mark this morning. Evidence strength is
        # tracked separately, as the best single observation available.
        strength = max(strength, weight)
        used += 1
        if best is None or weight > best[0]:
            best = (weight, r)

    if den == 0:
        return {"signal": 0.0, "observations": 0, "top": None, "known": False}

    signal = (num / den) * strength
    top = best[1] if best else None
    return {
        "signal": round(max(-1.0, min(1.0, signal)), 3),
        "sources": sorted({r.get("source", "own") for r in rows}),
        "observations": used,
        "known": True,
        "top": None if not top else {
            "bait": top["bait"], "abundance": top.get("abundance"),
            "when": top["when"], "source": top.get("source", "own"),
            "age_days": round(max(0.0, (when - datetime.fromisoformat(top["when"]))
                                  .total_seconds() / 86400.0), 1),
            "distance_nm": round(_nm(lat, lon, float(top["lat"]), float(top["lon"])), 2),
        },
    }


def modifier(signal: float) -> float:
    """Bait scales the whole forecast rather than nudging one term: perfect
    water with nothing to eat in it is still an empty spot."""
    if signal >= 0:
        return 1.0 + 0.35 * signal      # up to 1.35x
    return 1.0 + 0.25 * signal          # down to 0.75x


def describe(b: dict) -> str:
    if not b.get("known"):
        return "no bait reports nearby"
    t = b.get("top") or {}
    if b["signal"] < -0.1:
        return f"bait reported absent ({t.get('age_days', '?')}d ago)"
    return (f"{t.get('abundance','')} {t.get('bait','bait')} "
            f"{t.get('distance_nm','?')} nm away, {t.get('age_days','?')}d old").strip()
