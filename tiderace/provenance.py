"""Where each part of a number actually came from.

A score of 86.5 reads as one fact. It is not: it is a measurement, a
prediction, an inference and a guess multiplied together, and those are worth
very different amounts. The score's prominence overstates its reliability, and
the honest fix is not to hide it but to show what it is made of.

Five tiers, strongest first:

  observed     somebody looked. Your bait sighting, an observed water
               temperature, a buoy reading. The only tier that cannot be
               wrong about whether the thing happened.
  predicted    physics run forward from measurement. Tidal current from
               harmonics, sun and moon geometry, an NWS forecast. Reliable,
               but a statement about the future.
  secondhand   a human observation that arrived via someone else. A weekly
               report. Real, vaguer about where and when.
  inferred     a proxy. Birds standing in for bait. Often right, sometimes
               a flock resting.
  assumed      a number somebody typed. The species curves, the spot priors,
               the corroboration factor. These are hypotheses.

Independence matters as much as tier. Solunar peaks at lunar transit, lunar
transit drives the tide, the tide drives the current -- three sources that
agree because they are one source. Your eyes and a stranger's eBird checklist
agreeing is two. Convergence is only evidence when the witnesses are separate,
so this groups by origin, not just by tier.
"""

from __future__ import annotations

OBSERVED, PREDICTED, SECONDHAND, INFERRED, ASSUMED = (
    "observed", "predicted", "secondhand", "inferred", "assumed")

TIER_ORDER = [OBSERVED, PREDICTED, SECONDHAND, INFERRED, ASSUMED]

# Every scoring input, with where it comes from and what it is downstream of.
# `origin` is the independence key: inputs sharing an origin are one witness.
INPUTS = {
    "current":   (PREDICTED,  "NOAA harmonic current prediction",  "moon"),
    "light":     (PREDICTED,  "solar geometry",                    "sun"),
    "temp":      (OBSERVED,   "water temperature gauge",           "ocean"),
    "wind":      (PREDICTED,  "NWS gridded forecast",              "weather"),
    "pressure":  (PREDICTED,  "NWS gridded forecast",              "weather"),
    "season":    (OBSERVED,   "65y GSO trawl temperature series",  "ocean"),
}

MODIFIERS = {
    "bait":                 (OBSERVED,   "bait seen",              "bait"),
    "birds":                (INFERRED,   "birds as a bait proxy",  "bait"),
    # Whales share the "bait" origin with birds on purpose. Both are a predator
    # standing in for a look at the bait, so agreement between them is one
    # witness reinforced, not two witnesses converging.
    "whales":               (INFERRED,   "whales as a bait proxy", "bait"),
    "birds_and_whales":     (INFERRED,   "two predators on bait",  "bait"),
    "bait_worked_by_birds": (OBSERVED,   "bait seen, birds on it", "bait"),
    "spring_tide":          (PREDICTED,  "lunar phase",            "moon"),
    "tide_stage":           (ASSUMED,    "hand-set stage preference", "belief"),
    "spot_quality":         (ASSUMED,    "hand-set spot prior",    "belief"),
    "heat_daytime":         (OBSERVED,   "water temperature gauge", "ocean"),
    "heat_night":           (OBSERVED,   "water temperature gauge", "ocean"),
    "wind_against_tide":    (PREDICTED,  "NWS forecast + current", "weather"),
}


def breakdown(scored: dict, feat: dict | None = None) -> dict:
    """Classify one scored window by where its parts came from."""
    feat = feat or {}
    tiers: dict[str, list] = {t: [] for t in TIER_ORDER}
    origins: dict[str, set] = {}

    for name, contribution in (scored.get("weighted") or {}).items():
        tier, what, origin = INPUTS.get(name, (ASSUMED, name, "belief"))
        # A term contributes nothing if its weight is zero.
        if contribution <= 0:
            continue
        tiers[tier].append({"name": name, "what": what, "amount": contribution})
        origins.setdefault(origin, set()).add(name)

    for name, value in (scored.get("modifiers") or {}).items():
        if abs(value - 1.0) < 0.005:
            continue
        tier, what, origin = MODIFIERS.get(name, (ASSUMED, name, "belief"))
        tiers[tier].append({"name": name, "what": what,
                            "amount": round(value - 1.0, 3)})
        origins.setdefault(origin, set()).add(name)

    # The species curves shape every term, so they are always in play.
    tiers[ASSUMED].append({"name": "species_curve", "amount": None,
                           "what": "hand-set response curves — never fitted"})
    origins.setdefault("belief", set()).add("species_curve")

    counted = {t: len(v) for t, v in tiers.items() if v}
    hard = len(tiers[OBSERVED]) + len(tiers[PREDICTED])
    soft = len(tiers[SECONDHAND]) + len(tiers[INFERRED]) + len(tiers[ASSUMED])

    return {
        "tiers": {t: v for t, v in tiers.items() if v},
        "counts": counted,
        "hard": hard, "soft": soft,
        "independent_origins": sorted(origins),
        "origin_detail": {k: sorted(v) for k, v in sorted(origins.items())},
    }


def agreement(feat: dict) -> dict:
    """How many genuinely separate witnesses say bait is here.

    The point Matt made, made checkable: several sources converging is worth
    more than any one model's opinion -- but only if they are separate. This
    counts witnesses, and says plainly when there are none.
    """
    witnesses = []
    sources = feat.get("bait_sources") or []
    if "own" in sources or "manual" in sources or "voice" in sources:
        witnesses.append(("you saw it", OBSERVED))
    if "report" in sources:
        witnesses.append(("a report said so", SECONDHAND))
    if (feat.get("bird_signal") or 0) > 0:
        kind = feat.get("proxy_kind") or "birds"
        witnesses.append(({"birds": "birds are on it",
                           "whales": "whales are on it",
                           "birds_and_whales": "birds and whales are on it",
                           }.get(kind, "birds are on it"), INFERRED))

    return {
        "witnesses": witnesses,
        "count": len(witnesses),
        "corroborated": len(witnesses) >= 2,
        "strongest": witnesses[0][1] if witnesses else None,
    }
