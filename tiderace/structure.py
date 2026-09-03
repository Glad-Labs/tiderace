"""Find the bumps: places the bottom stands up out of what is around it.

This is a different question from the one `heat.py` answers, and the honest
thing to say up front is that the potential surface cannot do this. Its
resolution is the current-station Voronoi -- about 38 patches for the whole
bay. A hump is a hundred metres across. The surface will never see one.

Structure comes from the bottom, not the water, and the bottom is the highest
resolution data in the project: 25,895 charted soundings, each one a real
measurement at a real point, against a current field measured in 3 nm hops.

The method is a bathymetric position index. For each sounding, compare it to
the water around it:

    relief = median(depth of neighbours within R) - depth(here)

Positive relief means this point stands shallower than its surroundings --
a hump, a rock pile, the top of a ledge. Median rather than mean because a
second bump inside the radius would drag a mean and leave the real one
looking ordinary.

Three things stop it producing nonsense:

  **Non-maximum suppression.** One hump carries a dozen soundings, and
  without suppression it is reported as a dozen discoveries. Only the
  shallowest sounding in a cluster survives.

  **A neighbour floor.** In thinly surveyed water the "neighbours" are half a
  kilometre away and say nothing about a fifty-metre feature. Too few
  neighbours means no opinion, not a low score.

  **Reported spacing.** Every candidate carries the median distance to its
  neighbours, because relief computed from soundings 400 m apart is a
  different claim from relief computed at 40 m.

WHAT THIS IS NOT: a fish finder. It finds structure, and structure is
necessary but nowhere near sufficient. Worse, the source is biased in a way
that matters -- a chart exists to keep vessels off the shallow spots, so
surveyors sound hazards deliberately and densely. Shallow outliers are
therefore over-represented on purpose. A "discovery" here may be a
well-surveyed hazard that every local already knows, which is why every
candidate reports how close it is to charted rock, wreck and obstruction.

Each candidate also reports `depth_suits`: which species' *published* depth
band its top falls inside, and what that band actually claims. That labels a
bump, it does not rank one -- ranking here is by relief, because relief is
what distinguishes one coordinate from its neighbour. Only two of the fourteen
scored species have a depth band at all, so an empty `depth_suits` means
nothing published reaches this depth rather than nothing lives here.

The point of the list is that it is falsifiable. Go, drift it, log what
happens. That is the loop the whole project is short of.
"""

from __future__ import annotations

import json
import math
import os

from . import bathy

CHART_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "charts")
SOUNDINGS = os.path.join(CHART_DIR, "soundings.geojson")

# Defaults chosen for inshore structure. A 200 m radius asks "is this shallower
# than the water within a couple of boat lengths of a drift", which is the
# scale you can actually hold a position over.
RADIUS_M = 200.0
MIN_RELIEF_FT = 6.0
MIN_NEIGHBOURS = 8
CLUSTER_M = 150.0
M_PER_DEG_LAT = 110_540.0


def _m_per_deg_lon(lat: float) -> float:
    return 111_320.0 * math.cos(math.radians(lat))


def _dist_m(la1, lo1, la2, lo2, mpl) -> float:
    dy = (la1 - la2) * M_PER_DEG_LAT
    dx = (lo1 - lo2) * mpl
    return math.hypot(dx, dy)


def load_soundings(path: str = SOUNDINGS) -> list[tuple[float, float, float]]:
    """(lat, lon, depth_ft) for every charted sounding."""
    with open(path) as fh:
        gj = json.load(fh)
    out = []
    for f in gj.get("features", []):
        d = (f.get("properties") or {}).get("depth_ft")
        g = f.get("geometry") or {}
        c = g.get("coordinates")
        if d is None or not c or len(c) < 2:
            continue
        out.append((float(c[1]), float(c[0]), float(d)))
    return out


def _index(points, cell_deg: float):
    """Grid hash. 26k points against each other is 670M comparisons; against
    the nine cells that could hold a neighbour it is a few dozen."""
    idx: dict[tuple[int, int], list[int]] = {}
    for i, (la, lo, _) in enumerate(points):
        key = (int(la / cell_deg), int(lo / cell_deg))
        idx.setdefault(key, []).append(i)
    return idx


