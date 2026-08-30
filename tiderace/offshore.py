"""Offshore conditions. Facts, not a score.

The bay model works because tidal current dominates there and is measured at
38 stations. Seventeen miles out at the wind farm none of that applies: the
governing variables are water temperature, where it changes sharply, water
colour, and structure. Extrapolating a current prediction that far is how you
get a confident number that means nothing.

So this reports and does not rank. There are no weights here to be wrong
about, which is the point -- you are better at deciding where to run than any
prior I could invent, and you are the one who can see the birds.

  SST + breaks   NOAA CoastWatch MUR, 1 km daily
  chlorophyll    NOAA CoastWatch VIIRS, water colour as a productivity proxy
  sea state      the nearest NDBC buoy, live
  structure      wind-farm turbines, and whatever the charts hold
  who is around  OBIS occurrence records -- real dated positions, not a guess

Occurrence history plays the part the GSO trawl plays inshore: it says what
has actually been recorded near here, and in which months, rather than what I
imagine should be.
"""

from __future__ import annotations

import json
import math
import os
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta

from . import cache

ERDDAP = "https://coastwatch.pfeg.noaa.gov/erddap/griddap"
OBIS = "https://api.obis.org/v3"
NDBC = "https://www.ndbc.noaa.gov/data/realtime2"

CACHE = os.path.join(os.path.dirname(__file__), "..", ".cache", "offshore")
UA = "tiderace (+https://github.com/Glad-Labs/tiderace)"

# Block Island Wind Farm — five turbines, roughly 3 nm SE of the island.
TURBINES = [("BIWF-1", 41.1183, -71.5219), ("BIWF-2", 41.1128, -71.5106),
            ("BIWF-3", 41.1072, -71.4994), ("BIWF-4", 41.1017, -71.4881),
            ("BIWF-5", 41.0961, -71.4769)]

PELAGICS = {
    "mahi":           "Coryphaena hippurus",
    "yellowfin":      "Thunnus albacares",
    "bluefin":        "Thunnus thynnus",
    "bigeye":         "Thunnus obesus",
    "white marlin":   "Kajikia albida",
    "blue marlin":    "Makaira nigricans",
    "swordfish":      "Xiphias gladius",
    "wahoo":          "Acanthocybium solandri",
}


class OffshoreError(RuntimeError):
    pass


# Long per-request timeouts multiply badly: the chlorophyll fallback walks
# several days and two datasets, so a 90-second ceiling made a missing scene
# cost twenty minutes instead of failing fast.
TIMEOUT = 25


def _negcache(p: str) -> bool:
    """Remember misses too. Cloud cover means most chlorophyll days are empty,
    and re-asking for them on every run is the whole latency problem."""
    return os.path.exists(p + ".miss") and \
        time.time() - os.path.getmtime(p + ".miss") < 12 * 3600


def _get(url: str, ttl: int = 6 * 3600) -> str:
    os.makedirs(CACHE, exist_ok=True)
    import hashlib
    p = os.path.join(CACHE, hashlib.sha256(url.encode()).hexdigest()[:20])
    if os.path.exists(p) and time.time() - os.path.getmtime(p) < ttl:
        with open(p) as fh:
            return fh.read()
    # A miss suppresses the request, never the data. A body already on disk is
    # stale, not wrong -- refusing to serve it because one later request timed
    # out threw away the good scene and the bad news together.
    if _negcache(p):
        if os.path.exists(p):
            with open(p) as fh:
                return fh.read()
        raise OffshoreError("recently unavailable (cached miss)")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            body = r.read().decode("utf-8", "replace")
    except Exception as e:                                        # noqa: BLE001
        if os.path.exists(p):
            with open(p) as fh:
                return fh.read()
        open(p + ".miss", "w").close()
        raise OffshoreError(f"{type(e).__name__}: {e}") from e
    cache.write_bytes(p, body if isinstance(body, bytes)
                      else str(body).encode())
    # The URL answered, so whatever it was that failed is over. Leaving the
    # marker meant one transient timeout kept costing a request 12 hours later.
    if os.path.exists(p + ".miss"):
        os.remove(p + ".miss")
    return body


def nm(lat1, lon1, lat2, lon2) -> float:
    return math.hypot((lon2 - lon1) * 45.0 * math.cos(math.radians(lat1)) / 0.75,
                      (lat2 - lat1) * 60.0)


# ------------------------------------------------------------------- sst

