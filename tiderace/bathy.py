"""Bottom shape offshore, from an elevation model rather than a chart.

Nautical charts are compiled for navigation, and offshore navigation only needs
to know that the water is deep enough. Measured on equal-sized cells, the ENC
harbour band carries 475 depth contours in the mid-bay and the general band
carries 2; on the shelf it is 5. That detail is not being lost somewhere in
this project -- it was never compiled, because no chart-maker needs to draw the
edge of a canyon for a ship that is passing over it in 200 metres of water.

An angler does need it. The shelf break and the canyon edges are the structure,
and they are exactly what the chart generalises away.

So this takes a different source: NOAA NCEI's DEM mosaic, a global seafloor
elevation model at about three metres, free and unauthenticated. It samples a
grid of depths and runs marching squares over it to produce contour lines at
whatever interval you ask for, anywhere, including water no chart contours.

**These are not charted depths and must never be treated as such.** A charted
sounding is a survey: somebody measured that spot and a hydrographer signed for
it. A DEM value is a model, interpolated between soundings that may be decades
old and kilometres apart. It is good enough to show you where the bottom falls
away and useless for deciding whether you will clear a rock. Everything here is
tagged `model: true` and the map draws it in a different style for that reason,
never mixed silently with ENC contours.

Two properties of the service shape the design:

  * `getSamples` caps at 1,000 points per request and truncates silently past
    that, so a fine grid is assembled from several overlapping blocks rather
    than asked for in one go.
  * The request has to be a POST. A multipoint geometry of even 256 points
    overflows the URI length limit on a GET.
"""

from __future__ import annotations

import json
import math
import os
import urllib.parse
import urllib.request

from . import cache

DEM = ("https://gis.ngdc.noaa.gov/arcgis/rest/services/"
       "DEM_mosaics/DEM_all/ImageServer")
UA = "tiderace (+https://github.com/Glad-Labs/tiderace)"

# The service returns at most 1000 samples per request and silently truncates
# past that -- which would leave the tail of a grid missing rather than
# erroring. So a request is capped at BLOCK x BLOCK and a finer grid is
# assembled from several of them.
#
# GRID is the full resolution per cell. 120 over a quarter-degree cell is about
# 230 m between samples, which resolves a canyon edge rather than implying one.
# It costs sixteen requests and roughly ten seconds the first time a cell is
# looked at, and nothing ever again -- the DEM does not change and the result
# is cached forever. Detail is worth ten seconds once.
BLOCK = 31                       # 961 points, inside the 1000 cap
MAX_SAMPLES = 1000
GRID = 120
assert BLOCK * BLOCK <= MAX_SAMPLES

BATHY_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "charts", "bathy")

# Metres of depth. Tight inshore where the bottom matters at close range, wider
# offshore where the interesting feature is the shelf break itself. Deliberately
# not evenly spaced: a 10 m interval out to 200 m would be forty lines nobody
# reads, and a 50 m interval inshore would draw nothing at all.
LEVELS = tuple(
    # 2 m steps to 30 -- inshore structure is measured in feet, not tens of feet
    list(range(2, 31, 2))
    # 5 m to 100, which covers the whole shelf
    + list(range(35, 101, 5))
    # 10 m to 200 across the shelf break, where the bottom starts to fall away
    + list(range(110, 201, 10))
    # then wide, because past 200 m the interesting thing is the canyon itself
    + [250, 300, 400, 500, 750, 1000, 1500, 2000, 3000])


class BathyError(RuntimeError):
    pass


