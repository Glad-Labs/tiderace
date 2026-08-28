"""Sun and moon geometry. Pure stdlib -- no ephemeris dependency.

Solar position follows the NOAA solar calculator algorithm (accurate to well
under a minute for our latitudes, which is far better than we need for
"is it low light?"). Lunar phase uses a mean-synodic approximation, which is
fine for the two things we care about: illumination fraction and spring/neap
timing.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

_SYNODIC = 29.530588853
# 2000-01-06 18:14 UTC -- a reference new moon.
_NEW_MOON_EPOCH = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)


def _julian_century(dt: datetime) -> float:
    jd = dt.timestamp() / 86400.0 + 2440587.5
    return (jd - 2451545.0) / 36525.0


def solar_elevation(dt: datetime, lat: float, lon: float) -> float:
    """Sun elevation in degrees above the horizon. Negative = below."""
    t = _julian_century(dt.astimezone(timezone.utc))

    mean_lon = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360.0
    mean_anom = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    eccent = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)

    ma = math.radians(mean_anom)
    center = (
        math.sin(ma) * (1.914602 - t * (0.004817 + 0.000014 * t))
        + math.sin(2 * ma) * (0.019993 - 0.000101 * t)
        + math.sin(3 * ma) * 0.000289
    )
    true_lon = mean_lon + center
    omega = 125.04 - 1934.136 * t
    app_lon = true_lon - 0.00569 - 0.00478 * math.sin(math.radians(omega))

    obliq = (
        23.0
        + (26.0 + ((21.448 - t * (46.815 + t * (0.00059 - t * 0.001813)))) / 60.0) / 60.0
    )
    obliq_corr = obliq + 0.00256 * math.cos(math.radians(omega))

    decl = math.degrees(
        math.asin(
            math.sin(math.radians(obliq_corr)) * math.sin(math.radians(app_lon))
        )
    )

    y = math.tan(math.radians(obliq_corr / 2)) ** 2
    eq_time = 4 * math.degrees(
        y * math.sin(2 * math.radians(mean_lon))
        - 2 * eccent * math.sin(ma)
        + 4 * eccent * y * math.sin(ma) * math.cos(2 * math.radians(mean_lon))
        - 0.5 * y * y * math.sin(4 * math.radians(mean_lon))
        - 1.25 * eccent * eccent * math.sin(2 * ma)
    )

    utc = dt.astimezone(timezone.utc)
    minutes = utc.hour * 60 + utc.minute + utc.second / 60.0
    true_solar = (minutes + eq_time + 4 * lon) % 1440.0
    hour_angle = true_solar / 4.0 - 180.0 if true_solar / 4.0 >= 0 else true_solar / 4.0 + 180.0

    la, de, ha = map(math.radians, (lat, decl, hour_angle))
    zenith = math.acos(
        math.sin(la) * math.sin(de) + math.cos(la) * math.cos(de) * math.cos(ha)
    )
    return 90.0 - math.degrees(zenith)


def moon_phase(dt: datetime) -> tuple[float, float]:
    """Return (age_in_days, illuminated_fraction 0..1)."""
    days = (dt.astimezone(timezone.utc) - _NEW_MOON_EPOCH).total_seconds() / 86400.0
    age = days % _SYNODIC
    illum = (1 - math.cos(2 * math.pi * age / _SYNODIC)) / 2
    return age, illum


def phase_name(age: float) -> str:
    idx = int(((age / _SYNODIC) * 8 + 0.5) % 8)
    return [
        "New", "Waxing Crescent", "First Quarter", "Waxing Gibbous",
        "Full", "Waning Gibbous", "Last Quarter", "Waning Crescent",
    ][idx]


def spring_tide_strength(age: float) -> float:
    """0 = neap, 1 = spring. Peaks at new and full moon."""
    return abs(math.cos(2 * math.pi * age / _SYNODIC))


def light_phase(elev: float) -> str:
    if elev >= 6:
        return "day"
    if elev >= -0.833:
        return "golden"
    if elev >= -12:
        return "twilight"
    return "night"


def sun_events(day: datetime, lat: float, lon: float) -> dict[str, datetime | None]:
    """Coarse sunrise/sunset by scanning elevation at 2-minute steps."""
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    events: dict[str, datetime | None] = {"sunrise": None, "sunset": None}
    prev = solar_elevation(start, lat, lon)
    for i in range(1, 721):
        cur_t = start + timedelta(minutes=2 * i)
        cur = solar_elevation(cur_t, lat, lon)
        if prev < -0.833 <= cur and events["sunrise"] is None:
            events["sunrise"] = cur_t
        if prev >= -0.833 > cur and events["sunset"] is None:
            events["sunset"] = cur_t
        prev = cur
    return events
