"""Species response models.

Every species is a set of named response curves over physical features. The
scorer returns the total *and* the per-term contributions, for two reasons:

  1. You can read why a window scored well, and argue with it.
  2. The weights are data, not code. Once there is a catch log, these become
     the initial values of a fitted model instead of hand-tuned priors.

Nothing here is magic. Where a number has a published source it is cited on
the line that uses it. Where it does not, it is conventional Narragansett Bay
angling wisdom and should be read as a hypothesis, not a measurement.

A caution that matters more than any single number: the literature answers
"where is this fish and is it physiologically comfortable", which is NOT the
question this file asks. This file asks "will it bite". Those diverge -- a
tautog is alive and present all summer and still nearly uncatchable. So a
published occurrence range is an upper bound on the band, never a substitute
for it, and the two must not be silently swapped.

Sources, all consulted 2026-08-29:
  [BB-SB]  Buzzards Bay species account, striped bass (after Bigelow &
           Schroeder; Setzler et al. 1980; Coutant 1986; Rogers & Westin 1978;
           Hollis 1952).  buzzardsbay.org/.../striped-bass.pdf
  [BB-TOG] Buzzards Bay species account, tautog (after Olla et al. 1974, 1975a,
           1978; Cooper 1966; Arendt et al. 2001a; Pearce 1969; McCormack 1976).
           buzzardsbay.org/.../tautog.pdf
  [SCUP]   Steimle et al. 1999, EFH source doc NMFS-NE-149, via ASMFC scup
           species profile.
  [ASMFC-BSB] ASMFC black sea bass habitat fact sheet.
  [NEFSC-SF]  NOAA Fisheries summer flounder science pages; EFH source doc
           NMFS-NE-151.
  [BSB-AS] Slesinger et al. 2019, aerobic scope of black sea bass (PMC6564031).
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
        # 43F = 6C and 70F = 21C are the bounds of the "active" range for adult
        # bass; 78F ~ 26C is where feeding measurably declines in seawater. All
        # three from [BB-SB]. Only the 55F plateau start is still hand-set.
        temp=(43, 55, 70, 78),
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
        # Checked, unchanged: 58F lower matches the 14C tolerance floor and the
        # 12-16C (54-60F) spring arrival [bluefish EFH / ASMFC]. The warm half
        # is unsourced -- no published upper feeding limit was found.
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
        # Checked, unchanged: 80F upper matches the 27C top of the inshore
        # occurrence range [NEFSC-SF]. The 56F lower is deliberately warmer
        # than the 9C (48F) occurrence floor -- they are present in cold water,
        # they just are not a fishery yet.
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
        # Aerobic scope peaks at 24.4C = 76F [BSB-AS]; inshore summer water
        # reaches 27C = 81F [ASMFC-BSB]. Lower bound stays angling knowledge --
        # the 7C migration threshold is presence, not catchability.
        temp=(55, 60, 76, 81),
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
        # Adults are most commonly caught at 17-27C = 63-81F [SCUP]; the old
        # plateau stopped at 76F and was clipping the warm half of their range.
        # 56F lower is angling knowledge, not the 8-9C departure threshold.
        temp=(56, 63, 79, 84),
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
        # Cold half is well supported: adults off RI at 7.5C (46F) were torpid
        # with empty guts, and fish are active again by 10C (50F) [BB-TOG].
        # The WARM half is not. Upper lethal is 31-33C (88-91F), far above the
        # 68F cutoff here; the literature only says feeding is "depressed at
        # elevated temperatures" without giving a number. So 58/68 is angling
        # knowledge doing real work, and it is the single least defensible pair
        # in this file -- see the presence-vs-catchability caution up top.
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

def _season_term(p: Profile, month: int, week: int | None = None,
                 thermal: dict[int, float] | None = None,
                 shift_days: int = 0) -> float:
    """Seasonal presence, from measurement where possible.

    Two different things are folded together here and it is worth keeping them
    apart in your head:

      * **Thermal presence** is derived from sixty-five years of weekly GSO
        temperature. It is measurement, and it replaces the hand-written month
        tuples -- which is how the tautog error surfaced, the data carving the
        summer closure out on its own.
      * **Migratory peak** is not thermal at all. Stripers peak in May-June and
        again in September-October because they are *moving through*, not
        because midsummer is too warm for them. No temperature series can tell
        you that, so those months stay hand-set.

    `shift_days` slides the thermal lookup when the year is running warm or
    cold: a spring five degrees ahead of normal pulls the whole run forward by
    a couple of weeks, which is exactly the local knowledge a fixed calendar
    cannot hold.
    """
    if thermal and week:
        eff = week + shift_days / 7.0
        lo = int(eff) % 52 or 52
        hi = (lo % 52) + 1
        frac = eff - int(eff)
        a, b = thermal.get(lo), thermal.get(hi)
        if a is not None and b is not None:
            presence = a + (b - a) * frac
        elif a is not None:
            presence = a
        else:
            presence = 1.0 if month in p.months else 0.0
    else:
        presence = 1.0 if month in p.months else 0.0

    peak = 1.0 if month in p.peak_months else 0.72
    return max(0.0, min(1.0, presence * peak))


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
        "season": _season_term(p, feat["month"], feat.get("week"),
                               feat.get("thermal_season"),
                               feat.get("season_shift_days") or 0),
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

    # Bait scales everything rather than nudging one term: perfect water with
    # nothing to eat in it is still an empty spot. No reports means unknown,
    # which is neutral -- only an explicit "nothing around" scores below 1.
    # Bait and birds are different facts and combine rather than override.
    # Bait alone is food present; birds alone are a discounted proxy for it;
    # both together mean the bait is being driven up, which implies something
    # is driving it. See bait.combined_modifier.
    from .bait import combined_modifier as _combine
    m, which = _combine(feat.get("bait_signal"), feat.get("bird_signal"))
    if which:
        mods[which] = m

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
    pretty = {"bait": "bait seen nearby", "birds": "birds working nearby",
              "bait_worked_by_birds": "bait being driven up — birds on it", "heat_night": "heat pushing the bite to dark",
              "heat_daytime": "daytime heat", "tide_stage": "wrong tide stage",
              "spot_quality": "spot quality", "spring_tide": "neap tide",
              "wind_against_tide": "wind against tide"}
    for k, v in result["modifiers"].items():
        name = pretty.get(k, k.replace("_", " "))
        if v < thresholds.get(k, 0.95):
            bits.append(f"held back by {name}")
        elif v > 1.05:
            bits.append(f"boosted for {name}")
    return "; ".join(bits) if bits else "middling on every axis"
