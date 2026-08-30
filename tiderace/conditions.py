"""Environmental facts nothing else in the project surfaces.

None of this is scored. Each is a measurement that changes what you would do
and that a tide table cannot tell you.

  water level anomaly   observed minus predicted at a CO-OPS station. A hard
                        blow stacks water into the bay or drags it out, and
                        the difference between the curve and the gauge is the
                        part nobody looks at.
  river discharge       USGS gauges. Freshwater after rain drops salinity in
                        the upper bay and moves bait; a spike is visible here
                        days before it is visible anywhere else.
  marine forecast       the NWS coastal waters zone — small craft advisories,
                        wind and seas as a forecast rather than one buoy's
                        instantaneous reading. The go / no-go.
"""

from __future__ import annotations

import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from .sources import _coops, _dt, _fetch

USGS = "https://waterservices.usgs.gov/nwis/iv/"
NWS = "https://api.weather.gov"

# Coastal waters zones covering the bay and the water outside it.
ZONES = {
    "ANZ236": "Narragansett Bay",
    "ANZ237": "RI Sound and Block Island Sound",
    "ANZ230": "Coastal waters from Watch Hill to Montauk",
    "ANZ250": "Coastal waters out to 25 nm",
}

# Rivers that actually reach the bay, largest first.
RIVERS = {
    "01113895": "Blackstone R. at Millville",
    "01114000": "Moshassuck R. at Providence",
    "01114500": "Woonasquatucket R. at Centerdale",
    "01109403": "Ten Mile R. at East Providence",
    "01117500": "Pawcatuck R. at Wood River Jct",
    "01111500": "Branch R. at Forestdale",
}


def water_level_anomaly(station: str = "8452660",
                        hours: int = 6) -> dict | None:
    """Observed water level against the harmonic prediction.

    A positive anomaly means more water than the tide table says -- wind has
    piled it in. Negative means it has been blown out. Either shifts every
    depth and every current in the bay away from the printed curve.
    """
    end = datetime.now()
    begin = end - timedelta(hours=hours)
    fmt = lambda d: d.strftime("%Y%m%d %H:%M")
    try:
        obs = _coops(product="water_level", station=station, datum="MLLW",
                     begin_date=fmt(begin), end_date=fmt(end))
        pred = _coops(product="predictions", station=station, datum="MLLW",
                      begin_date=fmt(begin), end_date=fmt(end))
    except Exception:                                             # noqa: BLE001
        return None

    o = {r["t"]: float(r["v"]) for r in obs.get("data", []) if r.get("v")}
    p = {r["t"]: float(r["v"]) for r in pred.get("predictions", []) if r.get("v")}
    shared = sorted(set(o) & set(p))
    if not shared:
        return None

    latest = shared[-1]
    diffs = [o[t] - p[t] for t in shared]
    return {
        "station": station, "when": latest,
        "observed_ft": round(o[latest], 2),
        "predicted_ft": round(p[latest], 2),
        "anomaly_ft": round(o[latest] - p[latest], 2),
        "mean_anomaly_ft": round(sum(diffs) / len(diffs), 2),
        "samples": len(shared),
    }


def rivers(sites: dict | None = None) -> list[dict]:
    """Instantaneous discharge, in cubic feet per second."""
    sites = sites or RIVERS
    q = urllib.parse.urlencode({
        "format": "json", "sites": ",".join(sites),
        "parameterCd": "00060", "siteStatus": "all"})
    try:
        data = _fetch(f"{USGS}?{q}", ttl=1800)
    except Exception:                                             # noqa: BLE001
        return []

    out = []
    for ts in data.get("value", {}).get("timeSeries", []):
        info = ts["sourceInfo"]
        vals = ts["values"][0]["value"]
        if not vals:
            continue
        try:
            cfs = float(vals[0]["value"])
        except (ValueError, KeyError):
            continue
        if cfs < 0:                       # USGS uses -999999 for missing
            continue
        code = info["siteCode"][0]["value"]
        out.append({"site": code, "name": sites.get(code, info["siteName"]),
                    "cfs": cfs, "when": vals[0].get("dateTime", "")[:16]})
    return sorted(out, key=lambda r: -r["cfs"])


def marine_forecast(zone: str = "ANZ236", office: str = "BOX") -> dict | None:
    """The NWS coastal waters forecast for one marine zone.

    Marine forecasts are not served by /zones/{id}/forecast the way land ones
    are -- that returns 404. They arrive as a single text product covering
    every zone the office issues for, so this pulls the latest Coastal Waters
    Forecast and cuts out the section for the zone asked about.
    """
    try:
        index = _fetch(f"{NWS}/products/types/CWF/locations/{office}", ttl=1800)
        items = index.get("@graph", [])
        if not items:
            return None
        product = _fetch(f"{NWS}/products/{items[0]['id']}", ttl=1800)
    except Exception:                                             # noqa: BLE001
        return None

    text = product.get("productText", "")
    start = text.find(zone)
    if start < 0:
        return None
    # A zone's section runs until the next zone header or the end.
    rest = text[start:]
    end = len(rest)
    for other in ZONES:
        if other == zone:
            continue
        i = rest.find(other)
        if 0 < i < end:
            end = i
    block = rest[:end].strip()

    periods = []
    for line in block.splitlines():
        line = line.strip()
        if line.startswith("."):
            head, _, body = line.partition("...")
            periods.append({"name": head.lstrip("."), "text": body.strip()})
        elif periods and line and not line.endswith("-"):
            periods[-1]["text"] = (periods[-1]["text"] + " " + line).strip()

    return {"zone": zone, "name": ZONES.get(zone, zone),
            "issued": product.get("issuanceTime", "")[:16],
            "periods": periods[:4], "raw": block}


def alerts(zone: str = "ANZ236") -> list[dict]:
    """Active advisories and warnings — small craft, gale, storm."""
    try:
        data = _fetch(f"{NWS}/alerts/active?zone={zone}", ttl=900)
    except Exception:                                             # noqa: BLE001
        return []
    out = []
    for f in data.get("features", []):
        p = f.get("properties", {})
        out.append({"event": p.get("event"), "severity": p.get("severity"),
                    "headline": (p.get("headline") or "")[:120],
                    "ends": (p.get("ends") or "")[:16]})
    return out
