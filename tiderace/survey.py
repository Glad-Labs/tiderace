"""Everything tiderace knows about one place at one time.

The forecast answers "when should I go". This answers a different and more
basic question -- "what is actually happening here right now" -- and it is the
one that gets used most, because a score is an opinion and a water temperature
is a fact.

Two ideas hold this module together.

**Every value carries its own footprint.** A charted sounding is a real
measurement at a real point; satellite SST is a kilometre average; HF radar
surface current is a ~6 km cell; the NWS grid is 2.5 km; a tidal current
prediction is a harmonic fit at a station some distance away, extrapolated.
Printed in a column those look equally precise and they are not, off by four
orders of magnitude. So nothing here returns a bare number: every datum is
`{value, source, resolution_m, ...}` and the renderer shows the footprint next
to the figure. "Down to the metre" is possible for depth and impossible for
sea surface temperature, and the honest thing is to say which is which rather
than let the layout imply otherwise.

**Zone decides what is worth asking.** River discharge matters in the upper
bay and is noise at the wind farm; HF radar and thermal breaks are the whole
story offshore and do not exist inside the bay. Asking every source everywhere
would be slow, and worse, it would return confident nulls -- "no thermal break
here" is not a fact about Wickford, it is a fact about the satellite product's
coverage. So each layer declares the zones it means anything in.

Nothing in here is scored, ranked or blended. It reports.
"""

from __future__ import annotations

from datetime import datetime

# Metres. Rough, honest, and documented at the point of use rather than
# invented per call.
RES = {
    "sounding": 1,          # a charted depth is a real point measurement
    "chart_feature": 5,     # wrecks, rocks, obstructions: surveyed positions
    "station": 100,         # a CO-OPS gauge reads its own piece of water
    "buoy": 100,            # NDBC hull position
    "sighting": 500,        # a citizen-science position, often eyeballed
    "nws_grid": 2500,       # NWS gridpoint forecast cell
    "sst": 1000,            # MUR SST is ~1 km
    "hf_radar": 6000,       # surface current cell
    "chlorophyll": 4000,
}

# Which zone each layer means anything in.
INSHORE, MIDBAY, OFFSHORE = "inshore", "midbay", "offshore"
ALL = (INSHORE, MIDBAY, OFFSHORE)


def zone(lat: float, lon: float, depth_ft: float | None = None) -> str:
    """Rough banding, used only to decide which sources to ask.

    Deliberately crude and driven by position rather than a coastline walk:
    this picks which questions to ask, and asking one extra is cheaper than a
    geometry pass. The bay proper sits north of about 41.35 N; south of that
    is open sound out to the shelf.
    """
    if lat >= 41.45:
        return INSHORE
    if lat >= 41.30:
        return MIDBAY
    if depth_ft is not None and depth_ft < 60:
        return MIDBAY
    return OFFSHORE


def _d(value, source: str, resolution_m: int | None,
       note: str = "", when: str | None = None) -> dict:
    return {"value": value, "source": source, "resolution_m": resolution_m,
            "note": note, "when": when}


def _try(fn, *a, **kw):
    """Every layer fails on its own. A dead satellite product must not take
    the tide table down with it, and a missing layer is reported as missing
    rather than as zero."""
    try:
        return fn(*a, **kw), None
    except Exception as e:                                        # noqa: BLE001
        return None, f"{type(e).__name__}: {str(e)[:90]}"