def sst_grid(lat: float, lon: float, box: float = 0.25,
             when: date | None = None) -> dict:
    """Sea surface temperature around a point, from MUR at ~1 km.

    MUR lags a day or two, so this walks back until it finds a populated day
    rather than reporting an empty grid as "no data".
    """
    when = when or date.today()
    for back in range(1, 6):
        d = (when - timedelta(days=back)).isoformat()
        q = (f"analysed_sst%5B({d})%5D"
             f"%5B({lat-box}):({lat+box})%5D%5B({lon-box}):({lon+box})%5D")
        try:
            raw = _get(f"{ERDDAP}/jplMURSST41.json?{q}")
        except OffshoreError:
            continue
        rows = json.loads(raw)["table"]["rows"]
        pts = [(r[1], r[2], r[3]) for r in rows if r[3] is not None]
        if len(pts) > 50:
            return {"date": d, "points": pts,
                    "centre_c": _nearest_value(pts, lat, lon)}
    raise OffshoreError("no SST grid available for the last five days")


def _nearest_value(pts, lat, lon):
    best = min(pts, key=lambda p: (p[0] - lat) ** 2 + (p[1] - lon) ** 2)
    return best[2]


def breaks(grid: dict, top: int = 5) -> list[dict]:
    """Where the water changes temperature fastest.

    A temperature break is the whole game offshore -- bait piles on the edge
    and everything else follows it. This is a plain finite-difference gradient
    on the SST grid, reported in degrees per nautical mile.
    """
    pts = grid["points"]
    lats = sorted({p[0] for p in pts})
    lons = sorted({p[1] for p in pts})
    at = {(round(p[0], 4), round(p[1], 4)): p[2] for p in pts}

    out = []
    for i in range(1, len(lats) - 1):
        for j in range(1, len(lons) - 1):
            la, lo = round(lats[i], 4), round(lons[j], 4)
            c = at.get((la, lo))
            n_, s_ = at.get((round(lats[i+1], 4), lo)), at.get((round(lats[i-1], 4), lo))
            e_, w_ = at.get((la, round(lons[j+1], 4))), at.get((la, round(lons[j-1], 4)))
            if None in (c, n_, s_, e_, w_):
                continue
            dy = (n_ - s_) / max(1e-6, nm(lats[i-1], lo, lats[i+1], lo))
            dx = (e_ - w_) / max(1e-6, nm(la, lons[j-1], la, lons[j+1]))
            out.append({"lat": la, "lon": lo, "sst_c": round(c, 2),
                        "grad_c_per_nm": round(math.hypot(dx, dy), 3)})
    out.sort(key=lambda r: -r["grad_c_per_nm"])
    return out[:top]


# ----------------------------------------------------------- chlorophyll

