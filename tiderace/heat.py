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

Depth was reported and never scored here for as long as `score.PROFILES` had
no published band for anything. Two species now have one -- fluke and black
sea bass, both out of the RIDEM Narragansett Bay trawl survey, both cited on
the line that sets them -- so for those two this surface scores it, and
`depth_scored` says which case any given response is. The other four still
have no band and still get none. That is not a gap waiting to be filled by
feel: for three of the four the source was consulted and said depth is the
wrong variable. Nothing gets guessed in, which was always the rule.

Depth is also the first term that varies WITHIN a binding. Every other input a
cell has comes from its nearest stations, which is exactly why cells sharing a
station are identical by construction -- but the bottom is measured per cell.
So where a species has a band, the expensive station work still runs once per
binding and only the arithmetic runs per cell.
"""

from __future__ import annotations

import math
import os
from datetime import datetime

from . import bathy, cache, features, score, spots, stations
from .sources import SourceError

# A lattice finer than this buys nothing: it subdivides the same station
# Voronoi into smaller pieces of the same number, which reads as precision
# that is not there.
MAX_N = 40
DEFAULT_N = 20


# Under data/cache/, which is gitignored. A bare filename here writes the
# surface into whatever directory the process happens to be in -- for the
# server that is the repo root, which is how 142 cache files were once swept
# into a commit by `git add -A`.
HEAT_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "cache", "heat")


def _key(species: str, bbox, n: int, when: datetime) -> str:
    s, w, nn, e = (round(float(v), 3) for v in bbox)
    return os.path.join(HEAT_DIR, "heat-%s-%s-%s-%s-%s-%d-%s.json" % (
        species, s, w, nn, e, n, when.strftime("%Y%m%dT%H")))


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
            # Depth is deliberately absent from the binding record even when
            # it is scored: the binding is what two stations say about the
            # water, and depth is the one thing they do not say. `row` carries
            # no depth, so the value here would be the neutral placeholder --
            # a number nothing measured, published under a key that reads as
            # though it had.
            "terms": {k: v for k, v in out.get("terms", {}).items()
                      if k != "depth"},
        }

        for i, j, la, lo, res in members:
            d = None
            if depths:
                try:
                    d = depths[i][j]
                except (IndexError, TypeError):
                    d = None
            depth_ft = _depth_ft(d)

            # Re-score only where there is a band to apply. For the other four
            # species this is the same arithmetic twice, and `out` already
            # holds it. features.build -- the expensive part -- stays above,
            # once per binding.
            cell = out
            if prof.depth is not None:
                try:
                    cell = score.score(species, dict(row, depth_ft=depth_ft),
                                       exposed=row["exposed"],
                                       prior=spot.prior(species),
                                       best_stage=spot.best_stage)
                except (SourceError, ValueError, KeyError):
                    cell = out

            cells.append({
                "lat": round(la, 5), "lon": round(lo, 5),
                "score": cell["score"],
                # The renderer washes a cell out by this, so a station three
                # miles away cannot look like one you are sitting on.
                "confidence": res.get("confidence"),
                "binding": bkey,
                "limiting": _limiting(cell.get("terms", {}), prof.weights),
                "depth_ft": depth_ft,
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
        # Said on every response so a client can tell which of the two cases
        # it is holding, rather than inferring it from whether the numbers
        # happen to vary.
        "depth_scored": prof.depth is not None,
        "depth_note": (
            ("Depth is scored for %s: score.PROFILES carries a published band "
             "for it, cited on the line that sets it. It is also the only "
             "term on this surface measured per cell -- every other input a "
             "cell has comes from its stations." % prof.name)
            if prof.depth is not None else
            ("Depth is reported, not scored. %s carries no depth band. That "
             "is a recorded finding, not an omission -- score.PROFILES names "
             "the source consulted for each of the four unscored species and "
             "what it said, and for three of them it said depth is the wrong "
             "variable. None will be guessed in." % prof.name)),
        "resolution_note": (
            "The current at a cell is the nearest station's prediction, so "
            "cells sharing a station are identical by construction. %d cells "
            "resolve to %d stations -- that, not the lattice, is the real "
            "resolution of the water half of this surface.%s"
            % (len(cells), len(bindings),
               " Depth is the exception: it is measured per cell, so cells on "
               "one station can still differ." if prof.depth is not None else "")),
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
