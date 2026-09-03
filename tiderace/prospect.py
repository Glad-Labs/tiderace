"""Unnamed coordinates worth trying, and what each claim is worth.

The ask was one number per coordinate, down to the metre: depth, temperature,
thermal breaks, chlorophyll, current, all of it folded together into "this spot
might be good for this fish". Half of that is buildable today. The other half
cannot be built by anyone, and the measurement says why.

Resolution of every input this project has:

    charted sounding          1 m     a real measurement at a real point
    chart feature             5 m     wrecks, rocks, obstructions
    NCEI elevation model      ~3 m    the bottom, modelled
    CO-OPS gauge            100 m     reads its own piece of water
    MUR SST                1000 m
    NWS gridpoint          2500 m
    VIIRS chlorophyll      4000 m
    current station        5556 m     38 of them in the bay, 3 nm apart
    HF radar               6000 m

Measured, not assumed: resolve the current station at Whale Rock and again at
50 m, 200 m and 1000 m north, and it is the same station every time. It only
changes at 5 km. The SST pixel is 1 km across and the chlorophyll pixel is
4 km, so two coordinates a hundred metres apart do not merely get *similar*
water -- they get the identical number, from the same pixel and the same
gauge.

So a single blended score per coordinate would be fake precision by
construction: the water half is a constant across every coordinate in the box,
and only the bottom varies at the scale of a drift. Blending them would let a
constant masquerade as local knowledge.

Two questions instead, which is how the decision is actually made:

    AREA      is this water worth fishing right now?
              current, temperature, thermal break, chlorophyll, light, season
              -- coarse, 1 to 6 km, identical everywhere in the box

    SPOT      where in it do I put the boat?
              relief, depth, drop, distance to charted structure
              -- fine, metres, and the only thing that varies

The ranking is by structure, because structure is the only input that
distinguishes one coordinate from its neighbour. The area score decides
whether to bother with the box at all. Saying which is which is the entire
value of this module; a prettier version that hid it would be worth less.

Depth is ranked as structure, never as a preference, and that stays true now
that two species carry a published depth band: the ranking below is by relief,
because relief is what distinguishes one coordinate from its neighbour. What
the band buys is a *label* on a bump -- `depth_suits` on each prospect says
which species' published band the depth falls in, and what that band actually
claims. Twelve of the fourteen have no band and appear on no bump; see
`score.PROFILES` for which source was consulted for each and what it said --
several of those twelve are refusals with a reason, not gaps.
"""

from __future__ import annotations

from datetime import datetime

from . import features, offshore, score, spots, stations, structure, survey
from .sources import SourceError


