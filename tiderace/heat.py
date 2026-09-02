"""Score a lattice of coordinates, and say how much of it is real.

The obvious version of this feature is a smooth gradient over the bay. That
version would be a lie, and measuring it is how you find out why.

Sample 81 points across Narragansett Bay and they bind to **31 distinct
current stations**. Push the lattice to 40x40 and it is still 31-ish, because
there are only 38 in-bay CO-OPS current stations in existence. The current at
a cell *is* the nearest station's prediction; nothing measures the water
between them. So the true spatial resolution of this surface is the station
Voronoi, and a smooth raster would be drawing the interpolation function
rather than the ocean.

Measured on a 9x9 lattice at one instant, striped bass:

    score        21.0 - 65.8, sd 15.6      (real variation, not a flat field)
    confidence   29 good / 15 fair / 27 poor
    current      sd 0.263   <- carries the map
    temp         sd 0.182   (only 3 distinct values bay-wide)
    season       sd 0.152
    light        sd 0.000   |
    wind         sd 0.000   |- regional constants: they move the whole
    pressure     sd 0.000   |  surface up and down, they never differentiate

Two things follow. First, **this is a current map with a temperature tint** --
which is the app's whole thesis, so that is the right answer, but it should be
named rather than dressed up as six independent factors. Second, **a third of
the bay is "poor" confidence** and must not be painted as though it were
known: `confidence` rides on every cell so the renderer can wash it out.

What this deliberately does NOT do is invent a depth term. Depth is on every
cell because it is worth seeing and Matt asked for it, but `score.PROFILES`
has no depth preference for any species and this module will not be the place
one gets guessed into existence. Getting there means what the temperature
bands took: published numbers, cited, per species. Until then depth is
reported, not scored, and `depth_scored` says so on every response.
"""

from __future__ import annotations

import math
from datetime import datetime

from . import bathy, cache, features, score, spots, stations
from .sources import SourceError

# A lattice finer than this buys nothing: it subdivides the same station
# Voronoi into smaller pieces of the same number, which reads as precision
# that is not there.
MAX_N = 40
DEFAULT_N = 20


def _key(species: str, bbox, n: int, when: datetime) -> str:
    s, w, nn, e = (round(float(v), 3) for v in bbox)
    return "heat-%s-%s-%s-%s-%s-%d-%s" % (
        species, s, w, nn, e, n, when.strftime("%Y%m%dT%H"))


def _limiting(terms: dict, weights: dict) -> str | None:
    """Which factor is costing this cell the most points.

    A number alone invites "the app says 41 here"; the factor behind it
    invites "the tide is wrong, come back at the ebb", which is the only one
    of the two a person can act on.
    """
    lost = {k: weights.get(k, 0.0) * (1.0 - v) for k, v in terms.items()}
    lost = {k: v for k, v in lost.items() if v > 0}
    return max(lost, key=lost.get) if lost else None


def _depth_ft(elev_m):
    """Seafloor elevation in metres (negative down) to depth in feet.

    Land, and anything at or above the waterline, comes back None rather than
    zero: a zero would render as "very shallow water" instead of "not water".
    """
    if elev_m is None:
        return None
    try:
        e = float(elev_m)
    except (TypeError, ValueError):
        return None
    if e >= 0:
        return None
    return round(-e * 3.28084, 1)


