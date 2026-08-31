"""NOAA ENC chart features — the structure that actually holds fish.

Rocks, wrecks, obstructions and bottom type come from NOAA's Electronic
Navigational Charts via the ENC Direct to GIS service. This is public domain
data and by far the highest-value overlay for fishing: a striper does not care
about a pretty basemap, it cares about a boulder field with current over it.

Features are fetched once and cached to GeoJSON on disk. The map then loads
instantly and works offline, and NOAA's service is hit once per region rather
than once per page view.

Usage bands matter. Narragansett Bay detail lives in the *harbour* band —
querying the general band returns nothing, which is a silent and very
confusing zero if you do not know to look for it.
"""

from __future__ import annotations

import json
import math
import os
import urllib.parse
import urllib.request

from . import cache

# Identifies the project rather than a person: a sysadmin reading their logs
# wants to know what is calling and where to complain, and the repository
# answers both without publishing an email address.
UA = "tiderace (+https://github.com/Glad-Labs/tiderace)"

ENC = "https://encdirect.noaa.gov/arcgis/rest/services/encdirect"
BAND = "enc_harbour"
PAGE = 1000                     # service maxRecordCount

CHART_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "charts")

# The water actually fished, which is wider than "the bay". The old box was
# (-71.60, 41.28, -71.10, 41.88) and quietly excluded Charlestown Breachway --
# the most-fished spot in the log -- along with Block Island and the wind farm,
# because they sit west and south of it. A mark outside the box reported "no
# chart data here", which reads as a fact about the area rather than about our
# cache, and that is exactly the wrong way round.
#
# Coverage was never the constraint: the harbour band has 2,024 soundings
# around the turbines and 473 around Charlestown. We were simply not asking.
BAY_BBOX = (-71.95, 40.95, -71.10, 41.88)

# name -> (layer id, what it is)
LAYERS: dict[str, tuple[int, str]] = {
    "rocks":        (34, "Underwater and awash rocks"),
    "wrecks":       (36, "Wrecks"),
    "obstructions": (33, "Obstructions"),
    "turbulence":   (35, "Water turbulence — rips and overfalls"),
    "kelp":         (74, "Weed and kelp beds"),
    "seabed":       (71, "Seabed type — sand, mud, rock, boulders"),
    # Analysis layers. Not overlays -- these are geometry the resolver reasons
    # over, which is why they are excluded from `available()` below.
    "land":         (233, "Land areas — the coastline as polygons"),
    "depth_area":   (227, "Charted depth ranges"),
    # Depth shading tells you "somewhere between 18 and 30 feet". These two say
    # which, and where the edge is -- the edge being the part fish actually sit
    # on. Soundings are the single densest layer we pull (~26k points over this
    # box) so the map only draws them close in.
    "soundings":    (76,  "Spot soundings — individual charted depths"),
    "contours":     (104, "Depth contours — the shape of the bottom"),
    # Lateral buoys and lights. Not decoration: they are how you say where you
    # are to somebody else, and how you find a mark again in the dark.
    "buoys":        (6,   "Lateral buoys"),
    "lights":       (11,  "Lights and beacons"),
}

# Layers fetched for computation rather than display. Land polygons as a map
# overlay would just be a second, worse basemap; what they are actually for is
# answering "is there an island between this mark and that current station?".
ANALYSIS = {"land"}

# S-57 WATLEV: water level effect.
WATLEV = {
    1: "partly submerged at high water", 2: "always dry",
    3: "always under water", 4: "covers and uncovers",
    5: "awash", 6: "subject to flooding", 7: "floating",
}


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={
        "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def fetch(name: str, bbox=BAY_BBOX, band: str | None = None,
          layer_id: int | None = None) -> dict:
    """Fetch one layer as GeoJSON, paging past the service record limit."""
    # Band and layer are parameters, not globals. The server is threaded
    # and two cells can be in flight at once; swapping a module-level
    # BAND under them would hand one request the other's chart band.
    if layer_id is None:
        layer_id, _ = LAYERS[name]
    band = band or BAND
    xmin, ymin, xmax, ymax = bbox
    geom = json.dumps({"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax,
                       "spatialReference": {"wkid": 4326}})

    feats: list[dict] = []
    offset = 0
    while True:
        q = urllib.parse.urlencode({
            "geometry": geom, "geometryType": "esriGeometryEnvelope",
            "inSR": "4326", "outSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": "*", "resultOffset": offset,
            "resultRecordCount": PAGE, "f": "geojson",
        })
        page = _get(f"{ENC}/{band}/MapServer/{layer_id}/query?{q}")
        got = page.get("features", [])
        feats.extend(got)
        if len(got) < PAGE:
            break
        offset += PAGE
        if offset > 50_000:                       # runaway guard
            break

    gj = {"type": "FeatureCollection",
          "features": [_clean(f) for f in feats if f.get("geometry")]}
    return _thin(gj, SIMPLIFY_DEG.get(name), MIN_AREA_DEG2.get(name))