def _area(lat: float, lon: float, species: str, when: datetime,
          deep: bool = False) -> dict:
    """The water, once, for the whole box. It does not vary inside one."""
    out: dict = {"resolution_m": {}, "unavailable": {}}

    try:
        res = stations.resolve(lat, lon)
        spot, res = spots.at_coord(lat, lon, resolution=res)
        rows = features.build(spot, when, 1, 60, species=species)
        row = rows[0] if rows else {}
        sc = score.score(species, row, exposed=row.get("exposed", False),
                         prior=spot.prior(species), best_stage=spot.best_stage)
        out["score"] = sc["score"]
        out["terms"] = sc.get("terms", {})
        from .heat import _limiting
        out["limiting"] = _limiting(sc.get("terms", {}),
                                    score.PROFILES[species].weights)
        out["current_speed"] = row.get("current_speed")
        out["current_stage"] = row.get("current_stage")
        out["water_temp_f"] = row.get("water_temp_f")
        out["light_phase"] = row.get("light_phase")
        out["confidence"] = res.get("confidence")
        out["resolution_m"]["current"] = survey.RES["station"]
        cur = res.get("current") or {}
        if cur.get("distance_nm"):
            # The station's own footprint is 100 m; how far away it is from
            # here is the number that actually limits the claim.
            out["current_station_nm"] = cur["distance_nm"]
            out["resolution_m"]["current"] = int(cur["distance_nm"] * 1852)
    except (SourceError, ValueError, KeyError) as exc:
        out["unavailable"]["water"] = str(exc)

    # Thermal break: where the water changes temperature fastest. Offshore it
    # is the whole game; inshore it is usually flat, and saying "no break" is
    # a real answer rather than a missing one.
    #
    # Two traps here, both silent. `breaks` returns `grad_c_per_nm` -- degrees
    # CELSIUS per nautical mile -- and reading it as `gradient_f_per_nm`
    # dropped the whole field without a word. And `sst_grid` spans 0.25 deg,
    # roughly 15 nm, so the sharpest break in it can be twenty miles from the
    # box: "the water changes fast nearby" is worthless without saying how
    # near. Distance is reported and anything beyond 5 nm is called out.
    try:
        grid = offshore.sst_grid(lat, lon, box=0.25)
        br = offshore.breaks(grid, top=1)
        if br:
            b = dict(br[0])
            b["grad_f_per_nm"] = round(b.get("grad_c_per_nm", 0.0) * 1.8, 3)
            b["distance_nm"] = round(
                structure._dist_m(lat, lon, b["lat"], b["lon"],
                                  structure._m_per_deg_lon(lat)) / 1852.0, 1)
            b["near"] = b["distance_nm"] <= 5.0
            out["thermal_break"] = b
        else:
            out["thermal_break"] = None
        out["resolution_m"]["sst"] = survey.RES["sst"]
    except (SourceError, ValueError, KeyError, TypeError) as exc:
        out["unavailable"]["thermal_break"] = str(exc)

    # Chlorophyll is opt-in, and the reason is timing rather than taste: a cold
    # call took 27 s inshore and 110 s offshore, and both returned None. VIIRS
    # is cloud-limited and unreliable close to shore, so the common answer is
    # "no pixel today" -- which is a fine answer to wait 0 s for and a terrible
    # one to wait two minutes for while a boat drifts. The module caches misses,
    # so once a box has been asked it is instant; `deep` is what does the
    # asking.
    if deep:
        try:
            ch = offshore.chlorophyll(lat, lon, box=0.25)
            out["chlorophyll"] = ch
            out["resolution_m"]["chlorophyll"] = survey.RES["chlorophyll"]
            if ch is None:
                out["unavailable"]["chlorophyll"] = (
                    "no VIIRS pixel here today (cloud, or too close to shore)")
        except (SourceError, ValueError, KeyError, TypeError) as exc:
            out["unavailable"]["chlorophyll"] = str(exc)
    else:
        out["unavailable"]["chlorophyll"] = (
            "not fetched: a cold VIIRS call took 110 s and returned nothing. "
            "Pass deep=1 to wait for it.")

    return out


def _why(bump: dict, area: dict) -> list[str]:
    """Plain sentences, each one traceable to a number above it."""
    out = []
    r = bump.get("relief_ft")
    if r:
        out.append("stands %.0f ft above the bottom within 220 m "
                   "(top %.0f ft, around %.0f ft)"
                   % (r, bump.get("depth_ft") or 0, bump.get("surround_ft") or 0))
    if bump.get("drop_ft"):
        out.append("falls away %.0f ft on its deep side" % bump["drop_ft"])
    if bump.get("novel"):
        out.append("no charted rock, wreck or obstruction within 100 m — "
                   "this one is not on the chart")
    elif bump.get("charted_hazard_m") is not None:
        out.append("%.0f m from a charted hazard, so probably already known"
                   % bump["charted_hazard_m"])

    # Everything below is the area, not the spot, and is labelled that way.
    if area.get("current_speed") is not None:
        out.append("area: %.2f kt %s current"
                   % (area["current_speed"], area.get("current_stage") or ""))
    if area.get("water_temp_f") is not None:
        out.append("area: %.0f °F water" % area["water_temp_f"])
    tb = area.get("thermal_break")
    if tb and tb.get("grad_f_per_nm"):
        out.append("area: sharpest temperature change %.2f °F/nm, %s nm away%s"
                   % (tb["grad_f_per_nm"], tb["distance_nm"],
                      "" if tb.get("near") else " — too far to matter here"))
    ch = area.get("chlorophyll")
    if ch and ch.get("median_mg_m3") is not None:
        out.append("area: chlorophyll %.2f mg/m³" % ch["median_mg_m3"])
    if area.get("limiting"):
        out.append("area held back by %s" % area["limiting"])
    return out


