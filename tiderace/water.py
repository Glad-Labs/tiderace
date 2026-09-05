"""The water as an image: sea-surface temperature and chlorophyll, drawn.

Matt, 5 September 2026: do we have the chlorophyll mapped? We fetched it for
one point and never drew it. ERDDAP will render either grid as a transparent
PNG for a bounding box, which drops straight onto the map as an image source:
no tiling, no key, one request per box per day. This module builds those
requests, fetches through the server so the phone talks to nothing but the
tailnet, and keeps the bytes on disk by day so the boat has yesterday's
picture without signal.

  sst    MUR, 1 km, daily. The fronts the offshore scorer ranks are gradients
         in exactly this field; seeing the field is how a ranked position
         becomes a place on a picture.
  chl    VIIRS chlorophyll, daily. Water colour as a productivity proxy: the
         green is the food, the clean blue edge beside it is usually where
         you want to be. Cloud blanks it on many days and the layer says so
         rather than showing an empty picture as "no plankton".

Both are drawn with a fixed colour scale so a colour means the same thing
every day, and the legend says what the scale is. The image is data, not a
score: nothing here ranks anything.
"""

from __future__ import annotations

import os
import urllib.parse
import urllib.request
from datetime import date, timedelta

from . import cache

# MUR is served from the PFEG node; the chlorophyll dataset moved to
# coastwatch.noaa.gov and the old address redirects there. Ask the new one.
SST_BASE = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/jplMURSST41.transparentPng"
CHL_BASE = "https://coastwatch.noaa.gov/erddap/griddap/noaacwNPPVIIRSSQchlaDaily.transparentPng"
UA = "tiderace (+https://github.com/Glad-Labs/tiderace)"
CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "cache", "water")

LAYERS = {
    "sst": {"label": "Sea-surface temperature — MUR 1 km, daily",
            "units": "°F", "scale": (55, 80),           # fixed, so a colour means one thing
            "note": "Fronts are where the colour changes fastest; the offshore "
                    "positions sit on the sharpest of them."},
    "chl": {"label": "Chlorophyll — VIIRS, daily, cloud permitting",
            "units": "mg/m³", "scale": (0.1, 10),      # log scale in ERDDAP
            "note": "Green is plankton, blue is clean water. Cloud blanks it; "
                    "a blank picture is a cloudy day, not empty water."},
}

# The box the offshore scorer works in, with the bay on top of it.
DEFAULT_BBOX = (41.0, -72.2, 41.9, -70.4)      # south, west, north, east
MAX_SPAN_DEG = 3.0


def _c(f: float) -> float:
    return (f - 32) * 5 / 9


def url_for(layer: str, bbox, when: date) -> str:
    """The ERDDAP request for one layer, one box, one day."""
    south, west, north, east = (float(v) for v in bbox)
    if layer == "sst":
        lo, hi = LAYERS["sst"]["scale"]
        q = (f"analysed_sst%5B({when.isoformat()}T09:00:00Z)%5D"
             f"%5B({south}):({north})%5D%5B({west}):({east})%5D"
             f"&.draw=surface&.vars=longitude%7Clatitude%7Canalysed_sst"
             f"&.colorBar=Rainbow2%7C%7C%7C{_c(lo):.1f}%7C{_c(hi):.1f}%7C"
             f"&.bgColor=0x00000000&.size=900%7C700")
        return f"{SST_BASE}?{q}"
    if layer == "chl":
        lo, hi = LAYERS["chl"]["scale"]
        # This dataset's latitude runs north to south, so the range is given
        # that way round or ERDDAP answers with an error, not an image.
        q = (f"chlor_a%5B({when.isoformat()}T12:00:00Z)%5D%5B(0.0)%5D"
             f"%5B({north}):({south})%5D%5B({west}):({east})%5D"
             f"&.draw=surface&.vars=longitude%7Clatitude%7Cchlor_a"
             f"&.colorBar=Rainbow2%7C%7CLog%7C{lo}%7C{hi}%7C"
             f"&.bgColor=0x00000000&.size=900%7C700")
        return f"{CHL_BASE}?{q}"
    raise ValueError(f"unknown water layer {layer!r}")


def check_bbox(bbox) -> tuple[float, float, float, float]:
    south, west, north, east = (float(v) for v in bbox)
    if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
        raise ValueError("bbox must be south,west,north,east")
    if north - south > MAX_SPAN_DEG or east - west > MAX_SPAN_DEG:
        raise ValueError(f"bbox wider than {MAX_SPAN_DEG} degrees; this is a picture "
                         "of one piece of water, not the Atlantic")
    return round(south, 2), round(west, 2), round(north, 2), round(east, 2)


def cache_path(layer: str, bbox, when: date) -> str:
    s, w, n, e = bbox
    return os.path.join(CACHE_DIR, f"{layer}_{when.isoformat()}_{s}_{w}_{n}_{e}.png")


def fetch(layer: str, bbox, when: date | None = None, root: str | None = None,
          _get=None) -> dict:
    """The image bytes for a layer, walking back up to five days for one that
    is populated. Cached on disk per day; a cached day is never re-fetched.
    Returns {bytes, date, cached}; raises if nothing is available."""
    if layer not in LAYERS:
        raise ValueError(f"unknown water layer {layer!r}")
    bbox = check_bbox(bbox)
    when = when or date.today()
    get = _get or _http_get
    last = None
    for back in range(1, 6):
        d = when - timedelta(days=back)
        path = cache_path(layer, bbox, d)
        if root:
            path = os.path.join(root, os.path.basename(path))
        if os.path.exists(path):
            with open(path, "rb") as fh:
                return {"bytes": fh.read(), "date": d.isoformat(), "cached": True}
        try:
            blob = get(url_for(layer, bbox, d))
        except Exception as exc:                                  # noqa: BLE001
            last = exc
            continue
        if not blob or blob[:8] != b"\x89PNG\r\n\x1a\n":
            last = ValueError("ERDDAP answered without an image")
            continue
        cache.write_bytes(path, blob)
        return {"bytes": blob, "date": d.isoformat(), "cached": False}
    raise RuntimeError(f"no {layer} image for the last five days: {last}")


def _http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()
