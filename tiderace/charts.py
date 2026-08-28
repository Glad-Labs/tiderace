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
import os
import urllib.parse
import urllib.request

ENC = "https://encdirect.noaa.gov/arcgis/rest/services/encdirect"
BAND = "enc_harbour"
PAGE = 1000                     # service maxRecordCount

CHART_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "charts")

# Narragansett Bay plus Point Judith and the Sakonnet.
BAY_BBOX = (-71.60, 41.28, -71.10, 41.88)

# name -> (layer id, what it is)
LAYERS: dict[str, tuple[int, str]] = {
    "rocks":        (34, "Underwater and awash rocks"),
    "wrecks":       (36, "Wrecks"),
    "obstructions": (33, "Obstructions"),
    "turbulence":   (35, "Water turbulence — rips and overfalls"),
    "kelp":         (74, "Weed and kelp beds"),
    "seabed":       (71, "Seabed type — sand, mud, rock, boulders"),
}

# S-57 WATLEV: water level effect.
WATLEV = {
    1: "partly submerged at high water", 2: "always dry",
    3: "always under water", 4: "covers and uncovers",
    5: "awash", 6: "subject to flooding", 7: "floating",
}


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers={
        "User-Agent": "tiderace (mattg@gladlabs.io)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def fetch(name: str, bbox=BAY_BBOX) -> dict:
    """Fetch one layer as GeoJSON, paging past the service record limit."""
    layer_id, _ = LAYERS[name]
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
        page = _get(f"{ENC}/{BAND}/MapServer/{layer_id}/query?{q}")
        got = page.get("features", [])
        feats.extend(got)
        if len(got) < PAGE:
            break
        offset += PAGE
        if offset > 50_000:                       # runaway guard
            break

    return {"type": "FeatureCollection",
            "features": [_clean(f) for f in feats if f.get("geometry")]}


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

    # VALSOU is the sounding over the feature, in metres.
    v = p.get("VALSOU")
    if isinstance(v, (int, float)):
        out["depth_m"] = round(float(v), 1)
        out["depth_ft"] = round(float(v) * 3.28084, 1)

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
        with open(path, "w") as fh:
            json.dump(gj, fh, separators=(",", ":"))
        counts[name] = len(gj["features"])
        print(f"  {name:<14} {counts[name]:>5} features  "
              f"{os.path.getsize(path)/1024:>7.0f} KB")
    return counts


def load(name: str) -> dict | None:
    path = os.path.join(CHART_DIR, f"{name}.geojson")
    if not os.path.exists(path):
        return None
    with open(path) as fh:
        return json.load(fh)


def available() -> list[str]:
    return [n for n in LAYERS if os.path.exists(
        os.path.join(CHART_DIR, f"{n}.geojson"))]


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