def survey(lat: float, lon: float, when: datetime | None = None,
           species: str = "striped_bass", include_slow: bool = True) -> dict:
    """Assemble every layer that means something at this place.

    `include_slow` drops the satellite and OBIS layers, which are the ones that
    cost seconds. The map wants them; a quick check on the water does not.
    """
    from . import charts, conditions, point as pointmod, protected, stations
    when = when or datetime.now()

    out: dict = {"lat": lat, "lon": lon, "when": when.isoformat(),
                 "layers": {}, "unavailable": {}}
    L, U = out["layers"], out["unavailable"]

    # ---------------------------------------------------------- the place
    depth = charts.depth_at(lat, lon)
    charted = charts.covers(lat, lon)
    z = zone(lat, lon, depth)
    out["zone"] = z
    out["charted"] = charted

    L["depth"] = _d(depth, "NOAA ENC soundings", RES["sounding"],
                    "charted sounding, not a live echo sounder"
                    if depth is not None else
                    ("no chart data for this area" if not charted else
                     "no sounding at this point"))
    L["bottom"] = _d(charts.bottom_at(lat, lon), "NOAA ENC", RES["chart_feature"])
    L["structure"] = _d(pointmod.structure_near(lat, lon), "NOAA ENC",
                        RES["chart_feature"],
                        "wrecks, rocks and obstructions within 0.25 nm")

    # ------------------------------------------------------- the stations
    res, err = _try(stations.resolve, lat, lon)
    if res:
        cur, tide = res.get("current"), res.get("tide")
        L["current_station"] = _d(cur, "NOAA CO-OPS", RES["station"],
                                  f"{cur['distance_nm']:.1f} nm away — the "
                                  "current here is extrapolated from it"
                                  if cur else "none found")
        L["tide_station"] = _d(tide, "NOAA CO-OPS", RES["station"],
                               f"{tide['distance_nm']:.1f} nm away" if tide else "")
        out["binding_confidence"] = res.get("confidence")
        out["binding_warnings"] = res.get("warnings", [])
    else:
        U["stations"] = err

    # --------------------------------------------- the hour being asked for
    # features.build does the join between stations and time; taking one row
    # from it is how this stays consistent with what the forecast would say.
    rows, err = _try(_row_at, lat, lon, when, species)
    if rows:
        # The current is the weakest number in here despite looking the most
        # precise: it is a harmonic prediction for a station some distance
        # away, not a measurement at this point.
        L["conditions"] = _d(rows, "NOAA harmonic prediction + NWS grid",
                             RES["station"],
                             "state at the hour asked for, via the same path "
                             "the forecast uses")
    else:
        U["conditions"] = err

    # ------------------------------------------------------------ weather
    obs, err = _try(_observations, lat, lon)
    if obs:
        L["weather"] = _d(obs, "NWS nearest station", RES["nws_grid"],
                          "last actual observation, not the gridded forecast")
    else:
        U["weather"] = err

    # -------------------------------------------------------- water level
    if res and res.get("tide"):
        anom, err = _try(conditions.water_level_anomaly, res["tide"]["id"])
        if anom:
            L["water_level_anomaly"] = _d(
                anom, "CO-OPS observed minus predicted", RES["station"],
                "wind and pressure pushing water in or out — a hard on-shore "
                "blow can hold a foot of water in the bay")
        else:
            U["water_level_anomaly"] = err

    # ---------------------------------------------------- rivers (inshore)
    if z == INSHORE:
        riv, err = _try(conditions.rivers)
        if riv:
            L["rivers"] = _d(riv, "USGS discharge", RES["station"],
                             "freshwater pushing into the upper bay")
        else:
            U["rivers"] = err

    # ------------------------------------------------------- marine forecast
    mf, err = _try(conditions.marine_forecast)
    if mf:
        L["marine_forecast"] = _d(mf, "NWS coastal waters forecast", None,
                                  "zone-wide text, not a point value")
    else:
        U["marine_forecast"] = err

    alerts, err = _try(conditions.alerts)
    if alerts is not None:
        L["alerts"] = _d(alerts, "NWS active alerts", None)

    # --------------------------------------------------- offshore-only layers
    if z == OFFSHORE:
        _offshore_layers(lat, lon, L, U, include_slow)

    # ------------------------------------------------------------ sightings
    _sighting_layers(lat, lon, L, U)

    # ------------------------------------------------------------- the rules
    L["protected"] = _d(protected.advisory(lat, lon, when.date()),
                        "50 CFR 224.103(c) / 224.105", None,
                        "law, not a forecast")

    return out