# Depth areas are the only layer heavy enough to matter on the wire: 2,325
# polygons carry ~306,000 vertices, most of them describing wiggles far below
# what any zoom level renders. Simplified on write, not on read, so the phone
# pays nothing for it. Land is deliberately left alone -- it never goes to the
# browser, and the crossing test should reason over the real coastline.
# Contours were the largest layer on the wire at 6.4 MB, and not because there
# is 6.4 MB of information in them: _thin only knew about polygons and points,
# so line coordinates were never even rounded, let alone simplified. A depth
# contour is a smooth curve -- 13 m of positional slop is invisible at any zoom
# this map offers and is far inside the accuracy of the survey behind it.
SIMPLIFY_DEG = {"depth_area": 1.2e-4, "contours": 1.2e-4}   # ~13 m
COORD_PLACES = 5                        # ~1.1 m

# Sub-hectare slivers of depth area are shoreline noise: invisible at any zoom
# this map offers, and a large share of the vertex count. Dropping them is what
# takes the layer from "the browser never finishes parsing it" to instant.
MIN_AREA_DEG2 = {"depth_area": 2e-7}    # ~1,800 m²


def _perp_distance(p, a, b) -> float:
    """Point-to-segment distance in degree space, longitude scaled to match."""
    k = math.cos(math.radians(a[1]))
    px, py = (p[0] - a[0]) * k, p[1] - a[1]
    bx, by = (b[0] - a[0]) * k, b[1] - a[1]
    span = bx * bx + by * by
    if span == 0:
        return math.hypot(px, py)
    t = max(0.0, min(1.0, (px * bx + py * by) / span))
    return math.hypot(px - t * bx, py - t * by)


def _simplify_ring(ring: list, tol: float) -> list:
    """Douglas-Peucker, iterative so a long ring cannot blow the stack."""
    if len(ring) < 4:
        return ring
    keep = [False] * len(ring)
    keep[0] = keep[-1] = True
    stack = [(0, len(ring) - 1)]
    while stack:
        lo, hi = stack.pop()
        worst, worst_i = tol, None
        for i in range(lo + 1, hi):
            d = _perp_distance(ring[i], ring[lo], ring[hi])
            if d > worst:
                worst, worst_i = d, i
        if worst_i is not None:
            keep[worst_i] = True
            stack.append((lo, worst_i))
            stack.append((worst_i, hi))
    out = [pt for pt, k in zip(ring, keep) if k]
    # A ring that collapses below a triangle is no longer an area.
    return out if len(out) >= 4 else ring


def _ring_area(ring: list) -> float:
    """Shoelace area in square degrees. Only used for relative comparison."""
    a = 0.0
    for i in range(len(ring) - 1):
        a += ring[i][0] * ring[i + 1][1] - ring[i + 1][0] * ring[i][1]
    return abs(a) / 2


def _thin(gj: dict, tol: float | None, min_area: float | None = None) -> dict:
    """Round coordinates, and simplify polygon rings where asked."""
    def ring(r):
        r = _simplify_ring(r, tol) if tol else r
        return [[round(x, COORD_PLACES), round(y, COORD_PLACES)] for x, y in
                ((c[0], c[1]) for c in r)]

    kept = []
    for f in gj.get("features", []):
        g = f.get("geometry") or {}
        t = g.get("type")
        if t == "Polygon":
            g["coordinates"] = [ring(r) for r in g["coordinates"]]
            if min_area and _ring_area(g["coordinates"][0]) < min_area:
                continue
        elif t == "MultiPolygon":
            g["coordinates"] = [[ring(r) for r in poly] for poly in g["coordinates"]]
            if min_area:
                g["coordinates"] = [poly for poly in g["coordinates"]
                                    if _ring_area(poly[0]) >= min_area]
                if not g["coordinates"]:
                    continue
        elif t == "LineString":
            g["coordinates"] = ring(g["coordinates"])
        elif t == "MultiLineString":
            g["coordinates"] = [ring(r) for r in g["coordinates"]]
        elif t == "Point":
            c = g["coordinates"]
            g["coordinates"] = [round(c[0], COORD_PLACES), round(c[1], COORD_PLACES)]
        kept.append(f)
    gj["features"] = kept
    return gj