def _near(idx, points, i, radius_m, cell_deg, mpl):
    la, lo, _ = points[i]
    ky, kx = int(la / cell_deg), int(lo / cell_deg)
    out = []
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            for j in idx.get((ky + dy, kx + dx), ()):
                if j == i:
                    continue
                d = _dist_m(la, lo, points[j][0], points[j][1], mpl)
                if d <= radius_m:
                    out.append((d, j))
    return out


def _median(v):
    s = sorted(v)
    n = len(s)
    if not n:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


def candidates(bbox=None, radius_m: float = RADIUS_M,
               min_relief_ft: float = MIN_RELIEF_FT,
               min_neighbours: int = MIN_NEIGHBOURS,
               cluster_m: float = CLUSTER_M, limit: int = 40,
               points=None) -> list[dict]:
    """Rank places that stand up out of the bottom around them.

    bbox is (south, west, north, east) or None for everything charted.
    """
    pts = points if points is not None else load_soundings()
    if bbox:
        s, w, n, e = (float(v) for v in bbox)
        pts = [p for p in pts if s <= p[0] <= n and w <= p[1] <= e]
    if not pts:
        return []

    mid_lat = sum(p[0] for p in pts) / len(pts)
    mpl = _m_per_deg_lon(mid_lat)
    cell_deg = radius_m / M_PER_DEG_LAT
    idx = _index(pts, cell_deg)

    found = []
    for i, (la, lo, dep) in enumerate(pts):
        near = _near(idx, pts, i, radius_m, cell_deg, mpl)
        if len(near) < min_neighbours:
            continue                      # too thin to have an opinion
        depths = [pts[j][2] for _, j in near]
        surround = _median(depths)
        relief = surround - dep
        if relief < min_relief_ft:
            continue
        # Only the top of the feature, not its flanks: if anything nearby is
        # shallower, that thing is the bump and this is its side.
        if min(depths) < dep:
            continue
        found.append({
            "lat": round(la, 5), "lon": round(lo, 5),
            "depth_ft": round(dep, 1),
            "surround_ft": round(surround, 1),
            "relief_ft": round(relief, 1),
            "drop_ft": round(max(depths) - dep, 1),
            "neighbours": len(near),
            # Relief measured from soundings 400 m apart is a different claim
            # from the same number measured at 40 m.
            "spacing_m": round(_median([d for d, _ in near]), 0),
        })

    # Non-maximum suppression. One hump carries a dozen soundings and would
    # otherwise be reported as a dozen finds.
    found.sort(key=lambda c: (-c["relief_ft"], c["depth_ft"]))
    kept: list[dict] = []
    for c in found:
        if any(_dist_m(c["lat"], c["lon"], k["lat"], k["lon"], mpl) < cluster_m
               for k in kept):
            continue
        kept.append(c)
        if len(kept) >= limit:
            break
    return kept


def _load_points(name: str):
    path = os.path.join(CHART_DIR, name + ".geojson")
    if not os.path.exists(path):
        return []
    try:
        with open(path) as fh:
            gj = json.load(fh)
    except (OSError, ValueError):
        return []
    out = []
    for f in gj.get("features", []):
        g = f.get("geometry") or {}
        if g.get("type") != "Point":
            continue
        c = g.get("coordinates")
        if c and len(c) >= 2:
            out.append((float(c[1]), float(c[0])))
    return out


def depth_suits(depth_ft) -> list[dict]:
    """Which scored species' published depth band contains this depth.

    Two of the fourteen carry a band (fluke and black sea bass); the other
    twelve have no publication behind one and are therefore absent from every
    answer this returns. That is the point of the shape: an empty list means "no
    species has a published depth band reaching here", NOT "nothing lives
    here". A tautog does not appear at any depth, and the reason is in
    `score.PROFILES` -- the literature says structure decides where they are,
    so a depth answer for them would be invented.

    `fit` is the band's own trapezoid, so 1.0 is inside the cited plateau and
    anything between 0 and 1 is on a ramp toward the published edge.
    """
    from . import score
    if depth_ft is None:
        return []
    try:
        d = float(depth_ft)
    except (TypeError, ValueError):
        return []
    out = []
    for key, prof in score.PROFILES.items():
        if not prof.depth:
            continue
        fit = score.trapezoid(d, *prof.depth)
        if fit <= 0:
            continue
        out.append({"species": key, "name": prof.name, "fit": round(fit, 3),
                    # Carried with the number, not left behind in score.py.
                    # The fluke band in particular is a lower bound, and a
                    # deep bump scoring 1.0 on it has met no upper limit
                    # rather than met a preference.
                    "claim": prof.depth_claim})
    out.sort(key=lambda r: (-r["fit"], r["species"]))
    return out