def _row_at(lat: float, lon: float, when: datetime, species: str) -> dict:
    """The physical state at the requested hour, via the same path the
    forecast uses so the two can never disagree."""
    from . import features, spots, stations
    res = stations.resolve(lat, lon)
    spot, _ = spots.at_coord(lat, lon, resolution=res)
    start = when.replace(minute=0, second=0, microsecond=0)
    rows = features.build(spot, start, hours=1, step_minutes=60, species=species)
    if not rows:
        raise RuntimeError("no feature row for that hour")
    r = rows[0]
    keep = ("current_speed", "current_dir", "water_temp_f", "wind_kt", "wind_dir",
            "light_phase", "pressure_trend_3h", "next_tide", "moon_phase",
            "moon_illum", "wind_against_tide", "exposed")
    return {k: r.get(k) for k in keep if k in r}


def _observations(lat: float, lon: float) -> dict:
    """The most recent actual observation, not the gridded forecast.

    Six hours back because a coastal station can go quiet for a while, and a
    three-hour-old real reading beats a model value for right now.
    """
    from datetime import timedelta
    from . import sources
    end = datetime.now()
    rows = sources.nws_observations(lat, lon, end - timedelta(hours=6), end)
    if not rows:
        raise RuntimeError("no observation in the last six hours")
    latest = rows[-1]
    return {"observed_at": str(latest.get("time") or ""),
            **{k: v for k, v in latest.items() if k != "time"}}


def _offshore_layers(lat, lon, L, U, include_slow: bool) -> None:
    from . import offshore

    t, err = _try(offshore.nearest_turbine, lat, lon)
    if t:
        L["turbine"] = _d(t, "BOEM / Block Island Wind Farm", RES["chart_feature"],
                          "structure holds bait and fish")

    b, err = _try(offshore.buoy)
    if b:
        L["buoy"] = _d(b, "NDBC", RES["buoy"],
                       "real measured sea state, not a model")
    else:
        U["buoy"] = err

    hf, err = _try(offshore.surface_current, lat, lon)
    if hf:
        L["surface_current"] = _d(hf, "HF radar (ucsdHfrE2)", RES["hf_radar"],
                                  "measured surface drift — this is the one "
                                  "layer that is a real current observation "
                                  "rather than a harmonic prediction")
    else:
        U["surface_current"] = err

    if not include_slow:
        return

    br, err = _try(offshore.breaks, lat, lon)
    if br:
        L["thermal_breaks"] = _d(br, "MUR SST", RES["sst"],
                                 "temperature gradient — where pelagics stack up")
    else:
        U["thermal_breaks"] = err

    ch, err = _try(offshore.chlorophyll, lat, lon)
    if ch:
        L["chlorophyll"] = _d(ch, "satellite ocean colour", RES["chlorophyll"],
                              "water colour, a proxy for the base of the chain")


def _sighting_layers(lat, lon, L, U) -> None:
    from . import bait as baitmod, birds, whales

    b, err = _try(birds.bait_activity, lat, lon)
    if b:
        L["birds"] = _d(b, "eBird", RES["sighting"],
                        "bait proxy — a bird found bait, you did not")
    else:
        U["birds"] = err

    w, err = _try(whales.activity, lat, lon)
    if w:
        L["whales"] = _d(w, "iNaturalist", RES["sighting"],
                         "bait proxy with a higher threshold than birds")
    else:
        U["whales"] = err

    log, err = _try(baitmod.load)
    if log is not None:
        near = []
        for r in log:
            try:
                dist = baitmod._nm(lat, lon, float(r["lat"]), float(r["lon"]))
            except (KeyError, TypeError, ValueError):
                continue
            if dist <= baitmod.MAX_NM:
                near.append({**r, "distance_nm": round(dist, 2)})
        near.sort(key=lambda r: r.get("when", ""), reverse=True)
        L["bait_log"] = _d(near, "your own log and fishing reports", RES["sighting"],
                           "the only bait layer that is an actual look at bait, "
                           "rather than an animal standing in for one")
