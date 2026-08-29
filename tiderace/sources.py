"""Live data sources. All free, all keyless, all public.

  NOAA CO-OPS  -- tide predictions, tidal current predictions, water temp
  NWS api.weather.gov -- gridded hourly wind / air temp / pressure / sky

Responses are cached on disk so that re-running a forecast or backtesting a
season does not hammer public infrastructure.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

# Weather lookups are the only place a *spot coordinate* leaves this machine.
# NWS grid cells are ~2.5 km, so querying at 4 decimal places (~11 m) discloses
# far more precision than the answer contains. Two decimals is ~1.1 km: no loss
# of forecast accuracy, and your marks do not end up in someone's access log.
WX_PRECISION = 2

CO_OPS = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"
NWS = "https://api.weather.gov"
UA = "tiderace (github.com/gladlabs; mattg@gladlabs.io)"

CACHE_DIR = os.environ.get(
    "TIDERACE_CACHE", os.path.join(os.path.dirname(__file__), "..", ".cache")
)
CACHE_TTL = int(os.environ.get("TIDERACE_CACHE_TTL", "1800"))  # 30 min


class SourceError(RuntimeError):
    pass


def _cache_path(url: str) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, hashlib.sha256(url.encode()).hexdigest()[:20] + ".json")


def _fetch(url: str, ttl: int = CACHE_TTL) -> dict:
    path = _cache_path(url)
    if ttl and os.path.exists(path) and time.time() - os.path.getmtime(path) < ttl:
        with open(path) as fh:
            return json.load(fh)

    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        raise SourceError(f"{exc.code} from {url}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        # Serve a stale cache rather than fail the whole forecast offline.
        if os.path.exists(path):
            with open(path) as fh:
                return json.load(fh)
        raise SourceError(f"network error for {url}: {exc}") from exc

    if isinstance(payload, dict) and "error" in payload:
        raise SourceError(payload["error"].get("message", "unknown CO-OPS error").strip())

    with open(path, "w") as fh:
        json.dump(payload, fh)
    return payload


def _coops(**params) -> dict:
    params.setdefault("units", "english")
    params.setdefault("time_zone", "lst_ldt")
    params.setdefault("format", "json")
    return _fetch(CO_OPS + "?" + urllib.parse.urlencode(params))


def _coarse(lat: float, lon: float) -> tuple[float, float]:
    """Round a coordinate to the resolution the weather actually has."""
    return round(lat, WX_PRECISION), round(lon, WX_PRECISION)


def _dt(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d %H:%M")


# --------------------------------------------------------------------------- tides

def tide_extremes(station: str, begin: datetime, end: datetime) -> list[dict]:
    """High and low water events (naive local times)."""
    data = _coops(
        product="predictions", station=station, datum="MLLW", interval="hilo",
        begin_date=begin.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"),
    )
    return [
        {"time": _dt(p["t"]), "height": float(p["v"]), "type": p["type"]}
        for p in data.get("predictions", [])
    ]


def tide_curve(station: str, begin: datetime, end: datetime) -> list[dict]:
    """Six-minute tide height curve."""
    data = _coops(
        product="predictions", station=station, datum="MLLW",
        begin_date=begin.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"),
    )
    return [{"time": _dt(p["t"]), "height": float(p["v"])} for p in data.get("predictions", [])]


# ------------------------------------------------------------------------ currents

def current_events(station: str, begin: datetime, end: datetime) -> list[dict]:
    """Slack / max-flood / max-ebb events. Velocity is signed: + flood, - ebb."""
    data = _coops(
        product="currents_predictions", station=station, interval="MAX_SLACK",
        begin_date=begin.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"),
    )
    cp = data.get("current_predictions", {}).get("cp", [])
    return [
        {
            "time": _dt(e["Time"]),
            "velocity": float(e["Velocity_Major"]),
            "type": e["Type"],
            "flood_dir": e.get("meanFloodDir"),
            "ebb_dir": e.get("meanEbbDir"),
        }
        for e in cp
    ]


def current_at(events: list[dict], when: datetime) -> dict | None:
    """Interpolate current velocity between slack and max.

    Tidal current between a slack and the following max is very close to a
    quarter sine wave, so we fit one rather than interpolating linearly --
    linear interpolation badly overstates how much water is moving right
    after slack, which is exactly the window anglers care about.
    """
    if len(events) < 2:
        return None
    prev = nxt = None
    for a, b in zip(events, events[1:]):
        if a["time"] <= when <= b["time"]:
            prev, nxt = a, b
            break
    if prev is None:
        return None

    span = (nxt["time"] - prev["time"]).total_seconds()
    if span <= 0:
        return None
    frac = (when - prev["time"]).total_seconds() / span

    # Sine easing from prev velocity to next velocity.
    v = prev["velocity"] + (nxt["velocity"] - prev["velocity"]) * (
        (1 - math.cos(math.pi * frac)) / 2
    )
    to_slack = (nxt["time"] - when).total_seconds() / 60.0 if nxt["type"] == "slack" else None
    from_slack = (when - prev["time"]).total_seconds() / 60.0 if prev["type"] == "slack" else None

    if abs(nxt["velocity"]) > abs(prev["velocity"]):
        stage, peak = "building", nxt
    else:
        stage, peak = "easing", prev

    return {
        "velocity": v,
        "speed": abs(v),
        "direction": "flood" if v > 0.02 else ("ebb" if v < -0.02 else "slack"),
        "stage": stage,
        "minutes_to_slack": to_slack,
        "minutes_from_slack": from_slack,
        "peak_speed": abs(peak["velocity"]),
        "compass": (peak.get("flood_dir") if v > 0 else peak.get("ebb_dir")),
    }


# ---------------------------------------------------------------------- water temp

def water_temp(station: str, begin: datetime | None = None,
               end: datetime | None = None) -> list[dict]:
    """Observed water temperature. Falls back to empty list if the station
    is not reporting (they do go offline)."""
    params = dict(product="water_temperature", station=station)
    if begin and end:
        params.update(begin_date=begin.strftime("%Y%m%d"), end_date=end.strftime("%Y%m%d"))
    else:
        params.update(date="latest")
    try:
        data = _coops(**params)
    except SourceError:
        return []
    out = []
    for p in data.get("data", []):
        try:
            out.append({"time": _dt(p["t"]), "temp_f": float(p["v"])})
        except (ValueError, KeyError):
            continue
    return out


def latest_water_temp(station: str) -> float | None:
    rows = water_temp(station)
    return rows[-1]["temp_f"] if rows else None


# -------------------------------------------------------------------------- weather

def nws_hourly(lat: float, lon: float) -> list[dict]:
    """Hourly forecast: wind, air temp, sky cover, pressure trend proxy."""
    lat, lon = _coarse(lat, lon)
    pt = _fetch(f"{NWS}/points/{lat:.4f},{lon:.4f}", ttl=86400)
    url = pt["properties"]["forecastHourly"]
    data = _fetch(url, ttl=3600)

    out = []
    for p in data.get("properties", {}).get("periods", []):
        start = datetime.fromisoformat(p["startTime"])
        speed = p.get("windSpeed") or ""
        try:
            kt = round(float(speed.split()[0]) * 0.868976, 1)  # mph -> kt
        except (ValueError, IndexError):
            kt = None
        out.append({
            "time": start.replace(tzinfo=None),
            "air_temp_f": p.get("temperature"),
            "wind_kt": kt,
            "wind_dir": p.get("windDirection"),
            "sky_pct": (p.get("skyCover") or {}).get("value")
                        if isinstance(p.get("skyCover"), dict) else None,
            "pop": (p.get("probabilityOfPrecipitation") or {}).get("value"),
            "short": p.get("shortForecast"),
        })
    return out


def nws_pressure(lat: float, lon: float) -> list[dict]:
    """Barometric pressure series from the raw gridpoint (Pa -> mb)."""
    lat, lon = _coarse(lat, lon)
    pt = _fetch(f"{NWS}/points/{lat:.4f},{lon:.4f}", ttl=86400)
    props = pt["properties"]
    grid = _fetch(f"{NWS}/gridpoints/{props['gridId']}/{props['gridX']},{props['gridY']}",
                  ttl=3600)
    series = grid.get("properties", {}).get("pressure", {}).get("values", [])
    out = []
    for v in series:
        stamp = v["validTime"].split("/")[0]
        val = v.get("value")
        if val is None:
            continue
        out.append({
            "time": datetime.fromisoformat(stamp).replace(tzinfo=None),
            "mb": val / 100.0,
        })
    return out


def nws_observations(lat: float, lon: float, begin: datetime,
                     end: datetime) -> list[dict]:
    """Observed weather from the nearest reporting station.

    The forecast endpoint only looks forward, so backfilling a trip from last
    week would otherwise land in the log with every weather field null -- and
    a training example missing half its features is close to worthless.
    """
    lat, lon = _coarse(lat, lon)
    pt = _fetch(f"{NWS}/points/{lat:.4f},{lon:.4f}", ttl=86400)
    try:
        stations = _fetch(pt["properties"]["observationStations"], ttl=86400)
        ids = [s.rsplit("/", 1)[-1] for s in stations.get("observationStations", [])[:3]]
    except (SourceError, KeyError):
        return []

    for sid in ids:
        q = urllib.parse.urlencode({
            "start": begin.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        try:
            data = _fetch(f"{NWS}/stations/{sid}/observations?{q}", ttl=86400)
        except SourceError:
            continue

        out = []
        for f in data.get("features", []):
            p = f.get("properties", {})
            stamp = p.get("timestamp")
            if not stamp:
                continue
            temp_c = (p.get("temperature") or {}).get("value")
            wind_kmh = (p.get("windSpeed") or {}).get("value")
            wind_deg = (p.get("windDirection") or {}).get("value")
            pres_pa = (p.get("barometricPressure") or {}).get("value")
            out.append({
                "time": datetime.fromisoformat(stamp).replace(tzinfo=None),
                "air_temp_f": temp_c * 9 / 5 + 32 if temp_c is not None else None,
                # NWS reports wind in km/h under this key despite the name.
                "wind_kt": round(wind_kmh * 0.539957, 1) if wind_kmh is not None else None,
                "wind_dir": _deg_to_compass(wind_deg),
                "sky_pct": None,
                "mb": pres_pa / 100.0 if pres_pa is not None else None,
            })
        if out:
            return sorted(out, key=lambda r: r["time"])
    return []


def _deg_to_compass(deg: float | None) -> str | None:
    if deg is None:
        return None
    names = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
             "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return names[int((deg / 22.5) + 0.5) % 16]