def covers(lat: float, lon: float, bbox=BAY_BBOX, pad: float = 0.05) -> bool:
    """Is this point inside the area the cached chart layers describe?

    The land, depth and structure layers are one bay. Outside it every chart
    lookup returns "nothing here", which is indistinguishable from "open
    water" and is the wrong answer for a mark off another coast. Callers ask
    this first so they can say "no data" rather than imply "all clear".
    """
    x0, y0, x1, y1 = bbox
    return (x0 - pad) <= lon <= (x1 + pad) and (y0 - pad) <= lat <= (y1 + pad)


def _clean(f: dict) -> dict:
    """Drop chart bookkeeping, keep what a fisherman would want, and decode
    the S-57 codes that are meaningless as raw integers."""
    p = f.get("properties") or {}
    out: dict = {}

    if p.get("CATWRK"):
        out["type"] = str(p["CATWRK"])
    if p.get("NATSUR"):
        out["bottom"] = str(p["NATSUR"])
    if p.get("NATQUA"):
        out["bottom_quality"] = str(p["NATQUA"])
    if p.get("CATOBS"):
        out["type"] = str(p["CATOBS"])

    # The depth over a feature, in metres. Three different S-57 fields carry it
    # depending on the layer, and using only VALSOU is why the soundings layer
    # came back with 25,895 points and not one depth on any of them:
    #   VALSOU  depth over a rock, wreck or obstruction
    #   Z       a spot sounding, which is the whole content of that layer
    #   VALDCO  the value of a depth contour
    for src in ("VALSOU", "Z", "VALDCO"):
        v = p.get(src)
        if isinstance(v, (int, float)):
            out["depth_m"] = round(float(v), 1)
            out["depth_ft"] = round(float(v) * 3.28084, 1)
            break

    # DRVAL1/DRVAL2 are the shallow and deep limits of a charted depth area,
    # in metres. They are the only reason to keep a depth polygon at all.
    for src, m_key, ft_key in (("DRVAL1", "depth_min_m", "depth_min_ft"),
                               ("DRVAL2", "depth_max_m", "depth_max_ft")):
        v2 = p.get(src)
        if isinstance(v2, (int, float)):
            out[m_key] = round(float(v2), 1)
            out[ft_key] = round(float(v2) * 3.28084, 1)

    w = p.get("WATLEV")
    try:
        out["water_level"] = WATLEV.get(int(w))
    except (TypeError, ValueError):
        pass

    if p.get("OBJNAM"):
        out["name"] = str(p["OBJNAM"])

    f["properties"] = {k: v for k, v in out.items() if v is not None}
    return f


def cache_all(bbox=BAY_BBOX, out_dir: str | None = None) -> dict[str, int]:
    out_dir = out_dir or CHART_DIR
    os.makedirs(out_dir, exist_ok=True)
    counts: dict[str, int] = {}
    for name in LAYERS:
        try:
            gj = fetch(name, bbox)
        except Exception as exc:                                  # noqa: BLE001
            counts[name] = -1
            print(f"  ! {name}: {exc}")
            continue
        path = os.path.join(out_dir, f"{name}.geojson")
        cache.write_json(path, gj)
        counts[name] = len(gj["features"])
        print(f"  {name:<14} {counts[name]:>5} features  "
              f"{os.path.getsize(path)/1024:>7.0f} KB")
    return counts


# Parsed layers, keyed by name and mtime. `structure_near` walks five layers
# per report and `point.report` is called per mark, so re-reading and
# re-parsing ~770 KB of GeoJSON every time was the single most expensive thing
# in a report. Keyed on mtime so a `tiderace charts` rebuild in the same
# process is picked up rather than served stale.
#
# Callers treat the result as read-only. Nothing here mutates it, and nothing
# should start: the object is shared now.
_LOADED: dict[str, tuple[float, dict]] = {}


