"""Assemble the hourly feature vector for a spot: the join between the
physical data sources and the species models."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import astro, bait, gso, solunar, sources
from .sources import SourceError
from .spots import Spot

_EASTERN = ZoneInfo("America/New_York")

EXPOSED = {"reef", "breachway", "point"}

_COMPASS = {
    "N": 0, "NNE": 22, "NE": 45, "ENE": 67, "E": 90, "ESE": 112, "SE": 135,
    "SSE": 157, "S": 180, "SSW": 202, "SW": 225, "WSW": 247, "W": 270,
    "WNW": 292, "NW": 315, "NNW": 337,
}


def _nearest(series: list[dict], when: datetime, key: str, max_gap_h: float = 3.0):
    if not series:
        return None
    best = min(series, key=lambda r: abs((r["time"] - when).total_seconds()))
    if abs((best["time"] - when).total_seconds()) > max_gap_h * 3600:
        return None
    return best.get(key)


def _pressure_trend(series: list[dict], when: datetime) -> float | None:
    now = _nearest(series, when, "mb")
    past = _nearest(series, when - timedelta(hours=3), "mb")
    if now is None or past is None:
        return None
    return now - past


def _wind_against_tide(wind_dir: str | None, current_compass: int | None,
                       speed: float) -> bool:
    """Wind blowing into the teeth of the current -- the drift killer."""
    if not wind_dir or current_compass is None or speed < 0.3:
        return False
    wind_from = _COMPASS.get(wind_dir.upper())
    if wind_from is None:
        return False
    wind_toward = (wind_from + 180) % 360
    diff = abs((wind_toward - current_compass + 180) % 360 - 180)
    return diff > 135


def build(spot: Spot, start: datetime, hours: int = 48,
          step_minutes: int = 30, species: str | None = None) -> list[dict]:
    """Feature rows at `step_minutes` resolution starting at `start`."""
    end = start + timedelta(hours=hours)
    pad_start = start - timedelta(days=1)
    pad_end = end + timedelta(days=1)

    cur_events = sources.current_events(spot.current_station, pad_start, pad_end)
    tides = sources.tide_extremes(spot.tide_station, pad_start, pad_end)
    temp_series = sources.water_temp(spot.tide_station, start - timedelta(days=2), end)
    wx, press = _weather(spot, start, end)

    # Bait sightings are read once, not per row -- the file is small but the
    # loop is 96 iterations deep.
    sightings = bait.load() if species else []

    # Lunar events are a per-day, per-place calculation, so they are computed
    # once here rather than 96 times in the loop. Recorded on every row even
    # though nothing scores them -- a factor you did not record is a factor you
    # can never test later.
    _lunar: dict = {}

    # Sixty-five years of GSO weekly temperature: the thermal window for this
    # species, and how far ahead or behind normal this year is running.
    thermal = gso.thermal_season(species, _gso_station(spot)) if species else None
    shift = None
    anom = None
    if thermal:
        obs = temp_series[-1]["temp_f"] if temp_series else None
        if obs is not None:
            anom = gso.anomaly(obs, start.date(), _gso_station(spot))
            shift = (anom or {}).get("season_shift_days")

    fallback_temp = temp_series[-1]["temp_f"] if temp_series else None
    if fallback_temp is None:
        fallback_temp = sources.latest_water_temp(spot.tide_station)

    rows = []
    steps = int(hours * 60 / step_minutes)
    for i in range(steps):
        t = start + timedelta(minutes=step_minutes * i)

        elev = astro.solar_elevation(t.replace(tzinfo=_local_tz(t)), spot.lat, spot.lon)
        age, illum = astro.moon_phase(t.replace(tzinfo=_local_tz(t)))
        cur = sources.current_at(cur_events, t)
        wind_dir = _nearest(wx, t, "wind_dir")
        speed = cur["speed"] if cur else 0.0

        b = (bait.bait_at(spot.lat, spot.lon, t, species, sightings)
             if species else {"signal": 0.0, "known": False})

        day = t.date()
        if day not in _lunar:
            _lunar[day] = solunar.events(t.replace(tzinfo=_local_tz(t)),
                                         spot.lat, spot.lon)
        sol = solunar.score(t.replace(tzinfo=_local_tz(t)), spot.lat, spot.lon,
                            _lunar[day])

        rows.append({
            "time": t,
            "week": min(52, t.isocalendar().week),
            "thermal_season": thermal,
            "season_shift_days": shift,
            "season_note": gso.describe_anomaly(anom) if anom else None,
            "solunar": sol["score"],
            "solunar_period": sol["period"],
            "solunar_kind": sol["kind"],
            "bait_signal": b["signal"],
            "bait_known": b.get("known", False),
            "bait_note": bait.describe(b) if b.get("known") else None,
            "month": t.month,
            "spot": spot.key,
            "solar_elev": round(elev, 2),
            "light_phase": astro.light_phase(elev),
            "moon_illum": round(illum, 3),
            "moon_phase": astro.phase_name(age),
            "spring_strength": round(astro.spring_tide_strength(age), 3),
            "current_speed": round(speed, 3),
            "current_dir": cur["direction"] if cur else None,
            "current_stage": cur["stage"] if cur else None,
            "minutes_to_slack": cur["minutes_to_slack"] if cur else None,
            "water_temp_f": _nearest(temp_series, t, "temp_f", 48) or fallback_temp,
            "air_temp_f": _nearest(wx, t, "air_temp_f"),
            "wind_kt": _nearest(wx, t, "wind_kt"),
            "wind_dir": wind_dir,
            "sky_pct": _nearest(wx, t, "sky_pct"),
            "pressure_trend_3h": _pressure_trend(press, t),
            "wind_against_tide": _wind_against_tide(
                wind_dir, cur["compass"] if cur else None, speed),
            "next_tide": _next_tide(tides, t),
            "exposed": spot.kind in EXPOSED,
        })
    return rows


# NWS grids cover land. Spots that sit over open water (Whale Rock, Brenton
# Reef) have no grid cell of their own, so each spot carries a land point and
# we fall back to a regional one rather than dropping the spot entirely --
# wind and pressure are regional at this scale anyway.
REGIONAL_WX = (41.5043, -71.3261)   # Newport


def _weather(spot: Spot, start: datetime | None = None,
             end: datetime | None = None) -> tuple[list[dict], list[dict]]:
    candidates = []
    if spot.wx_point:
        candidates.append(spot.wx_point)
    candidates.append((spot.lat, spot.lon))
    candidates.append(REGIONAL_WX)

    # Anything more than a couple of hours in the past needs observations,
    # not a forecast.
    historic = end is not None and end < datetime.now() - timedelta(hours=2)

    for lat, lon in candidates:
        try:
            if historic:
                obs = sources.nws_observations(
                    lat, lon, start - timedelta(hours=4), end + timedelta(hours=2))
                if obs:
                    press = [{"time": o["time"], "mb": o["mb"]}
                             for o in obs if o.get("mb") is not None]
                    return obs, press
                continue
            return sources.nws_hourly(lat, lon), sources.nws_pressure(lat, lon)
        except SourceError:
            continue
    return [], []


def _gso_station(spot: Spot) -> str:
    """Whale Rock sits at the mouth and runs cooler and more oceanic than the
    mid-bay; Fox Island represents everything up-bay of the passages."""
    return "whale_rock" if spot.lat < 41.50 else "fox_island"


def _next_tide(tides: list[dict], when: datetime) -> str | None:
    upcoming = [x for x in tides if x["time"] >= when]
    if not upcoming:
        return None
    nxt = upcoming[0]
    mins = int((nxt["time"] - when).total_seconds() / 60)
    kind = "high" if nxt["type"] == "H" else "low"
    return f"{kind} in {mins//60}h{mins%60:02d}m"


def _local_tz(t: datetime):
    """CO-OPS lst_ldt values are already local wall clock; attach the real
    Eastern zone so the solar math lines up.

    This used to approximate DST as "March through November is UTC-4", which
    was wrong for all of early March and late November -- an hour of error in
    sun elevation across the entire autumn run, which is exactly the season
    the low-light term matters most.
    """
    return _EASTERN