def annotate(cands: list[dict]) -> list[dict]:
    """How close each candidate sits to something already on the chart.

    A chart is drawn to keep vessels off the shallow spots, so hazards are
    sounded deliberately and densely and shallow outliers are over-represented
    by design. A candidate 30 m off a charted rock is not a discovery; it is
    the rock. Saying so is the difference between a list worth fishing and a
    list of things every local already knows.
    """
    known = {k: _load_points(k) for k in ("rocks", "wrecks", "obstructions")}
    for c in cands:
        mpl = _m_per_deg_lon(c["lat"])
        for kind, pts in known.items():
            if not pts:
                continue
            d = min(_dist_m(c["lat"], c["lon"], la, lo, mpl) for la, lo in pts)
            c[kind[:-1] + "_m"] = round(d, 0)
        # Named explicitly. Globbing every key ending in "_m" swept up
        # sample_m and spacing_m -- the grid resolution -- and reported the
        # 36 m sample step as the distance to the nearest rock, which made
        # every candidate in a scan look like a charted hazard.
        near = [c[k] for k in ("rock_m", "wreck_m", "obstruction_m") if k in c]
        c["charted_hazard_m"] = min(near) if near else None
        c["novel"] = (c["charted_hazard_m"] is None
                      or c["charted_hazard_m"] > 100)
        # What the depth alone is worth, per species that has a published
        # band. This says nothing about the relief above it -- a bump is
        # structure, and structure is the thing this module measures.
        c["depth_suits"] = depth_suits(c.get("depth_ft"))
    return cands


# ---- the DEM scan -------------------------------------------------------
#
# The sounding method above is limited by the survey, not the arithmetic: the
# median gap between charted soundings in the bay is about 150 m, so a
# fifty-metre hump falls between them and cannot be seen at all. Run over the
# bay it returns eleven candidates and most are drying rocks at 0.3 ft --
# shoreline hazards, sounded densely because a chart exists to keep boats off
# them, which is exactly the bias this module warns about.
#
# The DEM is a different instrument. Sampled over a 550 m box off Whale Rock
# it returned 961 of 961 points with 4.4 m (14 ft) of relief and a median
# change of 7 cm between adjacent samples 18 m apart -- smooth, but carrying
# real shape rather than an interpolated plane. That is fine enough to hold a
# bump, and it is the thing to scan.
#
# It is modelled, not measured. `bathy` says so on every feature it makes and
# so does this: `model: True` rides on every candidate.

SCAN_INNER_M = 60.0      # ignore the peak itself and its immediate shoulder
SCAN_OUTER_M = 220.0     # "the water around it" at drift scale


