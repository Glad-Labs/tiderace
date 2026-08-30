"""Resolve an arbitrary coordinate to the NOAA stations that describe it.

Every spot in `spots.py` was bound to its stations by hand and verified live.
That does not scale to "give me a report for this mark", so this module does
the binding automatically -- and the hard part is not finding the closest
station, it is refusing the closest station when it is the wrong one.

**Tidal current is constrained by geography; tide height is not.** Those two
sentences justify everything below. Water level propagates around a headland
and varies smoothly over the bay, so the nearest gauge is a fine answer for
height. Current does not: a mark on the Sakonnet and a station off Dyer Island
are a mile and a half apart with the whole of Aquidneck Island in between, and
they run at different speeds, at different times, in different directions.
Straight-line distance cannot tell them apart, and it fails *silently* -- the
forecast still comes out looking perfectly reasonable.

So current stations get a land-crossing test against the charted coastline
(`charts.crosses_land`) and height stations do not. Measured on real
coordinates, the test is not academic:

    Sakonnet shore of Aquidneck   nearest = Dyer Island-Carrs Point, mid-bay
    East side of Prudence Island  nearest = "Dyer Island, WEST of"
    Middle of Conanicut Island    nearest = Rose Island, for a point on land

Nothing here talks to the network per lookup. The catalog is fetched once and
cached, and resolution is pure local geometry -- so asking for a report at a
coordinate does not send that coordinate anywhere.
"""

from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.request

MDAPI = "https://api.tidesandcurrents.noaa.gov/mdapi/prod/webapi/stations.json"
UA = "tiderace (+https://github.com/Glad-Labs/tiderace)"

CATALOG_PATH = os.environ.get(
    "TIDERACE_STATIONS",
    os.path.join(os.path.dirname(__file__), "..", "data", "stations.json"))

# Station lists change on the order of years, not days.
CATALOG_MAX_AGE_DAYS = 90

# Distance bands for the confidence flag, in nautical miles. Past FAR_NM a
# current prediction is describing somewhere else.
NEAR_NM = 1.5
FAR_NM = 3.0

# Past this there is no NOAA station worth calling nearby, which in practice
# means a dropped minus sign on the longitude -- but it might be someone
# genuinely fishing somewhere else, so it is a loud warning and a "poor"
# confidence rather than a refusal. What it must never be is silent: every
# layer downstream still produces a number, and the answer looks exactly like
# a real one. Generous on purpose -- a typo detector, not a service area.
#
# Note this is NOT the same question as "are we outside the chart layers".
# NOAA's catalog is national, so San Francisco has stations 2 nm away and no
# coastline data at all; Tokyo has neither. They need different warnings.
NO_STATIONS_NM = 300.0


class StationError(RuntimeError):
    pass


# ------------------------------------------------------------------- catalog

def _fetch(kind: str) -> list[dict]:
    url = f"{MDAPI}?type={kind}&units=english"
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            payload = json.loads(resp.read().decode())
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise StationError(f"could not fetch {kind} stations: {exc}") from exc

    out, seen = [], set()
    for s in payload.get("stations", []):
        sid = s.get("id")
        # Current stations are published once per depth bin. The prediction
        # API is queried by bare station id, so the bins collapse to one row.
        if not sid or sid in seen:
            continue
        try:
            lat, lon = float(s["lat"]), float(s["lng"])
        except (KeyError, TypeError, ValueError):
            continue
        seen.add(sid)
        out.append({"id": sid, "name": s.get("name") or sid,
                    "lat": lat, "lon": lon})
    return out


def refresh(path: str | None = None) -> dict:
    """Pull the station catalog from NOAA and cache it.

    The whole national list is kept, not just Narragansett Bay: it is five
    fields per station either way, and it means a fork of this project points
    at its own water by changing coordinates rather than code.
    """
    path = path or CATALOG_PATH
    cat = {
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "current": _fetch("currentpredictions"),
        "tide": _fetch("waterlevels"),
    }
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(cat, fh, separators=(",", ":"))
    return cat


_CATALOG: dict | None = None


