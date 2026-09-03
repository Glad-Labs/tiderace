"""Everything tiderace knows about one coordinate.

`spots.py` holds nineteen curated places. This module answers the same
questions for anywhere else on the water, which is the whole point: the marks
that matter are the ones you found yourself, and they are not on a list.

Nothing here is new physics. `features.build` and `score.score` already take a
Spot and never asked where it came from -- the only thing missing was binding
an arbitrary coordinate to the NOAA stations that describe it, which
`stations.resolve` now does. This module is the join, and it exists as its own
module so the CLI and the map are looking at exactly the same report rather
than two implementations that drift.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from . import charts, protected as protectedmod, features, score, spots, stations
from .sources import SourceError


def windows(rows: list[dict], results: list[dict], threshold: float,
             max_hours: float = 3.0) -> list[dict]:
    """Find local score peaks and return a tight window around each.

    An earlier version merged every consecutive above-threshold sample, which
    produced "19:00-06:30" -- technically true and completely useless. A
    window you can act on is the shoulder of a peak, not the whole night, so
    each peak is trimmed to where the score is still within 12% of it and
    capped at `max_hours`.
    """
    scores = [r["score"] for r in results]
    n = len(scores)
    if n < 3:
        return []

    step = (rows[1]["time"] - rows[0]["time"]).total_seconds() / 60
    half_span = int((max_hours * 60 / step) / 2)

    # The endpoints are candidates too. Excluding them dropped the single most
    # actionable window there is -- "it is good right now and fading" -- because
    # that peak always lands on sample zero. A 68 at the top of the hour was
    # being reported as no window at all while a 55 six hours out was.
    peaks = []
    for i in range(n):
        if scores[i] < threshold:
            continue
        lo = max(0, i - half_span)
        hi = min(n, i + half_span + 1)
        if scores[i] >= max(scores[lo:hi]) - 1e-9:
            peaks.append(i)

    # Collapse peaks that sit on the same hump.
    merged = []
    for i in peaks:
        if merged and (i - merged[-1]) * step <= max_hours * 60:
            if scores[i] > scores[merged[-1]]:
                merged[-1] = i
        else:
            merged.append(i)

    out = []
    for i in merged:
        floor = scores[i] * 0.88
        a = b = i
        while a > 0 and scores[a - 1] >= floor and (i - a) * step < max_hours * 30:
            a -= 1
        while b < n - 1 and scores[b + 1] >= floor and (b - i) * step < max_hours * 30:
            b += 1
        out.append({"start": rows[a]["time"], "end": rows[b]["time"],
                    "best": results[i], "best_row": rows[i], "rows": b - a + 1})
    return out


STRUCTURE_LAYERS = ("rocks", "wrecks", "obstructions", "turbulence", "kelp")


def structure_near(lat: float, lon: float, max_nm: float = 0.25) -> dict[str, int]:
    """Charted hard structure within a short drift of a mark.

    Counts rather than positions: the useful fact at report time is "there are
    fourteen rocks here and none two hundred yards west", not a list.
    """
    out: dict[str, int] = {}
    for layer in STRUCTURE_LAYERS:
        gj = charts.load(layer)
        if not gj:
            continue
        n = 0
        for f in gj.get("features", []):
            g = f.get("geometry") or {}
            if g.get("type") != "Point":
                continue
            dx = (g["coordinates"][0] - lon) * 45.0     # nm per degree lon at 41.5N
            dy = (g["coordinates"][1] - lat) * 60.0
            if (dx * dx + dy * dy) ** 0.5 <= max_nm:
                n += 1
        if n:
            out[layer] = n
    return out


def report(lat: float, lon: float, species: str = "striped_bass",
           start: datetime | None = None, hours: int = 48,
           threshold: float = 45.0, top: int = 6,
           step_minutes: int = 30) -> dict:
    """Resolve, describe and score one coordinate.

    Returns the station binding and its caveats alongside the numbers, because
    at an arbitrary point the binding is the part most likely to be wrong and
    the reader has no curated table to fall back on.
    """
    if species not in score.PROFILES:
        raise ValueError(f"unknown species {species!r}")

    res = stations.resolve(lat, lon)
    spot, res = spots.at_coord(lat, lon, resolution=res)
    start = start or datetime.now().replace(minute=0, second=0, microsecond=0)

    rows = features.build(spot, start, hours, step_minutes, species=species)
    results = [score.score(species, r, exposed=r["exposed"],
                           prior=spot.prior(species),
                           best_stage=spot.best_stage) for r in rows]

    now = datetime.now()
    i_now = min(range(len(rows)),
                key=lambda i: abs((rows[i]["time"] - now).total_seconds()))

    return {
        "lat": lat, "lon": lon,
        "label": spot.label,
        "species": species,
        "species_name": score.PROFILES[species].name,
        "start": start.isoformat(),
        "hours": hours,
        "stations": {
            "current": res["current"], "tide": res["tide"], "temp": res.get("temp"),
            "rejected": res["current_rejected"],
            "alternates": res["current_alternates"],
            "confidence": res["confidence"], "warnings": res["warnings"],
        },
        "place": {
            "depth": charts.depth_at(lat, lon),
            "bottom": charts.bottom_at(lat, lon),
            "structure": structure_near(lat, lon),
            "on_land": res["on_land"],
            # "we looked and found nothing" and "we have no chart here" are
            # different facts, and only one of them is good news.
            "charted": charts.covers(lat, lon),
            "water_point": res.get("water_point"),
        },
        # Rules, not signals. Kept beside the place rather than the score so
        # nothing here can ever raise a number.
        "protected": protectedmod.advisory(lat, lon),
        # No history at a bare coordinate, so the spot-quality modifier is a
        # default rather than knowledge. Said out loud so a caller cannot
        # mistake 0.6 for a measurement.
        "prior": spot.prior(species),
        "prior_is_default": species not in spot.quality,
        "now": {
            "time": rows[i_now]["time"].isoformat(),
            "score": results[i_now]["score"],
            "explain": score.explain(results[i_now]),
            **{k: v for k, v in rows[i_now].items()
               if k != "time" and not isinstance(v, datetime)},
        },
        # Ranked by score to decide *which* windows make the cut, then shown
        # in time order because at a single mark you are reading a day, not a
        # league table. Truncating in time order would silently drop a better
        # window for being later.
        "windows": [{
            "start": w["start"].isoformat(),
            "end": w["end"].isoformat(),
            "score": w["best"]["score"],
            "explain": score.explain(w["best"]),
            "current_speed": w["best_row"]["current_speed"],
            "current_dir": w["best_row"]["current_dir"],
            "light_phase": w["best_row"]["light_phase"],
            "water_temp_f": w["best_row"]["water_temp_f"],
            "wind_kt": w["best_row"]["wind_kt"],
            "wind_dir": w["best_row"]["wind_dir"],
            "next_tide": w["best_row"]["next_tide"],
        } for w in sorted(
            sorted(windows(rows, results, threshold),
                   key=lambda w: w["best"]["score"], reverse=True)[:top],
            key=lambda w: w["start"])],
        "rows": rows,
        "results": results,
    }