def load(name: str) -> dict | None:
    path = os.path.join(CHART_DIR, f"{name}.geojson")
    if not os.path.exists(path):
        return None
    mtime = os.path.getmtime(path)
    hit = _LOADED.get(name)
    if hit and hit[0] == mtime:
        return hit[1]
    with open(path) as fh:
        gj = json.load(fh)
    _LOADED[name] = (mtime, gj)
    return gj


def available(include_analysis: bool = False) -> list[str]:
    return [n for n in LAYERS
            if (include_analysis or n not in ANALYSIS)
            and os.path.exists(os.path.join(CHART_DIR, f"{n}.geojson"))]


def bottom_at(lat: float, lon: float, max_nm: float = 0.35) -> dict | None:
    """Nearest charted seabed sample to a point.

    Bottom type is the missing half of a structure model: tautog and black sea
    bass want rock and boulder, fluke want sand. The charts know this and the
    scorer currently does not -- surfacing it per spot is the first step.
    """
    gj = load("seabed")
    if not gj:
        return None
    best, best_d = None, 1e9
    for f in gj["features"]:
        g = f.get("geometry") or {}
        if g.get("type") != "Point":
            continue
        x, y = g["coordinates"][0], g["coordinates"][1]
        # Local flat-earth approximation is ample at this scale.
        dx = (x - lon) * 45.0    # nm per degree lon at 41.5N
        dy = (y - lat) * 60.0    # nm per degree lat
        d = (dx * dx + dy * dy) ** 0.5
        if d < best_d and f["properties"].get("bottom"):
            best, best_d = f, d
    if best is None or best_d > max_nm:
        return None
    return {"bottom": best["properties"]["bottom"],
            "quality": best["properties"].get("bottom_quality"),
            "distance_nm": round(best_d, 2)}


# --------------------------------------------------------------- land geometry
#
# The reason this exists: tidal current is constrained by geography in a way
# that straight-line distance is not. Nearest-by-distance will happily bind a
# mark on the Sakonnet to a station in the middle of the bay, with Aquidneck
# Island in between -- a different body of water, running at a different phase.
# Testing whether the path crosses land is a cheap, chart-derived stand-in for
# "is this the same water?", and it is the difference between a current number
# that means something and one that is confidently wrong.

_LAND_INDEX: list | None = None


def _polygons(geom: dict) -> list:
    """Every polygon in a geometry, as [exterior_ring, *holes] lists."""
    t = geom.get("type")
    if t == "Polygon":
        return [geom["coordinates"]]
    if t == "MultiPolygon":
        return list(geom["coordinates"])
    return []


def _bbox(ring: list) -> tuple[float, float, float, float]:
    xs = [c[0] for c in ring]
    ys = [c[1] for c in ring]
    return min(xs), min(ys), max(xs), max(ys)


def land_index() -> list:
    """Bounding-box index over the land polygons, built once.

    A path test touches every candidate station, so the inner loop runs a few
    hundred times per lookup. Rejecting a polygon on its bounding box first
    turns that from noticeable into free.
    """
    global _LAND_INDEX
    if _LAND_INDEX is not None:
        return _LAND_INDEX
    gj = load("land")
    idx: list = []
    if gj:
        for f in gj.get("features", []):
            for poly in _polygons(f.get("geometry") or {}):
                if not poly or len(poly[0]) < 3:
                    continue
                idx.append((_bbox(poly[0]), poly))
    _LAND_INDEX = idx
    return idx


