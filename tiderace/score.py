"""Species response models.

Every species is a set of named response curves over physical features. The
scorer returns the total *and* the per-term contributions, for two reasons:

  1. You can read why a window scored well, and argue with it.
  2. The weights are data, not code. Once there is a catch log, these become
     the initial values of a fitted model instead of hand-tuned priors.

Nothing here is magic. It is the conventional wisdom of Narragansett Bay
saltwater fishing written down in a form a computer can rank.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


# ------------------------------------------------------------- response curves

def trapezoid(x: float, lo_out: float, lo_in: float, hi_in: float, hi_out: float) -> float:
    """0 outside [lo_out, hi_out], 1 inside [lo_in, hi_in], linear ramps between."""
    if x <= lo_out or x >= hi_out:
        return 0.0
    if lo_in <= x <= hi_in:
        return 1.0
    if x < lo_in:
        return (x - lo_out) / (lo_in - lo_out)
    return (hi_out - x) / (hi_out - hi_in)


def gaussian(x: float, mu: float, sigma: float) -> float:
    return math.exp(-((x - mu) ** 2) / (2 * sigma * sigma))


def peaked(x: float, opt: float, sigma_lo: float, sigma_hi: float,
           hard_max: float) -> float:
    """Asymmetric bell: rewards being near the optimum instead of merely
    inside a wide acceptable band. A flat-topped trapezoid cannot tell
    0.6 kt from 1.4 kt, and that difference is the whole forecast."""
    if x >= hard_max:
        return 0.0
    sigma = sigma_lo if x < opt else sigma_hi
    val = gaussian(x, opt, sigma)
    # Taper to exactly zero at the hard limit so nothing survives a rip.
    if x > opt:
        val *= max(0.0, min(1.0, (hard_max - x) / (hard_max - opt)))
    return val


@dataclass
class Profile:
    key: str
    name: str
    months: tuple[int, ...]          # months present in the bay
    peak_months: tuple[int, ...]     # months of peak abundance
    temp: tuple[float, float, float, float]      # trapezoid on water temp F
    current: tuple[float, float, float, float]   # (optimum, sigma_lo, sigma_hi, hard_max) kt
    light: dict[str, float]          # multiplier by light phase
    weights: dict[str, float]        # term weights, should sum to ~1
    wind_max_kt: float = 25.0
    likes_falling_pressure: bool = True
    notes: str = ""


PROFILES: dict[str, Profile] = {
    "striped_bass": Profile(
        key="striped_bass", name="Striped Bass",
        months=(4, 5, 6, 7, 8, 9, 10, 11), peak_months=(5, 6, 9, 10),
        temp=(44, 55, 68, 76),
        current=(1.40, 0.62, 1.15, 4.0),
        light={"golden": 1.0, "twilight": 0.96, "night": 0.88, "day": 0.40},
        weights={"season": 0.20, "temp": 0.15, "current": 0.28,
                 "light": 0.22, "wind": 0.07, "pressure": 0.08},
        wind_max_kt=25,
        notes="Moving water and low light. In August heat the day bite dies; "
              "night and the first hour of grey light carry the month.",
    ),
    "bluefish": Profile(
        key="bluefish", name="Bluefish",
        months=(6, 7, 8, 9, 10), peak_months=(7, 8, 9),
        temp=(58, 64, 78, 84),
        current=(1.30, 0.75, 1.40, 4.5),
        light={"golden": 1.0, "twilight": 0.88, "day": 0.74, "night": 0.60},
        weights={"season": 0.18, "temp": 0.14, "current": 0.24,
                 "light": 0.18, "wind": 0.10, "pressure": 0.16},
        wind_max_kt=28,
        notes="Far less fussy than bass. Follows bait; a blitz beats any forecast.",
    ),
    "fluke": Profile(
        key="fluke", name="Fluke (Summer Flounder)",
        months=(5, 6, 7, 8, 9), peak_months=(6, 7, 8),
        temp=(56, 62, 74, 80),
        current=(1.00, 0.42, 0.52, 2.6),   # drift speed -- too fast is as bad as slack
        light={"day": 1.0, "golden": 0.90, "twilight": 0.58, "night": 0.30},
        weights={"season": 0.20, "temp": 0.14, "current": 0.34,
                 "light": 0.14, "wind": 0.12, "pressure": 0.06},
        wind_max_kt=20,
        likes_falling_pressure=False,
        notes="Drift speed is the whole game: 0.5-1.5 kt over sand and edges. "
              "Wind against tide ruins the drift even when the numbers look fine.",
    ),
    "black_sea_bass": Profile(
        key="black_sea_bass", name="Black Sea Bass",
        months=(6, 7, 8, 9, 10, 11), peak_months=(7, 8, 9),
        temp=(55, 60, 74, 80),
        current=(0.90, 0.48, 0.68, 3.0),
        light={"day": 1.0, "golden": 0.90, "twilight": 0.60, "night": 0.36},
        weights={"season": 0.20, "temp": 0.16, "current": 0.26,
                 "light": 0.16, "wind": 0.14, "pressure": 0.08},
        wind_max_kt=20,
        likes_falling_pressure=False,
        notes="Structure fish. Enough current to hold them on the piece, "
              "not so much you cannot stay on it.",
    ),
    "scup": Profile(
        key="scup", name="Scup (Porgy)",
        months=(5, 6, 7, 8, 9, 10), peak_months=(6, 7, 8, 9),
        temp=(56, 62, 76, 82),
        current=(0.90, 0.55, 0.90, 3.2),
        light={"day": 1.0, "golden": 0.85, "twilight": 0.50, "night": 0.28},
        weights={"season": 0.18, "temp": 0.14, "current": 0.24,
                 "light": 0.16, "wind": 0.18, "pressure": 0.10},
        wind_max_kt=18,
        likes_falling_pressure=False,
        notes="The reliable one. If the day is fishable at all, scup are catchable.",
    ),
    "tautog": Profile(
        key="tautog", name="Tautog (Blackfish)",
        months=(4, 5, 6, 7, 8, 9, 10, 11, 12), peak_months=(10, 11),
        temp=(38, 47, 58, 68),
        current=(0.60, 0.38, 0.50, 2.4),
        light={"day": 1.0, "golden": 0.80, "twilight": 0.40, "night": 0.18},
        weights={"season": 0.26, "temp": 0.20, "current": 0.20,
                 "light": 0.14, "wind": 0.14, "pressure": 0.06},
        wind_max_kt=18,
        likes_falling_pressure=False,
        notes="Cold water, hard structure, anchored. Resident most of the year, "
              "so the temperature curve — not the calendar — is what shuts them "
              "off in summer. The October-November window is the one that matters.",
    ),
}


# ------------------------------------------------------------------- the scorer

def _season_term(p: Profile, month: int) -> float:
    if month in p.peak_months:
        return 1.0
    if month in p.months:
        return 0.55
    return 0.0


def _wind_term(p: Profile, wind_kt: float | None, exposed: bool) -> float:
    if wind_kt is None:
        return 0.6
    cap = p.wind_max_kt * (0.8 if exposed else 1.0)
    if wind_kt >= cap:
        return 0.0
    # A little chop is better than glass for most of these species.
    return trapezoid(wind_kt, -1, 4, cap * 0.55, cap)


def _pressure_term(p: Profile, trend_mb_3h: float | None) -> float:
    if trend_mb_3h is None:
        return 0.6
    if p.likes_falling_pressure:
        # Falling pressure ahead of a front turns bass on; hard high is flat.
        return trapezoid(trend_mb_3h, -6.0, -2.5, -0.2, 2.5)
    return trapezoid(trend_mb_3h, -3.0, -1.0, 1.0, 3.0)


def score(species: str, feat: dict, exposed: bool = False,
          prior: float = 0.75, best_stage: str | None = None) -> dict:
    """Score one moment at one spot. Returns total 0..100 plus contributions.

    `prior` is the spot's standing reputation for this species and
    `best_stage` its preferred tide stage -- both local knowledge, both
    intended to be replaced by fitted values once a catch log exists."""
    p = PROFILES[species]
    terms: dict[str, float] = {
        "season": _season_term(p, feat["month"]),
        "temp": trapezoid(feat["water_temp_f"], *p.temp) if feat.get("water_temp_f") else 0.6,
        "current": peaked(feat.get("current_speed", 0.0), *p.current),
        "light": p.light.get(feat["light_phase"], 0.6),
        "wind": _wind_term(p, feat.get("wind_kt"), exposed),
        "pressure": _pressure_term(p, feat.get("pressure_trend_3h")),
    }

    total = sum(p.weights[k] * v for k, v in terms.items())

    # Multiplicative modifiers -- things that gate rather than nudge.
    mods: dict[str, float] = {}

    # The spot's own reputation for this species. Compressed toward 1 so a
    # mediocre spot in perfect conditions still beats a great spot in bad ones.
    mods["spot_quality"] = 0.55 + 0.45 * prior

    # Spring tides move more water everywhere; neaps flatten the bay.
    spring = feat.get("spring_strength", 0.5)
    mods["spring_tide"] = 0.92 + 0.12 * spring
    if species == "tautog":
        mods["spring_tide"] = 1.0   # they sit on structure regardless

    # Some spots only really switch on when the water runs one way.
    if best_stage and feat.get("current_dir") in ("flood", "ebb"):
        mods["tide_stage"] = 1.0 if feat["current_dir"] == best_stage else 0.80

    # Bass specifically: hot water pushes the bite into darkness.
    if species == "striped_bass":
        wt = feat.get("water_temp_f") or 65
        if wt > 70 and feat["light_phase"] == "day":
            mods["heat_daytime"] = 0.55
        elif wt > 70 and feat["light_phase"] == "night":
            mods["heat_night"] = 1.06

    # Fluke: wind against tide wrecks the drift.
    if species == "fluke" and feat.get("wind_against_tide"):
        mods["wind_against_tide"] = 0.6

    for m in mods.values():
        total *= m

    return {
        "species": species,
        "name": p.name,
        "score": round(max(0.0, min(1.0, total)) * 100, 1),
        "terms": {k: round(v, 3) for k, v in terms.items()},
        "weighted": {k: round(p.weights[k] * v, 4) for k, v in terms.items()},
        "modifiers": {k: round(v, 3) for k, v in mods.items()},
    }


def explain(result: dict, top_n: int = 3) -> str:
    """Human sentence about what drove (or killed) the score."""
    p = PROFILES[result["species"]]
    ranked = sorted(result["weighted"].items(), key=lambda kv: kv[1], reverse=True)
    strong = [k for k, v in ranked if result["terms"][k] >= 0.75][:top_n]
    weak = [k for k, v in sorted(result["terms"].items(), key=lambda kv: kv[1])
            if v <= 0.35][:2]
    label = {
        "season": "seasonal timing", "temp": "water temperature",
        "current": "current speed", "light": "light level",
        "wind": "wind", "pressure": "barometer",
    }
    bits = []
    if strong:
        bits.append("helped by " + ", ".join(label[k] for k in strong))
    if weak:
        bits.append("held back by " + ", ".join(label[k] for k in weak))
    # spot_quality is always < 1 by construction, so only mention it when the
    # spot is genuinely a weak choice rather than merely not the very best.
    thresholds = {"spot_quality": 0.78}
    for k, v in result["modifiers"].items():
        if v < thresholds.get(k, 0.95):
            bits.append(f"held back by {k.replace('_', ' ')}")
        elif v > 1.05:
            bits.append(f"boosted for {k.replace('_', ' ')}")
    return "; ".join(bits) if bits else "middling on every axis"