def chlorophyll(lat: float, lon: float, box: float = 0.25) -> dict | None:
    """Water colour. High chlorophyll is green and productive; the clean blue
    edge beside it is usually where you want to be."""
    for ds, var in (("nesdisVHNSQchlaDaily", "chlor_a"),):
        for back in range(1, 5):
            d = (date.today() - timedelta(days=back)).isoformat()
            q = (f"{var}%5B({d})%5D%5B(0.0)%5D"
                 f"%5B({lat-box}):({lat+box})%5D%5B({lon-box}):({lon+box})%5D")
            try:
                raw = _get(f"{ERDDAP}/{ds}.json?{q}")
            except OffshoreError:
                continue
            try:
                rows = json.loads(raw)["table"]["rows"]
            except Exception:                                     # noqa: BLE001
                continue
            vals = [r[-1] for r in rows if r[-1] is not None]
            if len(vals) > 20:
                vals.sort()
                return {"date": d, "dataset": ds, "n": len(vals),
                        "median_mg_m3": round(vals[len(vals)//2], 3),
                        "low": round(vals[int(len(vals)*.1)], 3),
                        "high": round(vals[int(len(vals)*.9)], 3)}
    return None


# ----------------------------------------------------------------- buoy

def buoy(station: str = "44097") -> dict | None:
    try:
        raw = _get(f"{NDBC}/{station}.txt", ttl=1800)
    except OffshoreError:
        return None
    lines = [l for l in raw.splitlines() if l and not l.startswith("#")]
    if not lines:
        return None
    f = lines[0].split()
    def num(i):
        try:
            v = float(f[i]);  return None if v == 99.0 or v == 999.0 else v
        except (ValueError, IndexError):
            return None
    return {"station": station,
            "when": f"{f[0]}-{f[1]}-{f[2]} {f[3]}:{f[4]}Z",
            "wind_dir": num(5), "wind_kt": (num(6) * 1.94384) if num(6) else None,
            "wave_m": num(8), "dom_period_s": num(9), "wave_dir": num(11),
            "water_c": num(14), "air_c": num(13)}


# ----------------------------------------------------- who has been here

def occurrences(lat: float, lon: float, radius_nm: float = 25,
                species: dict | None = None) -> dict:
    """Real dated records near a point, by species and month.

    This is measurement standing in for a prior, the same job the GSO trawl
    does inshore. It says nothing about today -- only what has genuinely been
    caught or observed around here, and when in the year.
    """
    species = species or PELAGICS
    d = radius_nm / 60.0
    poly = (f"POLYGON(({lon-d} {lat-d},{lon+d} {lat-d},"
            f"{lon+d} {lat+d},{lon-d} {lat+d},{lon-d} {lat-d}))")
    out = {}
    for common, sci in species.items():
        q = urllib.parse.urlencode({"scientificname": sci, "geometry": poly,
                                    "size": 0})
        try:
            total = json.loads(_get(f"{OBIS}/occurrence?{q}", ttl=7*86400)).get("total", 0)
        except Exception:                                         # noqa: BLE001
            continue
        if not total:
            continue
        q2 = urllib.parse.urlencode({"scientificname": sci, "geometry": poly,
                                     "size": 400})
        months = Counter()
        try:
            for r in json.loads(_get(f"{OBIS}/occurrence?{q2}", ttl=7*86400)).get("results", []):
                ed = (r.get("eventDate") or "")[:7]
                if len(ed) == 7 and ed[5:7].isdigit():
                    months[int(ed[5:7])] += 1
        except Exception:                                         # noqa: BLE001
            pass
        out[common] = {"scientific": sci, "records": total,
                       "by_month": dict(sorted(months.items()))}
    return out


HFRADAR = "ucsdHfrE2"          # US East Coast, 2 km, near-real-time


def surface_current(lat: float, lon: float, box: float = 0.08) -> dict | None:
    """Measured surface current from the HF radar network.

    This is the one thing the offshore report was missing that the bay report
    has: current that was *observed* rather than extrapolated. Shore-based
    radar reads the surface directly, so unlike a tide-station extrapolation
    seventeen miles out, this is a measurement.

    Coverage is genuinely patchy -- radar has gaps and bad hours -- so a null
    here means "not measured now", never "no current".
    """
    try:
        info = json.loads(_get(f"{ERDDAP.replace('griddap','info')}/{HFRADAR}/index.json",
                               ttl=3600))
    except OffshoreError:
        return None
    latest = None
    for r in info["table"]["rows"]:
        if r[2] == "time_coverage_end":
            latest = r[4]
            break
    if not latest:
        return None

    q = (f"water_u%5B({latest})%5D%5B({lat-box}):({lat+box})%5D"
         f"%5B({lon-box}):({lon+box})%5D,"
         f"water_v%5B({latest})%5D%5B({lat-box}):({lat+box})%5D"
         f"%5B({lon-box}):({lon+box})%5D")
    try:
        rows = json.loads(_get(f"{ERDDAP}/{HFRADAR}.json?{q}", ttl=1800))["table"]["rows"]
    except Exception:                                             # noqa: BLE001
        return None

    cells = [(r[1], r[2], r[3], r[4]) for r in rows
             if r[3] is not None and r[4] is not None]
    if not cells:
        return {"when": latest, "cells": 0, "of": len(rows), "measured": False}

    us = [c[2] for c in cells]
    vs = [c[3] for c in cells]
    mu, mv = sum(us) / len(us), sum(vs) / len(vs)
    speeds = [math.hypot(u, v) * 1.94384 for _, _, u, v in cells]

    # Where neighbouring cells disagree the water is shearing, and a shear line
    # is a convergence -- which is where anything floating ends up.
    spread = max(speeds) - min(speeds)

    return {
        "when": latest, "cells": len(cells), "of": len(rows), "measured": True,
        "mean_kt": round(math.hypot(mu, mv) * 1.94384, 2),
        "toward_deg": round((math.degrees(math.atan2(mu, mv)) + 360) % 360),
        "fastest_kt": round(max(speeds), 2),
        "slowest_kt": round(min(speeds), 2),
        "shear_kt": round(spread, 2),
    }


def nearest_turbine(lat: float, lon: float) -> tuple[str, float]:
    n, la, lo = min(TURBINES, key=lambda t: nm(lat, lon, t[1], t[2]))
    return n, round(nm(lat, lon, la, lo), 1)