def _in_ring(x: float, y: float, ring: list) -> bool:
    """Ray casting. Ring is a list of [lon, lat]."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > y) != (yj > y):
            if x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
        j = i
    return inside


def _in_polygon(x: float, y: float, poly: list) -> bool:
    if not _in_ring(x, y, poly[0]):
        return False
    return not any(_in_ring(x, y, hole) for hole in poly[1:])


def _segments_cross(ax, ay, bx, by, cx, cy, dx, dy) -> bool:
    def side(px, py, qx, qy, rx, ry):
        v = (qy - py) * (rx - qx) - (qx - px) * (ry - qy)
        return 0 if abs(v) < 1e-14 else (1 if v > 0 else 2)
    o1 = side(ax, ay, bx, by, cx, cy)
    o2 = side(ax, ay, bx, by, dx, dy)
    o3 = side(cx, cy, dx, dy, ax, ay)
    o4 = side(cx, cy, dx, dy, bx, by)
    return o1 != o2 and o3 != o4


def on_land(lat: float, lon: float) -> bool | None:
    """Is this point on charted land? None when the layer is not cached."""
    idx = land_index()
    if not idx:
        return None
    for (x0, y0, x1, y1), poly in idx:
        if x0 <= lon <= x1 and y0 <= lat <= y1 and _in_polygon(lon, lat, poly):
            return True
    return False


# Shore marks sit *on* the coastline, and so do some current stations. A plain
# does-the-segment-touch-a-polygon test therefore rejects the correct station
# for almost every shore spot -- Beavertail and Castle Hill are both charted as
# land, because they are headlands you fish *from*.
#
# So the question is not "does this path touch land" but "how much land". A
# path that clips a headland for eighty metres, or that only appears to because
# NOAA rounded a station to two decimal places, is still the same water. A path
# with half a mile of Aquidneck Island in it is not.
END_BUFFER_NM = 0.08          # ~150 m trimmed off each end
LAND_TOLERANCE_NM = 0.15      # ~280 m of land before the path is disqualified
SAMPLE_NM = 0.05              # ~90 m between samples along the path


def land_span_nm(lat1: float, lon1: float, lat2: float, lon2: float,
                 buffer_nm: float = END_BUFFER_NM) -> float | None:
    """How much of the path between two points lies over charted land, in nm.

    None means the land layer is not cached, which is emphatically not the
    same answer as 0.0. A caller that treats the two alike is back to guessing.
    """
    if not land_index():
        return None

    span_lat = lat2 - lat1
    span_lon = (lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    length_nm = math.hypot(span_lat, span_lon) * 60.0
    if length_nm <= 2 * buffer_nm:
        return 0.0            # nothing between them to cross

    f = buffer_nm / length_nm
    a_lat, a_lon = lat1 + span_lat * f, lon1 + (lon2 - lon1) * f
    b_lat, b_lon = lat2 - span_lat * f, lon2 - (lon2 - lon1) * f

    inner_nm = length_nm - 2 * buffer_nm
    steps = max(2, int(inner_nm / SAMPLE_NM))
    hits = 0
    for i in range(steps + 1):
        t = i / steps
        if on_land(a_lat + (b_lat - a_lat) * t, a_lon + (b_lon - a_lon) * t):
            hits += 1
    return round(inner_nm * hits / (steps + 1), 3)


def crosses_land(lat1: float, lon1: float, lat2: float, lon2: float,
                 tolerance_nm: float = LAND_TOLERANCE_NM) -> bool | None:
    """Is there enough land between two points to call them different water?"""
    span = land_span_nm(lat1, lon1, lat2, lon2)
    if span is None:
        return None
    return span > tolerance_nm


# Rings and bearings for the outward search below. Sixteen bearings is enough
# to find the water off any headland without turning this into a real solver.
_WATER_RINGS = (0.03, 0.06, 0.12, 0.2, 0.3, 0.45, 0.65)


def nearest_water(lat: float, lon: float) -> dict | None:
    """Walk a mark that sits on charted land out to the water beside it.

    Shore spots are the normal case, not the exception: you fish Beavertail
    from Beavertail, and the coordinate you write down is the rock you stood
    on. Every current station is offshore of it, so measuring land crossings
    from the rock itself disqualifies all of them. Measuring from the water a
    hundred metres away asks the question that was actually meant.
    """
    if on_land(lat, lon) is not True:
        return None
    for r in _WATER_RINGS:
        best = None
        for i in range(16):
            brg = math.radians(i * 22.5)
            dlat = r * math.cos(brg) / 60.0
            dlon = r * math.sin(brg) / (60.0 * math.cos(math.radians(lat)))
            cand_lat, cand_lon = lat + dlat, lon + dlon
            if on_land(cand_lat, cand_lon) is False:
                best = {"lat": round(cand_lat, 5), "lon": round(cand_lon, 5),
                        "distance_nm": round(r, 3),
                        "bearing_deg": int(i * 22.5)}
                break
        if best:
            return best
    return None


_DEPTH_INDEX: list | None = None


def depth_index() -> list:
    """Bounding-box index over charted depth areas, built once.

    The depth layer is an order of magnitude larger than the others, so
    re-reading it per lookup would put a tenth of a second on every request
    the map makes.
    """
    global _DEPTH_INDEX
    if _DEPTH_INDEX is not None:
        return _DEPTH_INDEX
    gj = load("depth_area")
    idx: list = []
    if gj:
        for f in gj.get("features", []):
            props = f.get("properties") or {}
            if "depth_min_m" not in props and "depth_max_m" not in props:
                continue
            for poly in _polygons(f.get("geometry") or {}):
                if not poly or len(poly[0]) < 3:
                    continue
                idx.append((_bbox(poly[0]), poly, props))
    _DEPTH_INDEX = idx
    return idx


def depth_at(lat: float, lon: float) -> dict | None:
    """Charted depth range containing a point.

    Depth areas nest, so the smallest polygon containing the point is the
    tightest range on offer.
    """
    best, best_area = None, None
    for (x0, y0, x1, y1), poly, props in depth_index():
        if not (x0 <= lon <= x1 and y0 <= lat <= y1):
            continue
        if not _in_polygon(lon, lat, poly):
            continue
        area = (x1 - x0) * (y1 - y0)
        if best_area is None or area < best_area:
            best, best_area = props, area
    if best is None:
        return None
    return {"min_ft": best.get("depth_min_ft"), "max_ft": best.get("depth_max_ft"),
            "min_m": best.get("depth_min_m"), "max_m": best.get("depth_max_m")}


# ------------------------------------------------------- charts on demand
#
# Shipping whole GeoJSON layers to the browser works for one bay and cannot
# work for Montauk to the Cape. That box is seventeen times the area of
# Narragansett Bay -- 37,000 square nautical miles against 2,100 -- and the
# current layers are already 17 MB. Naively widened they would be a quarter of
# a gigabyte, which no phone is going to parse, let alone over a cell
# connection on the water.
#
# So chart data is cut into a fixed grid and fetched a cell at a time, only
# where you actually look. The grid is fixed rather than following the viewport
# because a stable key is what makes a cell cacheable: pan away and back and it
# is the same cell, already on disk and already in the service worker. A
# viewport-shaped query would be a different URL every time and would cache
# nothing.
#
# Cells are fetched from NOAA once and kept forever -- ENC updates are measured
# in months, and a stale rock is still a rock. Coverage therefore grows to
# wherever you have been, which is the right shape for someone who runs the
# same water repeatedly.

CELL_DEG = 0.25                 # ~15 nm of latitude; a few hundred KB per cell
CELL_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "charts", "cells")

# The water this is willing to serve at all. Generous -- Montauk to well east of
# the Cape, and south to the shelf break where the canyons start.
SERVE_BBOX = (-74.30, 39.40, -69.60, 42.70)


def cell_key(lat: float, lon: float) -> tuple[int, int]:
    """Grid indices for a coordinate. Integers so the key is exact -- deriving
    it from floats would make neighbouring requests miss each other."""
    return (math.floor(lat / CELL_DEG), math.floor(lon / CELL_DEG))


def cell_bbox(iy: int, ix: int) -> tuple[float, float, float, float]:
    return (round(ix * CELL_DEG, 6), round(iy * CELL_DEG, 6),
            round((ix + 1) * CELL_DEG, 6), round((iy + 1) * CELL_DEG, 6))


def cells_for(bbox, limit: int = 12) -> list[tuple[int, int]]:
    """Every grid cell a viewport touches, nearest the centre first.

    Capped: a zoomed-out view can span hundreds of cells, and fetching them all
    would hammer NOAA for data drawn two pixels wide. The map only asks for
    detail layers when it is zoomed in far enough for them to mean something.
    """
    w, s, e, n = bbox
    w, s = max(w, SERVE_BBOX[0]), max(s, SERVE_BBOX[1])
    e, n = min(e, SERVE_BBOX[2]), min(n, SERVE_BBOX[3])
    if w >= e or s >= n:
        return []
    cy, cx = (s + n) / 2, (w + e) / 2
    out = []
    iy0, ix0 = cell_key(s, w)
    iy1, ix1 = cell_key(n, e)
    for iy in range(iy0, iy1 + 1):
        for ix in range(ix0, ix1 + 1):
            bx = cell_bbox(iy, ix)
            d = math.hypot((bx[1] + bx[3]) / 2 - cy, (bx[0] + bx[2]) / 2 - cx)
            out.append((d, iy, ix))
    out.sort()
    return [(iy, ix) for _, iy, ix in out[:limit]]


def cell_path(name: str, iy: int, ix: int) -> str:
    return os.path.join(CELL_DIR, f"{name}_{iy}_{ix}.geojson")


def cell(name: str, iy: int, ix: int, refresh: bool = False) -> dict:
    """One grid cell of one layer, from disk or from NOAA.

    An empty cell is cached too. Most of this box is open water with no rocks
    in it, and re-asking NOAA every time you pan across nothing would be the
    slowest possible way to learn that.
    """
    if name not in LAYERS:
        raise KeyError(name)
    path = cell_path(name, iy, ix)
    if not refresh:
        hit = cache.read_json(path)
        if hit is not None:
            return hit
    gj = fetch_banded(name, cell_bbox(iy, ix))
    cache.write_json(path, gj)
    return gj

# ENC is published in usage bands, and which one holds your water depends on
# how far out you are. The harbour band has 4,475 soundings in a cell off
# Montauk and NOTHING at all on the shelf; the coastal and general bands are
# the opposite -- sparse inshore, but they are the only thing out where the
# canyons are. A single band therefore cannot serve someone who runs from
# Montauk to the Cape and then keeps going.
#
# So a cell tries bands finest-first and keeps the first that actually returns
# something. Inshore that is harbour detail; offshore it falls through to
# whatever exists. The band that answered is recorded on the response, because
# "twelve soundings" from the general band and "twelve soundings" from the
# harbour band mean very different things about how well surveyed the bottom is.
BAND_LAYERS = {
    # band          soundings  contours
    "enc_harbour":  {"soundings": 76,  "contours": 104},
    "enc_approach": {"soundings": 80,  "contours": 108},
    "enc_coastal":  {"soundings": 61,  "contours": 82},
    "enc_general":  {"soundings": 50,  "contours": 64},
}
BAND_ORDER = ("enc_harbour", "enc_approach", "enc_coastal", "enc_general")


def _band_count(name: str, bbox, band: str, layer_id: int) -> int:
    """How many features this band has here, without downloading them.

    returnCountOnly is a cheap query, which is what makes picking the right
    band affordable: four counts and one real fetch beats four real fetches.
    """
    xmin, ymin, xmax, ymax = bbox
    geom = json.dumps({"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax,
                       "spatialReference": {"wkid": 4326}})
    q = urllib.parse.urlencode({
        "geometry": geom, "geometryType": "esriGeometryEnvelope",
        "inSR": "4326", "spatialRel": "esriSpatialRelIntersects",
        "returnCountOnly": "true", "f": "json",
    })
    try:
        d = _get(f"{ENC}/{band}/MapServer/{layer_id}/query?{q}")
        return int(d.get("count") or 0)
    except Exception:                                             # noqa: BLE001
        return 0


def fetch_banded(name: str, bbox, bands=BAND_ORDER) -> dict:
    """Fetch a layer from whichever band actually has the most here.

    The first cut took the finest band with ANY features, which is wrong in the
    middle distance: off Block Island the harbour band has 13 contours in a
    cell where general has 16, and "first non-empty" quietly picked the 13.
    Bands overlap, and which one is richest is a property of the cell, not of
    the distance from shore.

    Ties go to the finer band -- same feature count from harbour and coastal
    means the harbour version is the better surveyed one.

    Only the depth layers are banded. Rocks, wrecks and kelp are inshore
    features by nature and the harbour band is where they live.
    """
    if name not in BAND_LAYERS["enc_harbour"]:
        gj = fetch(name, bbox)
        gj["band"] = BAND
        return gj

    best_band, best_lid, best_n = None, None, 0
    for band in bands:
        lid = BAND_LAYERS.get(band, {}).get(name)
        if lid is None:
            continue
        n = _band_count(name, bbox, band, lid)
        if n > best_n:                       # strict: ties keep the finer band
            best_band, best_lid, best_n = band, lid, n

    if not best_band:
        # Genuinely nothing charted here, which is itself worth caching.
        return {"type": "FeatureCollection", "features": [], "band": None}

    gj = fetch(name, bbox, band=best_band, layer_id=best_lid)
    gj["band"] = best_band
    return gj