def prospects(bbox, species: str = "striped_bass", n: int = 61,
              when: datetime | None = None, limit: int = 20,
              min_relief_ft: float = 3.0, deep: bool = False) -> dict:
    """Rank unnamed coordinates in a box, and separate area from spot."""
    if species not in score.PROFILES:
        raise ValueError("unknown species %r" % species)
    when = (when or datetime.now()).replace(minute=0, second=0, microsecond=0)
    south, west, north, east = (float(v) for v in bbox)
    mid_lat, mid_lon = (south + north) / 2.0, (west + east) / 2.0

    scan = structure.scan_view(bbox, n=n, min_relief_ft=min_relief_ft,
                               limit=limit)
    area = _area(mid_lat, mid_lon, species, when, deep=deep)

    out = {
        "species": species,
        "species_name": score.PROFILES[species].name,
        "when": when.isoformat(),
        "bbox": [south, west, north, east],
        "area": area,
        "sample_m": scan.get("sample_m"),
        "usable": scan.get("usable"),
        "prospects": [],
        # The ranking is by relief and stays that way. Depth appears on a
        # prospect as `depth_suits`, which labels rather than ranks.
        "depth_scored": False,
    }
    if not scan.get("usable"):
        out["note"] = scan.get("note")
        return out

    for b in scan.get("bumps", []):
        b = dict(b)
        b["why"] = _why(b, area)
        b["area_score"] = area.get("score")
        out["prospects"].append(b)

    out["note"] = (
        "Ranked by structure, because structure is the only input that varies "
        "between two coordinates a hundred metres apart. The area score (%s) "
        "is one number for the whole box: the current station, the SST pixel "
        "and the chlorophyll pixel do not change inside it. Bottom is modelled "
        "at about %s m; the water is 1 to 6 km. Structure is not fish."
        % (area.get("score"), scan.get("sample_m")))
    return out


# ---- where to go, for one fish, right now -------------------------------
#
# The app began by ranking twenty-one curated spots, and that is not the
# question. The question is where to put the boat given everything known, and
# nothing about a curated list answers it -- every one of those spots is
# inside the bay, somebody chose them, and a coordinate two hundred metres
# away that nobody named is invisible to a ranking built from that list.
#
# So this ranks coordinates, not spots. What makes that honest rather than
# just finer is the measurement in this module's header: inside a box you
# could drift, the water does not vary. Scored over a 2 km box for fluke, 576
# cells came back spanning 49.4 to 57.2 -- sd 2.72 -- because every cell shares
# a current station, an SST pixel and a chlorophyll pixel. Ranking coordinates
# by that spread would be ranking noise.
#
# Two things do vary at the scale of a drift, and both are defensible:
#
#   relief   measured off the ~3 m model, tens of metres of variation
#   depth    but ONLY for a species with a published band -- fluke and black
#            sea bass have one, the other four do not, and for those the
#            depth of a bump is reported and never scored
#
# So the ranking is relief, gated and then ordered by the species' own cited
# band where one exists. For a fish with no band the answer says so instead of
# quietly ranking by structure alone and letting it read as a fish forecast.

def best(bbox, species: str = "striped_bass", n: int = 61,
         when: datetime | None = None, limit: int = 12,
         min_relief_ft: float = 3.0, deep: bool = False) -> dict:
    """Ranked coordinates for one species, finest first."""
    if species not in score.PROFILES:
        raise ValueError("unknown species %r" % species)
    out = prospects(bbox, species, n=n, when=when, limit=60,
                    min_relief_ft=min_relief_ft, deep=deep)
    prof = score.PROFILES[species]
    banded = bool(prof.depth)

    ranked = []
    for c in out.get("prospects", []):
        fit = None
        if banded:
            hit = [d for d in (c.get("depth_suits") or [])
                   if d["species"] == species]
            # Outside the published band is not a candidate for THIS fish. It
            # may still be a fine bump; it is not one this species is cited as
            # using.
            if not hit:
                continue
            fit = hit[0]["fit"]
        r = dict(c)
        r["depth_fit"] = fit
        # Relief is the measured thing and stays the spine of the order. Where
        # a band exists it breaks ties, because a 12 ft bump inside the cited
        # depth is a better answer than a 12 ft bump on its edge.
        r["rank_on"] = ("relief within the published depth band" if banded
                        else "relief only")
        ranked.append(r)

    ranked.sort(key=lambda r: (-(r.get("relief_ft") or 0),
                               -(r.get("depth_fit") or 0)))
    out["best"] = ranked[:limit]
    out["depth_banded"] = banded
    out["ranked_by"] = ("relief, restricted to the depths %s is cited at"
                        % prof.name) if banded else (
                       "relief alone — no published depth band for %s, so depth "
                       "is reported and not scored" % prof.name)
    out["note_best"] = (
        "%d coordinate%s, ranked by what actually varies where you drift. The "
        "area score (%s) is one number for the whole box: every cell here shares "
        "a current station, an SST pixel and a chlorophyll pixel, so it decides "
        "whether to come at all and cannot decide where."
        % (len(out["best"]), "" if len(out["best"]) == 1 else "s",
           (out.get("area") or {}).get("score")))
    return out