def _sample_block(bbox, n: int) -> list[list[float | None]]:
    """One request: an n x n grid of seafloor elevation, metres, negative down.

    Rows run south to north so the array reads like a map with north up, which
    is what the contour code and anyone debugging it assumes.
    """
    w, s, e, nn = bbox
    pts = []
    for j in range(n):
        for i in range(n):
            pts.append([w + (e - w) * i / (n - 1) if n > 1 else w,
                        s + (nn - s) * j / (n - 1) if n > 1 else s])

    body = urllib.parse.urlencode({
        "geometry": json.dumps({"points": pts,
                                "spatialReference": {"wkid": 4326}}),
        "geometryType": "esriGeometryMultipoint",
        "returnFirstValueOnly": "true",
        "f": "json",
    }).encode()
    req = urllib.request.Request(
        f"{DEM}/getSamples", data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            data = json.load(r)
    except Exception as exc:                                      # noqa: BLE001
        raise BathyError(f"{type(exc).__name__}: {exc}") from exc

    # Samples are keyed by index into the points we sent. The service does not
    # promise to return them in order and omits points it has no value for, so
    # the grid is filled by locationId rather than by position in the response.
    grid: list[list[float | None]] = [[None] * n for _ in range(n)]
    for smp in data.get("samples", []):
        try:
            k = int(smp.get("locationId"))
            val = float(smp.get("value"))
        except (TypeError, ValueError):
            continue
        if 0 <= k < n * n:
            grid[k // n][k % n] = val
    return grid


def sample_grid(bbox, n: int = GRID) -> list[list[float | None]]:
    """An n x n elevation grid, assembled from as many requests as it takes.

    Blocks overlap by one sample on each shared edge so the seam between them
    is a real shared value rather than two independent samples that disagree --
    a contour crossing the seam would otherwise kink or break.
    """
    if n <= BLOCK:
        return _sample_block(bbox, n)

    w, s, e, nn = bbox
    # How many blocks per side, and how many samples each contributes.
    nb = math.ceil((n - 1) / (BLOCK - 1))
    step = (BLOCK - 1)
    grid: list[list[float | None]] = [[None] * n for _ in range(n)]
    for bj in range(nb):
        for bi in range(nb):
            i0, j0 = bi * step, bj * step
            i1, j1 = min(i0 + BLOCK - 1, n - 1), min(j0 + BLOCK - 1, n - 1)
            if i0 >= i1 or j0 >= j1:
                continue
            sub = (w + (e - w) * i0 / (n - 1), s + (nn - s) * j0 / (n - 1),
                   w + (e - w) * i1 / (n - 1), s + (nn - s) * j1 / (n - 1))
            side = max(i1 - i0, j1 - j0) + 1
            block = _sample_block(sub, side)
            for jj in range(min(side, j1 - j0 + 1)):
                for ii in range(min(side, i1 - i0 + 1)):
                    grid[j0 + jj][i0 + ii] = block[jj][ii]
    return grid


def _interp(p1, p2, v1, v2, level):
    """Where along an edge the contour crosses. Guarded against v1 == v2, which
    happens on a flat bottom and would otherwise divide by zero."""
    if v2 == v1:
        return p1
    t = (level - v1) / (v2 - v1)
    return (p1[0] + (p2[0] - p1[0]) * t, p1[1] + (p2[1] - p1[1]) * t)


def _cell_segments(x0, y0, x1, y1, va, vb, vc, vd, level):
    """Marching squares for one grid cell.

    Corners are (a) SW, (b) SE, (c) NE, (d) NW. Returns the line segments where
    the surface crosses `level`. The ambiguous saddle cases (5 and 10) are
    resolved with the centre average, which is the standard fix and matters
    here: a saddle is a col between two deeps, and getting it backwards joins
    two separate holes into one.
    """
    if None in (va, vb, vc, vd):
        return []                       # a gap in the model, not a flat bottom

    idx = (1 if va > level else 0) | (2 if vb > level else 0) \
        | (4 if vc > level else 0) | (8 if vd > level else 0)
    if idx in (0, 15):
        return []

    sw, se, ne, nw = (x0, y0), (x1, y0), (x1, y1), (x0, y1)
    bottom = _interp(sw, se, va, vb, level)
    right  = _interp(se, ne, vb, vc, level)
    top    = _interp(nw, ne, vd, vc, level)
    left   = _interp(sw, nw, va, vd, level)

    if idx in (1, 14):  return [(left, bottom)]
    if idx in (2, 13):  return [(bottom, right)]
    if idx in (3, 12):  return [(left, right)]
    if idx in (4, 11):  return [(right, top)]
    if idx in (6, 9):   return [(bottom, top)]
    if idx in (7, 8):   return [(left, top)]
    centre = (va + vb + vc + vd) / 4
    if idx == 5:
        return ([(left, top), (bottom, right)] if centre > level
                else [(left, bottom), (right, top)])
    if idx == 10:
        return ([(left, bottom), (right, top)] if centre > level
                else [(left, top), (bottom, right)])
    return []


def _join(segments, tol=1e-9):
    """Chain segments end to end into polylines.

    Marching squares emits unordered fragments. Drawing them as thousands of
    two-point lines works but makes labelling impossible and renders far
    slower, so they are stitched into runs first.
    """
    ends: dict = {}
    def key(p):
        return (round(p[0] / tol), round(p[1] / tol))
    for a, b in segments:
        ends.setdefault(key(a), []).append((a, b))
        ends.setdefault(key(b), []).append((b, a))

    used, lines = set(), []
    for i, seg in enumerate(segments):
        if i in used:
            continue
        used.add(i)
        line = [seg[0], seg[1]]
        # Extend forward, then backward, consuming any segment that shares an
        # endpoint. Each is used once; the `used` set is what stops a closed
        # ring from looping forever.
        for direction in (0, 1):
            if direction:
                line.reverse()
            while True:
                nxt = None
                for j, s2 in enumerate(segments):
                    if j in used:
                        continue
                    if key(s2[0]) == key(line[-1]):
                        nxt = (j, s2[1])
                    elif key(s2[1]) == key(line[-1]):
                        nxt = (j, s2[0])
                    if nxt:
                        break
                if not nxt:
                    break
                used.add(nxt[0])
                line.append(nxt[1])
        lines.append(line)
    return lines


def contours(bbox, levels=LEVELS, n: int = GRID,
             grid=None) -> dict:
    """Depth contours for a bbox, as GeoJSON, from the elevation model.

    `grid` is injectable so the contour maths can be tested against a known
    surface without going to the network.
    """
    g = sample_grid(bbox, n) if grid is None else grid
    n = len(g)
    w, s, e, nn = bbox
    dx = (e - w) / (n - 1)
    dy = (nn - s) / (n - 1)

    feats = []
    for depth in levels:
        level = -float(depth)           # elevation is negative below the surface
        segs = []
        for j in range(n - 1):
            for i in range(n - 1):
                x0, y0 = w + i * dx, s + j * dy
                segs += _cell_segments(x0, y0, x0 + dx, y0 + dy,
                                       g[j][i], g[j][i + 1],
                                       g[j + 1][i + 1], g[j + 1][i], level)
        if not segs:
            continue
        for line in _join(segs):
            if len(line) < 2:
                continue
            feats.append({
                "type": "Feature",
                "geometry": {"type": "LineString",
                             "coordinates": [[round(x, 6), round(y, 6)]
                                             for x, y in line]},
                "properties": {
                    "depth_m": depth,
                    "depth_ft": round(depth * 3.28084),
                    # Loud on every single feature, not just in a header
                    # somewhere: whatever consumes this must not be able to
                    # mistake it for a charted sounding.
                    "model": True,
                    "source": "NOAA NCEI DEM",
                },
            })
    return {"type": "FeatureCollection", "features": feats,
            "model": True,
            "note": "Modelled from an elevation grid, not charted soundings. "
                    "Not for navigation."}


def cell_path(iy: int, ix: int) -> str:
    return os.path.join(BATHY_DIR, f"bathy_{iy}_{ix}.geojson")


def cell(iy: int, ix: int, refresh: bool = False) -> dict:
    """One grid cell of modelled contours, cached like the chart cells.

    Same grid as `charts.cell` so the two line up and share a cache key shape.
    The DEM does not change, so these are kept indefinitely.
    """
    from . import charts
    path = cell_path(iy, ix)
    if not refresh:
        hit = cache.read_json(path)
        if hit is not None:
            return hit
    gj = contours(charts.cell_bbox(iy, ix))
    cache.write_json(path, gj)
    return gj