def catalog(path: str | None = None, auto_refresh: bool = True) -> dict:
    global _CATALOG
    if _CATALOG is not None:
        return _CATALOG
    path = path or CATALOG_PATH
    if os.path.exists(path):
        age_days = (time.time() - os.path.getmtime(path)) / 86400
        try:
            with open(path) as fh:
                cat = json.load(fh)
            if age_days <= CATALOG_MAX_AGE_DAYS or not auto_refresh:
                _CATALOG = cat
                return cat
        except (OSError, json.JSONDecodeError):
            cat = None
        # Stale: try to refresh, but a cached list that is a year old still
        # beats no forecast at all if the network is down.
        try:
            _CATALOG = refresh(path)
        except StationError:
            _CATALOG = cat if cat else {"current": [], "tide": []}
        return _CATALOG

    if not auto_refresh:
        raise StationError(
            f"no station catalog at {path} — run: tiderace stations --refresh")
    _CATALOG = refresh(path)
    return _CATALOG


# ------------------------------------------------------------------ geometry

def distance_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in nautical miles."""
    r = 3440.065
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _ranked(stations: list[dict], lat: float, lon: float,
            limit: int) -> list[dict]:
    scored = [dict(s, distance_nm=round(distance_nm(lat, lon, s["lat"], s["lon"]), 2))
              for s in stations]
    scored.sort(key=lambda s: s["distance_nm"])
    return scored[:limit]


# ------------------------------------------------------------ temperature

_TEMP_CACHE: dict[str, bool] = {}


def reports_temp(station_id: str) -> bool:
    """Does this water-level station actually report water temperature?

    Probed rather than read from metadata: NOAA's own products.json says no
    for Newport, Conimicut and Fall River, and all three return temperatures
    when you ask them. The underlying call is disk-cached by `sources`, so
    this costs one request per station per cache window.
    """
    if station_id in _TEMP_CACHE:
        return _TEMP_CACHE[station_id]
    from . import sources
    try:
        ok = sources.latest_water_temp(station_id) is not None
    except Exception:                                             # noqa: BLE001
        ok = False
    _TEMP_CACHE[station_id] = ok
    return ok


# ----------------------------------------------------------------- resolution

def current_candidates(lat: float, lon: float, limit: int = 8,
                       cat: dict | None = None,
                       origin: tuple[float, float] | None = None) -> list[dict]:
    """Nearby current stations, nearest first, each marked with whether the
    path to it crosses land.

    Candidates are returned rather than filtered away. A station on the far
    side of an island is very rarely the right answer, but "there is nothing
    else within ten miles" is a judgement for the caller to make visibly, not
    for this function to make silently.
    """
    cat = cat or catalog()
    from . import charts
    # Distances are measured from the mark; land is measured from the water
    # beside it, which for a shore spot is not the same point.
    olat, olon = origin or (lat, lon)
    # The land test walks the path sample by sample. From a mark the chart
    # layers do not cover it can only ever answer "don't know", and the walk
    # to a station on another continent is thousands of samples long -- ten
    # seconds of work to reach that non-answer.
    testable = charts.covers(olat, olon)
    out = []
    for s in _ranked(cat.get("current", []), lat, lon, limit):
        s = dict(s)
        span = charts.land_span_nm(olat, olon, s["lat"], s["lon"]) if testable else None
        s["land_span_nm"] = span
        s["crosses_land"] = (None if span is None
                             else span > charts.LAND_TOLERANCE_NM)
        out.append(s)
    return out


def resolve(lat: float, lon: float, cat: dict | None = None) -> dict:
    """Bind a coordinate to its current and tide stations.

    Returns the choice *and* the reasoning: distance, whether the land test
    ran, what it rejected, and a confidence flag. A caller that wants to print
    a number without a caveat has to ignore the caveat on purpose.
    """
    cat = cat or catalog()
    from . import charts

    # Cheapest possible first: a plain distance sort, before any land geometry.
    # The chart layers cover one bay, so for a mark on another coast every
    # land test below is seconds of work that can only return "don't know".
    probe = _ranked(list(cat.get("current", [])) + list(cat.get("tide", [])),
                    lat, lon, 1)
    stranded_far = bool(probe) and probe[0]["distance_nm"] > NO_STATIONS_NM
    off_chart = not charts.covers(lat, lon)

    warnings: list[str] = []
    if stranded_far:
        warnings.append(
            f"nearest NOAA station is {probe[0]['distance_nm']:.0f} nm away — "
            f"there is no tide or current data for this mark. If you meant "
            f"{lat},{-abs(lon)}, the longitude is missing its minus sign")

    # The chart layers are one bay. Outside them every land test can only say
    # "nothing here", which reads as "open water" and is not the same thing --
    # so they are skipped and the gap is named. This is also what keeps a
    # far-away mark cheap: the land geometry is the slow part.
    land_known = bool(charts.land_index()) and not off_chart
    ashore = charts.on_land(lat, lon) if land_known else None

    if off_chart:
        warnings.append(
            "no coastline or depth data for this area, so the current station "
            "was picked on distance alone and could be across land")
    elif not land_known:
        warnings.append(
            "no coastline data cached, so the current station could be across "
            "land — run: tiderace charts")

    # A mark on charted land is the normal case for shore fishing, not an
    # error. Step off the rock and reason from the water beside it.
    water = charts.nearest_water(lat, lon) if ashore else None
    stranded = bool(ashore) and water is None
    origin = (water["lat"], water["lon"]) if water else None
    if water:
        warnings.append(
            f"mark is on charted land; current taken from the water "
            f"{int(water['distance_nm'] * 1852)} m away on bearing "
            f"{water['bearing_deg']}°")
    elif stranded:
        warnings.append(
            "mark is on charted land with no water within half a mile — "
            "check the coordinate")

    cands = current_candidates(lat, lon, limit=8, cat=cat, origin=origin)
    clear = [c for c in cands if c["crosses_land"] is not True]
    rejected = [c for c in cands if c["crosses_land"] is True]

    current = clear[0] if clear else (cands[0] if cands else None)
    if not clear and cands:
        warnings.append(
            f"every nearby current station is across land; falling back to "
            f"{cands[0]['name']}, which probably describes different water")
    elif rejected and current and rejected[0]["distance_nm"] < current["distance_nm"]:
        warnings.append(
            f"skipped {rejected[0]['name']} "
            f"({rejected[0]['distance_nm']} nm, closer) — path crosses land")

    tide_list = _ranked(cat.get("tide", []), lat, lon, 4)
    tide = tide_list[0] if tide_list else None

    # Water temperature rides on the water-level stations, but not all of them
    # carry a thermometer -- Providence and New Bedford report level only. The
    # nearest gauge is the right answer for height and the wrong one for
    # temperature, so they are resolved separately. Losing the temperature
    # would not fail loudly; it would quietly default that whole term to 0.6.
    temp = next((t for t in tide_list if reports_temp(t["id"])), None)
    if temp is None:
        warnings.append("no nearby station reports water temperature")
    elif tide and temp["id"] != tide["id"]:
        warnings.append(
            f"{tide['name']} reports no water temperature; taking it from "
            f"{temp['name']} ({temp['distance_nm']} nm)")

    if current is None:
        warnings.append("no current station found at all")
        confidence = "poor"
    elif off_chart or stranded_far:
        confidence = "poor"
    elif not clear or current["distance_nm"] > FAR_NM or stranded:
        confidence = "poor"
    elif not land_known or current["distance_nm"] > NEAR_NM:
        confidence = "fair"
    else:
        confidence = "good"

    if current and not stranded_far and current["distance_nm"] > FAR_NM:
        warnings.append(
            f"nearest usable current station is {current['distance_nm']} nm away; "
            "the current here is an extrapolation, not a prediction")

    return {
        "lat": lat, "lon": lon,
        "current": current,
        "current_rejected": rejected,
        "current_alternates": [c for c in clear[1:4]],
        "tide": tide,
        "tide_alternates": tide_list[1:],
        "temp": temp,
        "on_land": ashore,
        "off_chart": off_chart,
        "no_stations_near": stranded_far,
        "water_point": water,
        "land_data": land_known,
        "confidence": confidence,
        "warnings": warnings,
    }
