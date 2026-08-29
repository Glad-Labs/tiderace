"""Solunar theory, computed properly so it can be tested rather than believed.

A large part of this industry runs on solunar theory: fish feed hardest when
the moon is overhead or underfoot (the *major* periods) and, less strongly, at
moonrise and moonset (*minor*). Fishing Reminder is built on it outright, and
FishNotify's Jamestown window on 28 August 2026 -- 06:34 to 10:34, on a full
moon whose moonset lands at the 06:08 sunrise -- is a solunar window with the
tide playing no part.

This module exists so that claim can be **measured against** the physics model
rather than argued about, which is why nothing here feeds the score. It is a
rival hypothesis, and folding a rival into the thing it competes with destroys
the only interesting question: does the moon beat the current?

There is a second reason to keep it out. Solunar periods are driven by lunar
position, and so are spring tides and therefore current speed. Adding a
solunar term on top of `current_speed` and `spring_strength` would count the
moon three times over and call the result a better model.

Lunar position is the abbreviated Meeus series -- good to roughly ten arc
minutes, which is far better than transit timing needs.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

D2R = math.pi / 180.0
R2D = 180.0 / math.pi


def _jc(dt: datetime) -> float:
    """Julian centuries since J2000.0."""
    jd = dt.astimezone(timezone.utc).timestamp() / 86400.0 + 2440587.5
    return (jd - 2451545.0) / 36525.0


def moon_equatorial(dt: datetime) -> tuple[float, float]:
    """Geocentric right ascension and declination in degrees."""
    t = _jc(dt)

    Lp = 218.3164477 + 481267.88123421 * t          # mean longitude
    D = 297.8501921 + 445267.1114034 * t            # mean elongation
    M = 357.5291092 + 35999.0502909 * t             # sun mean anomaly
    Mp = 134.9633964 + 477198.8675055 * t           # moon mean anomaly
    F = 93.2720950 + 483202.0175233 * t             # argument of latitude

    d, m, mp, f = (x * D2R for x in (D, M, Mp, F))

    lon = (Lp
           + 6.289 * math.sin(mp)
           + 1.274 * math.sin(2 * d - mp)
           + 0.658 * math.sin(2 * d)
           + 0.214 * math.sin(2 * mp)
           - 0.186 * math.sin(m)
           - 0.114 * math.sin(2 * f))
    lat = (5.128 * math.sin(f)
           + 0.280 * math.sin(mp + f)
           - 0.278 * math.sin(f - mp)
           + 0.176 * math.sin(2 * d - f))

    eps = 23.439291 - 0.0130042 * t
    lam, bet, e = lon * D2R, lat * D2R, eps * D2R

    ra = math.atan2(math.sin(lam) * math.cos(e) - math.tan(bet) * math.sin(e),
                    math.cos(lam))
    dec = math.asin(math.sin(bet) * math.cos(e)
                    + math.cos(bet) * math.sin(e) * math.sin(lam))
    return (ra * R2D) % 360.0, dec * R2D


def _gmst(dt: datetime) -> float:
    """Greenwich mean sidereal time in degrees."""
    jd = dt.astimezone(timezone.utc).timestamp() / 86400.0 + 2440587.5
    t = (jd - 2451545.0) / 36525.0
    return (280.46061837 + 360.98564736629 * (jd - 2451545.0)
            + 0.000387933 * t * t) % 360.0


def moon_altitude(dt: datetime, lat: float, lon: float) -> float:
    """Altitude above the horizon in degrees."""
    ra, dec = moon_equatorial(dt)
    h = ((_gmst(dt) + lon - ra) % 360.0) * D2R
    p, d = lat * D2R, dec * D2R
    return math.asin(math.sin(p) * math.sin(d)
                     + math.cos(p) * math.cos(d) * math.cos(h)) * R2D


def moon_hour_angle(dt: datetime, lon: float) -> float:
    """Hour angle in degrees, wrapped to -180..180. Zero at transit."""
    ra, _ = moon_equatorial(dt)
    return ((_gmst(dt) + lon - ra + 180.0) % 360.0) - 180.0


# The moon's apparent radius plus refraction minus parallax; the conventional
# rise/set altitude is a shade above the horizon rather than at it.
RISESET_ALT = 0.125


def events(day: datetime, lat: float, lon: float,
           step_minutes: int = 4) -> dict[str, datetime | None]:
    """Moonrise, moonset, transit (overhead) and antitransit (underfoot).

    Scanned rather than solved. At four-minute steps this lands within a
    couple of minutes, which is well inside the hour-wide periods the theory
    actually describes.
    """
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    n = int(24 * 60 / step_minutes) + 1
    times = [start + timedelta(minutes=step_minutes * i) for i in range(n)]
    alts = [moon_altitude(t, lat, lon) for t in times]
    has = [moon_hour_angle(t, lon) for t in times]

    out: dict[str, datetime | None] = {
        "moonrise": None, "moonset": None, "transit": None, "antitransit": None}

    for i in range(1, n):
        if alts[i - 1] < RISESET_ALT <= alts[i] and out["moonrise"] is None:
            out["moonrise"] = _interp(times[i - 1], times[i],
                                      alts[i - 1], alts[i], RISESET_ALT)
        if alts[i - 1] >= RISESET_ALT > alts[i] and out["moonset"] is None:
            out["moonset"] = _interp(times[i - 1], times[i],
                                     alts[i - 1], alts[i], RISESET_ALT)
        # Hour angle crosses zero at transit and wraps at antitransit.
        if has[i - 1] < 0 <= has[i] and out["transit"] is None:
            out["transit"] = _interp(times[i - 1], times[i],
                                     has[i - 1], has[i], 0.0)
        if has[i - 1] > 0 >= has[i] - 360 and has[i] < has[i - 1] - 180 \
                and out["antitransit"] is None:
            out["antitransit"] = times[i - 1] + timedelta(minutes=step_minutes / 2)

    if out["antitransit"] is None and out["transit"] is not None:
        # Underfoot is half a lunar day from overhead.
        for delta in (timedelta(hours=12, minutes=25), timedelta(hours=-12, minutes=-25)):
            cand = out["transit"] + delta
            if start <= cand < start + timedelta(days=1):
                out["antitransit"] = cand
                break
    return out


def _interp(t0, t1, v0, v1, target):
    if v1 == v0:
        return t0
    f = (target - v0) / (v1 - v0)
    return t0 + (t1 - t0) * f


MAJOR_HALF_H = 1.0        # overhead / underfoot, +/- an hour
MINOR_HALF_H = 0.5        # moonrise / moonset, +/- half an hour


def score(when: datetime, lat: float, lon: float,
          day_events: dict | None = None) -> dict:
    """Solunar rating 0..1 for a moment, plus which period it falls in.

    Weighted the way the theory states it: majors stronger than minors, and a
    period counts for more when the moon is full or new, when sun and moon
    pull together.
    """
    ev = day_events or events(when, lat, lon)
    from .astro import moon_phase, spring_tide_strength
    age, illum = moon_phase(when)
    pull = 0.75 + 0.25 * spring_tide_strength(age)   # syzygy bonus

    best, label = 0.0, None
    for key, weight, half in (("transit", 1.0, MAJOR_HALF_H),
                              ("antitransit", 0.92, MAJOR_HALF_H),
                              ("moonrise", 0.6, MINOR_HALF_H),
                              ("moonset", 0.6, MINOR_HALF_H)):
        t = ev.get(key)
        if t is None:
            continue
        hours = abs((when - t).total_seconds()) / 3600.0
        if hours > half:
            continue
        # Triangular falloff across the window: strongest at the centre.
        v = weight * (1.0 - hours / half)
        if v > best:
            best, label = v, key

    return {
        "score": round(min(1.0, best * pull), 3),
        "period": label,
        "kind": None if label is None else
                ("major" if label in ("transit", "antitransit") else "minor"),
        "illumination": round(illum, 3),
    }