def surface(species: str, bbox, when: datetime | None = None,
            n: int = DEFAULT_N, refresh: bool = False) -> dict:
    """Score an n x n lattice over `bbox` at one instant.

    bbox is (south, west, north, east). Cells that raise `SourceError` -- land,
    or off every chart -- are dropped rather than defaulted, so the surface has
    holes where the data does. That is the intended appearance.
    """
    if species not in score.PROFILES:
        raise ValueError("unknown species %r" % species)
    n = max(4, min(int(n), MAX_N))
    when = (when or datetime.now()).replace(minute=0, second=0, microsecond=0)

    ck = _key(species, bbox, n, when)
    if not refresh:
        hit = cache.read_json(ck)
        if hit:
            return hit

    south, west, north, east = (float(v) for v in bbox)
    lats = [south + (north - south) * i / (n - 1) for i in range(n)]
    lons = [west + (east - west) * j / (n - 1) for j in range(n)]

    # Depth for the whole lattice in one pass; per-cell lookups would be the
    # slow way to get the same numbers.
    #
    # Two traps, both hit on the way in. bathy takes (west, south, east,
    # north) while this module carries (south, west, north, east), and it
    # returns seafloor ELEVATION in metres, negative down -- not depth, and
    # not feet. Passing one convention to the other put the bottom of the bay
    # at 2125 ft, which is the useful kind of wrong: absurd enough to notice.
    # A subtler mix-up would have shipped.
    try:
        depths = bathy.sample_grid((west, south, east, north), n)
    except Exception:
        depths = None

    # Pass one: bind every cell to its stations. This is the expensive part
    # per cell and the cheap part per station.
    placed: list[tuple[int, int, float, float, dict]] = []
    for i, la in enumerate(lats):
        for j, lo in enumerate(lons):
            try:
                res = stations.resolve(la, lo)
            except (SourceError, ValueError):
                continue
            if not res.get("current"):
                continue
            placed.append((i, j, la, lo, res))

    # Pass two: score once per distinct binding. Cells sharing a current
    # station share its prediction exactly -- there is no measurement between
    # them to tell them apart -- so computing per cell would be arithmetic
    # dressed up as resolution.
    groups: dict[tuple, list] = {}
    for i, j, la, lo, res in placed:
        cid = (res.get("current") or {}).get("id")
        tid = (res.get("tide") or {}).get("id")
        groups.setdefault((cid, tid), []).append((i, j, la, lo, res))

    prof = score.PROFILES[species]
    cells: list[dict] = []
    bindings: dict[str, dict] = {}

    for (cid, tid), members in groups.items():
        i0, j0, la0, lo0, res0 = members[0]
        try:
            spot, res0 = spots.at_coord(la0, lo0, resolution=res0)
            rows = features.build(spot, when, 1, 60, species=species)
            if not rows:
                continue
            row = rows[0]
            out = score.score(species, row, exposed=row["exposed"],
                              prior=spot.prior(species),
                              best_stage=spot.best_stage)
        except (SourceError, ValueError, KeyError):
            continue

        bkey = "%s|%s" % (cid, tid)
        bindings[bkey] = {
            "current_station": cid,
            "tide_station": tid,
            "cells": len(members),
            "current_speed": row.get("current_speed"),
            "current_stage": row.get("current_stage"),
            "water_temp_f": row.get("water_temp_f"),
            "terms": out.get("terms", {}),
        }
        lim = _limiting(out.get("terms", {}), prof.weights)

        for i, j, la, lo, res in members:
            d = None
            if depths:
                try:
                    d = depths[i][j]
                except (IndexError, TypeError):
                    d = None
            cells.append({
                "lat": round(la, 5), "lon": round(lo, 5),
                "score": out["score"],
                # The renderer washes a cell out by this, so a station three
                # miles away cannot look like one you are sitting on.
                "confidence": res.get("confidence"),
                "binding": bkey,
                "limiting": lim,
                "depth_ft": _depth_ft(d),
            })

    surf = {
        "species": species,
        "species_name": prof.name,
        "when": when.isoformat(),
        "bbox": [south, west, north, east],
        "n": n,
        "cells": cells,
        "bindings": bindings,
        "counts": {
            "requested": n * n,
            "water": len(placed),
            "scored": len(cells),
            "bindings": len(bindings),
        },
        # Said on every response so a client cannot render this as though
        # depth were one of the inputs.
        "depth_scored": False,
        "depth_note": ("Depth is reported, not scored. No species profile "
                       "carries a depth preference, and none will be guessed "
                       "in; that needs published numbers per species, the way "
                       "the temperature bands were done."),
        "resolution_note": (
            "The current at a cell is the nearest station's prediction, so "
            "cells sharing a station are identical by construction. %d cells "
            "resolve to %d stations -- that, not the lattice, is the real "
            "resolution of this surface."
            % (len(cells), len(bindings))),
    }
    cache.write_json(ck, surf)
    return surf


def spread(surf: dict) -> dict:
    """How much the surface actually varies, and how much of it is trustworthy.

    A heat map that is flat, or that is all low-confidence, should be able to
    say so rather than leaving the reader to infer it from the colours.
    """
    vals = [c["score"] for c in surf.get("cells", [])]
    if not vals:
        return {"cells": 0}
    mean = sum(vals) / len(vals)
    sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))
    conf: dict[str, int] = {}
    for c in surf["cells"]:
        k = c.get("confidence") or "unknown"
        conf[k] = conf.get(k, 0) + 1
    lim: dict[str, int] = {}
    for c in surf["cells"]:
        k = c.get("limiting") or "none"
        lim[k] = lim.get(k, 0) + 1
    return {
        "cells": len(vals),
        "min": round(min(vals), 1),
        "max": round(max(vals), 1),
        "spread": round(max(vals) - min(vals), 1),
        "sd": round(sd, 2),
        "confidence": conf,
        "limiting": lim,
    }