def scan(bbox, n: int = 61, inner_m: float = SCAN_INNER_M,
         outer_m: float = SCAN_OUTER_M, min_relief_ft: float = 3.0,
         min_depth_ft: float = 10.0, limit: int = 30, grid=None) -> list[dict]:
    """Bumps in a box, from the elevation model.

    bbox is (south, west, north, east) -- this module's order. `bathy` takes
    (west, south, east, north), and crossing the two samples a different ocean
    entirely; it put the bottom of the bay at 2125 ft the first time. The swap
    happens here, once, and a test pins it.
    """
    south, west, north, east = (float(v) for v in bbox)
    grid = grid if grid is not None else bathy.sample_grid(
        (west, south, east, north), n)
    if not grid:
        return []

    mid = (south + north) / 2.0
    step_y = (north - south) / (n - 1) * M_PER_DEG_LAT
    step_x = (east - west) / (n - 1) * _m_per_deg_lon(mid)
    step = (step_y + step_x) / 2.0
    r_in = max(1, int(round(inner_m / step)))
    r_out = max(r_in + 1, int(round(outer_m / step)))

    found = []
    for i in range(n):
        for j in range(n):
            # A cell within one ring of the edge has a one-sided ring, and a
            # ring missing its deep half reports relief that is an artefact of
            # where the box was drawn. The first run put four "bumps" on the
            # western boundary at exactly the bbox longitude.
            if (i < r_out or j < r_out or i >= n - r_out or j >= n - r_out):
                continue
            here = grid[i][j]
            if here is None or here >= 0:        # land, or above the waterline
                continue
            # You cannot drift a bump that is a foot under the surface. Without
            # a floor this returns the shoreline: the first run came back with
            # tops at 0.5, 0.9 and 1.2 ft, which are drying rocks.
            if -here * 3.28084 < min_depth_ft:
                continue
            ring, inside = [], []
            for di in range(-r_out, r_out + 1):
                for dj in range(-r_out, r_out + 1):
                    ii, jj = i + di, j + dj
                    if not (0 <= ii < n and 0 <= jj < n):
                        continue
                    v = grid[ii][jj]
                    if v is None or v >= 0:
                        continue
                    cheb = max(abs(di), abs(dj))
                    if cheb == 0:
                        continue
                    if cheb <= r_in:
                        inside.append(v)
                    elif cheb <= r_out:
                        ring.append(v)
            if len(ring) < 12:
                continue
            # Elevation is negative down, so a bump sits HIGHER than its ring.
            surround = _median(ring)
            relief_m = here - surround
            if relief_m <= 0:
                continue
            relief_ft = relief_m * 3.28084
            if relief_ft < min_relief_ft:
                continue
            # The top, not the flank: anything inside the inner radius that is
            # shallower means the peak is over there.
            if inside and max(inside) > here:
                continue
            found.append({
                "lat": round(south + (north - south) * i / (n - 1), 5),
                "lon": round(west + (east - west) * j / (n - 1), 5),
                "depth_ft": round(-here * 3.28084, 1),
                "surround_ft": round(-surround * 3.28084, 1),
                "relief_ft": round(relief_ft, 1),
                "drop_ft": round((here - min(ring)) * 3.28084, 1),
                "ring": len(ring),
                "sample_m": round(step, 0),
                "model": True,
            })

    found.sort(key=lambda c: -c["relief_ft"])
    mpl = _m_per_deg_lon(mid)
    kept: list[dict] = []
    for c in found:
        if any(_dist_m(c["lat"], c["lon"], k["lat"], k["lon"], mpl) < inner_m
               for k in kept):
            continue
        kept.append(c)
        if len(kept) >= limit:
            break
    return kept


# A bump is tens of metres across. Sampled coarser than this the grid steps
# straight over it, and the scan returns "nothing here" for water full of
# structure -- the most dangerous answer this module could give, because it
# reads as knowledge rather than as blindness.
USABLE_SAMPLE_M = 60.0


def scan_view(bbox, n: int = 61, **kw) -> dict:
    """A scan plus an honest account of whether the box could hold an answer.

    Zoomed out to the whole bay, n=61 puts 600 m between samples and every
    bump in Rhode Island falls between two of them. The empty list that comes
    back is indistinguishable from flat bottom unless something says so.
    """
    south, west, north, east = (float(v) for v in bbox)
    mid = (south + north) / 2.0
    step_y = (north - south) / (n - 1) * M_PER_DEG_LAT
    step_x = (east - west) / (n - 1) * _m_per_deg_lon(mid)
    step = (step_y + step_x) / 2.0

    usable = step <= USABLE_SAMPLE_M
    out = {
        "bbox": [south, west, north, east],
        "n": n,
        "sample_m": round(step, 0),
        "usable": usable,
        "model": True,
        "bumps": [],
    }
    if not usable:
        out["note"] = (
            "Samples are %.0f m apart here; a bump is tens of metres across, "
            "so this box would step over one. Zoom in and scan again -- an "
            "empty list at this scale means the grid is too coarse to see, "
            "not that the bottom is flat." % step)
        return out

    bumps = annotate(scan(bbox, n=n, **kw))
    out["bumps"] = bumps
    out["note"] = (
        "%d found, %d more than 100 m from charted rock, wreck or "
        "obstruction. Modelled bathymetry, not soundings: this says the bottom "
        "has shape here, not that anything lives on it."
        % (len(bumps), sum(1 for b in bumps if b.get("novel"))))
    return out
