"""Offshore species: the bands, their sources, and -- for now -- no score.

Matt, 3 September 2026: "why don't we have rankings for tuna? ... it would
be cool to have some forecasting for all species based on what we have so
far." Then: "go, start with bluefin and mahi."

The bay scorer refuses these fish for a structural reason recorded in
score.NOT_PROFILED: its load-bearing term is bay tidal current, and there is
no current station seventeen miles out. An offshore forecast needs its own
scorer, built on what offshore.py already fetches -- 1 km sea-surface
temperature and the fronts in it, chlorophyll, the nearest buoy, occurrence
records -- and its own bands. This file is the bands. Every number below is
transcribed from a document named in SOURCES with the page it came from,
exactly as score.PROFILES does inshore, because a band from memory would
produce a forecast that looks excellent and predicts nothing. Where the
literature is about a different ocean or a different life stage, the claim
says so.

The bands were shown and agreed on 3 September 2026 ("bands look right,
build the scorer, include bigeye and yellowfin"), and the scorer follows
below. Two tiers of claim live in this file and they are kept apart on
purpose: the BANDS can be checked against a document, and each one names
it; the WEIGHTS cannot, and are unvalidated priors until there are offshore
trips in the log -- `evaluate` has five trips today, none offshore, and
cannot tell a good offshore scorer from a bad one. Every score carries
`unvalidated: True` and the interface says so. Where a profile's literature
names something nothing here can measure -- a weed line, the thermocline --
the profile says that too, rather than scoring a proxy and calling it the
thing.

Temperatures are Fahrenheit, converted from the cited Celsius and rounded to
the degree, because that is what the boat's gauge and the MUR product show.
A trapezoid is (zero, full, full, zero): outside the outer pair the term is
0, between the inner pair it is 1, and it ramps linearly between.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def f(c: float) -> int:
    """Celsius to whole Fahrenheit, the way every band below was converted."""
    return round(c * 9 / 5 + 32)


SOURCES = {
    "A10": ("NOAA Fisheries, 2017. Final Amendment 10 to the 2006 Consolidated "
            "Atlantic Highly Migratory Species Fishery Management Plan: Essential "
            "Fish Habitat. Chapter 6.1, Atlantic bluefin tuna, pp. 104-111. "
            "https://www.habitat.noaa.gov/application/efhinventory/docs/a10_hms_efh.pdf"),
    "LAWSON2010": ("Lawson, G.L., Castleton, M.R. and Block, B.A., 2010. Movements and "
                   "diving behavior of Atlantic bluefin tuna in relation to water column "
                   "structure in the northwestern Atlantic. Archival tags 1999-2005, "
                   "Gulf of Maine, Canadian shelf and off-shelf waters. As summarised "
                   "in A10 p. 104-105."),
    "GALUARDI2012": ("Galuardi, B. and Lutcavage, M., 2012. Dispersal routes and habitat "
                     "utilization of juvenile Atlantic bluefin tuna tracked with mini "
                     "PSAT and archival tags. Juveniles aged 2-5 tagged off Cape Cod "
                     "2005-2009. As summarised in A10 p. 105-106."),
    "BLOCK2001": ("Block, B.A. et al., 2001. Migratory movements, depth preferences, and "
                  "thermal biology of Atlantic bluefin tuna. Science 293. Cited in A10 "
                  "p. 91 for the 3-30 C range withstood."),
    "SAFMC2003": ("South Atlantic Fishery Management Council, January 2003. Fishery "
                  "Management Plan for the Dolphin and Wahoo Fishery of the Atlantic. "
                  "Section 3.3.1 'Environmental Requirements at Different Life Stages', "
                  "p. 96; Action 22 (EFH), p. 230; gear description, Section 3.4. "
                  "https://faolex.fao.org/docs/pdf/usa162621.pdf"),
    "GIBBS1959": ("Gibbs, R.H. and Collette, B.B., 1959. On the identification, "
                  "distribution, and biology of the dolphins Coryphaena hippurus and "
                  "C. equiselis. Bull. Mar. Sci. Gulf Caribb. 9. Cited in SAFMC2003 "
                  "p. 96 for the 20 C isotherm as the limit of the dolphin's normal range."),
    "BEARDSLEY1967": ("Beardsley, G.L., 1967. Age, growth, and reproduction of the dolphin, "
                      "Coryphaena hippurus, in the Straits of Florida. Copeia 1967. Cited "
                      "in SAFMC2003 p. 96: increased numbers of adults in late spring and "
                      "summer at 26-28 C."),
    "HASSLER1977": ("Hassler, W.W. and Hogarth, W.T., 1977. The growth and culture of "
                    "dolphin, Coryphaena hippurus, in North Carolina. Aquaculture 12. "
                    "Cited in SAFMC2003 p. 96: captive dolphin tolerated 15-29.4 C."),
    "OBIS": ("Ocean Biodiversity Information System occurrence records within 60 nm of "
             "40.9 N, 71.3 W, fetched 3 September 2026 through offshore.occurrences. "
             "Bluefin: 423 records, Jun-Nov, 259 of them in August. Mahi: 1,191 records, "
             "Jul-Oct, 154 in August and 102 in September. Yellowfin: 1,623 records, "
             "Jul-Oct, 111 in August and 106 in September. Bigeye: 1,298 records, "
             "Jul-Oct, 120 in September and 97 in October. Records are where people "
             "were and reported, not where fish were; they say when, not how many."),
    "A10YFT": ("NOAA Fisheries, 2017. Final Amendment 10 (as A10), Section 6.2.5 Atlantic "
               "yellowfin tuna, pp. 114-116: 'an epipelagic, oceanic species, found in "
               "water temperatures between 18 and 31 C'; 'generally confined to the "
               "upper 100 m'; 'distribution has been associated with thermocline "
               "depth'; 'association with floating objects has been observed'; EFH "
               "for juveniles and adults 'offshore pelagic habitats seaward of the "
               "continental shelf break' from Georges Bank to Cape Cod and 'offshore "
               "and coastal habitats from Cape Cod to North Carolina'."),
    "A10BET": ("NOAA Fisheries, 2017. Final Amendment 10 (as A10), Section 6.2.2 Atlantic "
               "bigeye tuna, pp. 100-102: 'scientific knowledge of Atlantic bigeye tuna "
               "is limited'; 'regularly found in deeper waters than are other tuna, "
               "descending to 300 to 500 m and then returning regularly to the surface "
               "layer (Musyl et al. 2003)'; 'can tolerate water with temperatures as low "
               "as 5 C (Brill et al. 2005)'; juveniles school at the surface with "
               "yellowfin and skipjack and 'associate with floating objects, whale "
               "sharks, and sea mounts', associations that 'weaken as bigeye tuna "
               "mature'; EFH for juveniles and adults 'offshore pelagic habitats seaward "
               "of the continental shelf break' from the EEZ on Georges Bank to south "
               "of Cape Cod and Cape Cod to Cape Hatteras."),
}


@dataclass(frozen=True)
class PelagicProfile:
    key: str
    name: str
    sst: tuple[int, int, int, int] | None   # trapezoid, F: zero, full, full, zero; None = reported, not scored
    sst_claim: str
    months: tuple[int, ...]             # months with records or literature presence
    peak_months: tuple[int, ...]
    season_claim: str
    features: tuple[str, ...]           # what the literature associates the fish with
    features_claim: str
    fish_depth_note: str                # where in the column the fish sit
    sources: tuple[str, ...]            # keys into SOURCES


PROFILES: dict[str, PelagicProfile] = {
    "bluefin": PelagicProfile(
        key="bluefin", name="Bluefin Tuna",
        sst=(f(4), f(15), f(20), f(26)),            # 39, 59, 68, 79
        sst_claim=(
            "Full credit 59-68 F (15-20 C): PSAT-tagged juveniles off Cape Cod "
            "were 'primarily found near the surface at temperatures from 15 to "
            "20 C' in summer [GALUARDI2012], and adults on the Gulf of Maine and "
            "Canadian shelf foraging grounds 'occupied a relatively constant "
            "ambient temperature regime, with monthly median sea surface "
            "temperature between 16 and 19 C' [LAWSON2010]. Zero at 39 F and 79 F "
            "(4 and 26 C), the full range of sea temperatures the tagged juveniles "
            "experienced across all seasons [GALUARDI2012]. The species has been "
            "found to withstand 3-30 C [BLOCK2001]; that is tolerance, not "
            "preference, and is not the band."),
        months=(6, 7, 8, 9, 10, 11), peak_months=(7, 8),
        season_claim=(
            "Tagged fish 'arrived in the study region' in March-April in off-shelf "
            "water along the Gulf Stream edge, 'shifted distribution shoreward onto "
            "the shelf' as it warmed into summer, and 'departed shelf waters by "
            "November' [LAWSON2010]. Off Rhode Island the records agree: OBIS has "
            "bluefin June through November with 259 of 423 records in August "
            "[OBIS]. Peak is July-August on those records."),
        features=("shelf_break", "front"),
        features_claim=(
            "Summer core areas of tagged juveniles were 'coastal areas, the Gulf "
            "Stream margin and shelf break north of Cape Hatteras to the southern "
            "Gulf of Maine' [GALUARDI2012]; spring arrivals were 'along the edge of "
            "the Gulf Stream' [LAWSON2010]; adult EFH was expanded 'seaward of the "
            "continental shelf break to the outer extent of the EEZ' from Delaware "
            "to southern Maine on PSAT data [A10 p. 110-111]. Prey on the shelf: "
            "herring, mackerel, sand lance, squid [A10 p. 106]."),
        fish_depth_note=(
            "Most time in the upper 10 m [LAWSON2010] and at less than 20 m "
            "[GALUARDI2012]; dives to 500-1,000 m. Bottom depth is where the "
            "shelf break is, not a band on the fish."),
        sources=("A10", "LAWSON2010", "GALUARDI2012", "BLOCK2001", "OBIS"),
    ),
    "mahi": PelagicProfile(
        key="mahi", name="Mahi-mahi (Dolphinfish)",
        sst=(f(20), f(26), f(28), f(29.4)),         # 68, 79, 82, 85
        sst_claim=(
            "Zero below 68 F: 'Gibbs and Collette (1959) gave the 20 C isotherm as "
            "the limit of the dolphin's normal range' [SAFMC2003 p. 96, GIBBS1959]. "
            "Full credit 79-82 F: 'increased numbers of adults in late spring and "
            "summer when water temperatures were 26 to 28 C' [BEARDSLEY1967], in "
            "the Straits of Florida -- a warmer ocean than this one, so off Rhode "
            "Island the term will usually sit on the lower ramp, which is honest: "
            "this is the northern fringe of the range. Zero above 85 F: captive "
            "fish tolerated 15-29.4 C [HASSLER1977]; the 15 C floor of that "
            "tolerance is NOT used, because tolerance in a tank is not the normal "
            "range at sea and Gibbs and Collette's isotherm is."),
        months=(6, 7, 8, 9, 10), peak_months=(8, 9),
        season_claim=(
            "No New England seasonality in the FMP; larval peaks are Gulf of "
            "Mexico and do not transfer. Off Rhode Island the records give it: "
            "OBIS has mahi July through October, 154 records in August and 102 in "
            "September of 1,191 [OBIS]. June is included on the temperature band "
            "alone and carries no records."),
        features=("front", "floating_structure"),
        features_claim=(
            "EFH 'is the Gulf Stream, Charleston Gyre, Florida Current, and pelagic "
            "Sargassum' [SAFMC2003 Action 22]. Juveniles 'are closely associated "
            "with floating objects and Sargassum' [SAFMC2003 p. 96, GIBBS1959]; "
            "the commercial gear is set 'along weed lines or temperature breaks' "
            "[SAFMC2003 Section 3.4]. A temperature break is measurable from the "
            "MUR product; a weed line is not measurable from anything this project "
            "has, and the scorer must say so rather than pretend."),
        fish_depth_note=(
            "Surface fish, on floating structure; no depth band, and bottom depth "
            "is irrelevant except that spawning is 'over or beyond the continental "
            "shelf' [SAFMC2003 p. 96]."),
        sources=("SAFMC2003", "GIBBS1959", "BEARDSLEY1967", "HASSLER1977", "OBIS"),
    ),
    "yellowfin": PelagicProfile(
        key="yellowfin", name="Yellowfin Tuna",
        sst=(f(18), f(18), f(31), f(31)),           # 64, 64, 88, 88: a step
        sst_claim=(
            "A step, not a trapezoid: the source gives a range and no preference "
            "inside it. 'Found in water temperatures between 18 and 31 C' "
            "[A10YFT], so full credit from 64 F to 88 F and zero outside. Writing "
            "ramps onto that would be inventing the shape of a curve the "
            "document does not draw."),
        months=(7, 8, 9, 10), peak_months=(8, 9),
        season_claim=(
            "No New England seasonality in the source; the Gulf of Mexico "
            "July-December catches [A10YFT] are a different ocean. Off Rhode "
            "Island the records give it: OBIS has yellowfin July through October, "
            "111 records in August and 106 in September of 1,623 [OBIS]."),
        features=("shelf_break", "floating_structure"),
        features_claim=(
            "EFH for juveniles and adults is 'offshore pelagic habitats seaward of "
            "the continental shelf break' [A10YFT]; 'association with floating "
            "objects has been observed' [A10YFT] and nothing here can see one. "
            "Distribution 'has been associated with thermocline depth' [A10YFT], "
            "which this project cannot measure either; a surface front is not the "
            "thermocline and is not scored as one for this fish."),
        fish_depth_note=(
            "'Generally confined to the upper 100 m' [A10YFT]; most time shallower "
            "than 50 m. Bottom depth matters only as the shelf break."),
        sources=("A10YFT", "OBIS"),
    ),
    "bigeye": PelagicProfile(
        key="bigeye", name="Bigeye Tuna",
        sst=None,
        sst_claim=(
            "No band. 'Scientific knowledge of Atlantic bigeye tuna is limited' "
            "[A10BET], and the only temperature figure the source carries is a "
            "tolerance floor of 5 C [A10BET] for a fish that spends its days at "
            "300 to 500 m [A10BET]. Surface temperature is REPORTED for bigeye and "
            "never scored, the way depth is reported and never scored for the "
            "inshore species with no published band."),
        months=(7, 8, 9, 10, 11), peak_months=(9, 10),
        season_claim=(
            "Nothing in the source about New England timing. OBIS has bigeye July "
            "through November off Rhode Island, 120 records in September and 97 "
            "in October of 1,298 [OBIS]; later in the year than the other three, "
            "on those records."),
        features=("shelf_break",),
        features_claim=(
            "EFH for juveniles and adults is 'offshore pelagic habitats seaward of "
            "the continental shelf break' [A10BET]. Juvenile associations with "
            "floating objects and sea mounts 'weaken as bigeye tuna mature' "
            "[A10BET], so floating structure is not a term for this fish even if "
            "it were measurable."),
        fish_depth_note=(
            "'Descending to 300 to 500 m and then returning regularly to the "
            "surface layer' [A10BET]. The canyon walls at the shelf break are the "
            "bottom this describes."),
        sources=("A10BET", "OBIS"),
    ),
}


# ---- the scorer ------------------------------------------------------------
#
# Terms, each 0..1, each present only where the profile's literature gives it
# a reason to be:
#
#   sst        trapezoid on the surface temperature at the position, from the
#              MUR grid. Absent for bigeye (no band).
#   front      how close the position is to a sharp temperature break, and how
#              sharp: min(1, gradient / FRONT_FULL_C_PER_NM) * exp(-nm / FRONT_REACH_NM).
#              Present where the profile lists "front".
#   structure  how close the position is to the shelf break or a canyon wall,
#              and how steep that wall is: min(1, slope / STRUCTURE_FULL_M_PER_KM)
#              * exp(-nm / STRUCTURE_REACH_NM). The steepness matters because
#              a candidate found ON the shelf break is 0 nm from it by
#              construction -- without it every wall scored 1.0 and the fish
#              that live on walls ranked flat at 100. Present where the profile
#              lists "shelf_break".
#   season     1 in a peak month, SEASON_SHOULDER in another listed month, 0
#              otherwise. The months are OBIS records, not a preference.
#
# Then one multiplier that is about the boat, not the fish: sea state from the
# Block Island buoy. It never raises a score and the explanation calls it
# fishability so nobody reads it as biology.
#
# The weights are the part no document gives. They are stated here as priors,
# normalised over the terms a profile actually has, and every score says
# `unvalidated`. When there are offshore trips in the log, `evaluate` is the
# thing that gets to move them.

FRONT_FULL_C_PER_NM = 0.3     # measured: the sharpest fronts in the box on 2 Sep 2026 were 0.37
FRONT_REACH_NM = 5.0
STRUCTURE_REACH_NM = 10.0
STRUCTURE_FULL_M_PER_KM = 150.0   # measured: the canyon walls at 39.8 N run 130-170 m/km
SEASON_SHOULDER = 0.6
SEA_FULL_M = 1.5              # up to this wave height the multiplier is 1
SEA_ZERO_M = 4.0              # at this it is SEA_FLOOR; a fishability judgement, not fish

SEA_FLOOR = 0.3

WEIGHTS: dict[str, dict[str, float]] = {
    "bluefin":   {"sst": 0.35, "front": 0.25, "structure": 0.20, "season": 0.20},
    "mahi":      {"sst": 0.40, "front": 0.35, "season": 0.25},
    "yellowfin": {"sst": 0.30, "structure": 0.35, "season": 0.35},
    "bigeye":    {"structure": 0.55, "season": 0.45},
}

UNMEASURABLE = {
    "floating_structure": "floating structure (weed lines, debris): nothing this "
                          "project fetches can see one",
}


def _trapezoid(x, lo_out, lo_in, hi_in, hi_out):
    """score.trapezoid, with a step allowed (lo_out == lo_in)."""
    if x is None:
        return None
    if x < lo_out or x > hi_out:
        return 0.0
    if lo_in <= x <= hi_in:
        return 1.0
    if x < lo_in:
        return (x - lo_out) / (lo_in - lo_out)
    return (hi_out - x) / (hi_out - hi_in)


def score(species: str, feat: dict) -> dict:
    """One position, one profile. `feat` carries sst_f, front_nm,
    front_grad_c_nm, structure_nm, month, wave_m (any may be None)."""
    prof = PROFILES[species]
    weights = WEIGHTS[species]
    terms: dict[str, float] = {}
    absent: dict[str, str] = {}

    if "sst" in weights:
        t = _trapezoid(feat.get("sst_f"), *prof.sst) if prof.sst else None
        if t is None:
            absent["sst"] = "no surface temperature at this position"
        else:
            terms["sst"] = t
    if "front" in weights:
        d, g = feat.get("front_nm"), feat.get("front_grad_c_nm")
        if d is None or g is None:
            absent["front"] = "no temperature break found in the box"
        else:
            import math
            terms["front"] = min(1.0, g / FRONT_FULL_C_PER_NM) * math.exp(-d / FRONT_REACH_NM)
    if "structure" in weights:
        d, sl = feat.get("structure_nm"), feat.get("structure_slope")
        if d is None or sl is None:
            absent["structure"] = "no shelf break or canyon wall located"
        else:
            import math
            terms["structure"] = min(1.0, sl / STRUCTURE_FULL_M_PER_KM) * math.exp(-d / STRUCTURE_REACH_NM)
    if "season" in weights:
        m = feat.get("month")
        if m is None:
            absent["season"] = "no date to place in the season"
        else:
            terms["season"] = (1.0 if m in prof.peak_months
                               else SEASON_SHOULDER if m in prof.months else 0.0)

    if not terms:
        return {"score": None, "terms": {}, "absent": absent, "sea": None,
                "unvalidated": True, "species": species}
    wsum = sum(weights[k] for k in terms)
    raw = sum(weights[k] * v for k, v in terms.items()) / wsum

    wave = feat.get("wave_m")
    sea = 1.0
    if wave is not None and wave > SEA_FULL_M:
        sea = max(SEA_FLOOR, 1.0 - (wave - SEA_FULL_M) / (SEA_ZERO_M - SEA_FULL_M) * (1.0 - SEA_FLOOR))
    return {
        "score": round(100.0 * raw * sea, 1),
        "terms": {k: round(v, 3) for k, v in terms.items()},
        "weights": {k: weights[k] / wsum for k in terms},
        "absent": absent,
        "unmeasurable": [UNMEASURABLE[f] for f in prof.features if f in UNMEASURABLE],
        "sea": round(sea, 2),
        "unvalidated": True,
        "species": species,
    }


def explain(res: dict, feat: dict) -> str:
    """Plain words, each traceable to a term above."""
    if res.get("score") is None:
        return "no term could be computed here"
    prof = PROFILES[res["species"]]
    bits = []
    t = res["terms"]
    if "sst" in t:
        bits.append("%.0f °F is %s the %s band" % (
            feat.get("sst_f"), "inside" if t["sst"] >= 0.99 else
            "on the edge of" if t["sst"] > 0 else "outside", prof.name.split(" (")[0].lower()))
    elif prof.sst is None and feat.get("sst_f") is not None:
        bits.append("%.0f °F, reported not scored" % feat["sst_f"])
    if "front" in t:
        bits.append("break %.1f nm away at %.2f °F/nm" % (
            feat.get("front_nm"), (feat.get("front_grad_c_nm") or 0) * 1.8))
    if "structure" in t:
        bits.append("shelf break %.0f nm away, %.0f m/km" % (feat.get("structure_nm"),
                                                             feat.get("structure_slope") or 0))
    if "season" in t:
        bits.append("peak month on the records" if t["season"] >= 1 else
                    "in season on the records" if t["season"] > 0 else "no records this month")
    if res.get("sea") is not None and res["sea"] < 1:
        bits.append("sea state %.1f m, fishability ×%.2f" % (feat.get("wave_m"), res["sea"]))
    for a in res.get("absent", {}).values():
        bits.append(a)
    for u in res.get("unmeasurable", []):
        bits.append(u)
    return "; ".join(bits) + ". Unvalidated: no offshore trips in the log yet."


# ---- the positions -----------------------------------------------------------
#
# Two kinds of candidate, one per thing the literature names and this project
# can measure:
#
#   front         the sharpest temperature breaks in the MUR grid, clustered so
#                 one break is one candidate, not a row of adjacent pixels
#   shelf_break   the steepest bottom in the DEM grid -- the shelf break and
#                 the canyon walls -- clustered the same way
#
# plus your own marks inside the box. The box is the water south of Rhode
# Island out past the shelf break. Measured 3 Sep 2026: the SST grid is
# 22,801 points in 27 s (cached six hours by offshore._get), fronts up to
# 0.37 C/nm; the 61x61 bathymetry is 3.5 s, steepest cells 130-170 m/km on
# the canyon walls at 39.8 N.

OFFSHORE_BBOX = (39.5, -72.2, 41.3, -70.4)     # south, west, north, east
FRONT_CANDIDATES = 12
STRUCTURE_CANDIDATES = 12
CLUSTER_NM = 5.0
STRUCTURE_MIN_M_PER_KM = 50.0
BATHY_N = 61


def _nm(la1, lo1, la2, lo2):
    from .offshore import nm
    return nm(la1, lo1, la2, lo2)


def _cluster(rows, key, limit, min_nm=CLUSTER_NM):
    rows = sorted(rows, key=lambda r: -r[key])
    kept = []
    for r in rows:
        if any(_nm(r["lat"], r["lon"], k["lat"], k["lon"]) < min_nm for k in kept):
            continue
        kept.append(r)
        if len(kept) >= limit:
            break
    return kept


def fronts(grid: dict, limit: int = FRONT_CANDIDATES) -> list[dict]:
    """The sharpest breaks, one per break."""
    from . import offshore
    br = offshore.breaks(grid, top=max(400, limit * 40))
    return _cluster(br, "grad_c_per_nm", limit)


def slopes(bathy_grid, bbox=OFFSHORE_BBOX, n: int = BATHY_N) -> list[dict]:
    """Bottom slope per cell of a bathymetry grid, metres per km."""
    import math
    south, west, north, east = bbox
    dy = (north - south) / (n - 1) * 110_540.0
    dx = (east - west) / (n - 1) * 110_540.0 * math.cos(math.radians((south + north) / 2))
    out = []
    for i in range(1, n - 1):
        for j in range(1, n - 1):
            c = bathy_grid[i][j]
            up, dn = bathy_grid[i + 1][j], bathy_grid[i - 1][j]
            rt, lt = bathy_grid[i][j + 1], bathy_grid[i][j - 1]
            if None in (c, up, dn, rt, lt) or c >= 0:
                continue
            sl = math.hypot((up - dn) / (2 * dy), (rt - lt) / (2 * dx)) * 1000.0
            out.append({"lat": round(south + (north - south) * i / (n - 1), 4),
                        "lon": round(west + (east - west) * j / (n - 1), 4),
                        "depth_m": round(-c), "slope_m_per_km": round(sl, 1)})
    return out


def structure(bathy_grid, limit: int = STRUCTURE_CANDIDATES,
              bbox=OFFSHORE_BBOX, n: int = BATHY_N) -> list[dict]:
    steep = [r for r in slopes(bathy_grid, bbox, n) if r["slope_m_per_km"] >= STRUCTURE_MIN_M_PER_KM]
    return _cluster(steep, "slope_m_per_km", limit)


_bathy_cache: dict = {}
# cache.write_json takes a PATH. The first cut handed it a bare key and the
# bathymetry landed as a file in the checkout root, beside the code.
CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "cache", "pelagic")


def _bathy_path(bbox=OFFSHORE_BBOX, n: int = BATHY_N) -> str:
    return os.path.join(CACHE_DIR, "bathy_%s_%d.json"
                        % ("_".join("%.2f" % v for v in bbox), n))


def _bathy(bbox=OFFSHORE_BBOX, n: int = BATHY_N):
    from . import bathy, cache
    path = _bathy_path(bbox, n)
    if path in _bathy_cache:
        return _bathy_cache[path]
    hit = cache.read_json(path)
    if hit and hit.get("n") == n:
        _bathy_cache[path] = hit["grid"]
        return hit["grid"]
    south, west, north, east = bbox
    grid = bathy.sample_grid((west, south, east, north), n)
    cache.write_json(path, {"n": n, "grid": grid})
    _bathy_cache[path] = grid
    return grid


def _sst_at(grid: dict, lat: float, lon: float):
    from .offshore import _nearest_value
    c = _nearest_value(grid["points"], lat, lon)
    return None if c is None else round(c * 9 / 5 + 32, 1)


def candidates(species: str, sst_grid: dict | None = None, bathy_grid=None,
               marks: bool = True) -> tuple[list[dict], dict]:
    """The positions to score for this fish, and the shared water they sit in.

    Returns (positions, context). Each position is a dict with lat, lon,
    kind, label, notes and its features; context carries the SST date, the
    front and structure lists, and the buoy.
    """
    from . import offshore, spots
    prof = PROFILES[species]
    south, west, north, east = OFFSHORE_BBOX
    ctx: dict = {"bbox": OFFSHORE_BBOX}
    if sst_grid is None:
        sst_grid = offshore.sst_grid((south + north) / 2, (west + east) / 2,
                                     box=max(north - south, east - west) / 2)
    ctx["sst_date"] = sst_grid.get("date")
    fr = fronts(sst_grid)
    ctx["fronts"] = fr
    if bathy_grid is None:
        bathy_grid = _bathy()
    st = structure(bathy_grid)
    ctx["structure"] = st
    try:
        ctx["buoy"] = offshore.buoy("44097")
    except Exception:                                             # noqa: BLE001
        ctx["buoy"] = None

    out: list[dict] = []
    if "front" in prof.features:
        for b in fr:
            out.append({"lat": b["lat"], "lon": b["lon"], "kind": "front",
                        "notes": "temperature break: %.2f °F/nm at %.1f °F on %s"
                                 % (b["grad_c_per_nm"] * 1.8, b["sst_c"] * 9 / 5 + 32,
                                    ctx["sst_date"]),
                        "depth_ft": None, "private": False})
    if "shelf_break" in prof.features:
        for c in st:
            out.append({"lat": c["lat"], "lon": c["lon"], "kind": "shelf break",
                        "notes": "bottom falls %.0f m per km here, %.0f m deep — modelled "
                                 "bathymetry, the shelf break or a canyon wall"
                                 % (c["slope_m_per_km"], c["depth_m"]),
                        "depth_ft": round(c["depth_m"] * 3.28084), "private": False})
    if marks:
        for m in spots.SPOTS:
            if south <= m.lat <= north and west <= m.lon <= east:
                out.append({"lat": m.lat, "lon": m.lon, "kind": "mark", "key": m.key,
                            "notes": m.notes, "depth_ft": None, "private": True})

    for c in out:
        c.setdefault("key", spots.coord_key(c["lat"], c["lon"]))
        c["label"] = "%.4f, %.4f" % (c["lat"], c["lon"])
        c["sst_f"] = _sst_at(sst_grid, c["lat"], c["lon"])
        if fr:
            near = min(fr, key=lambda b: _nm(c["lat"], c["lon"], b["lat"], b["lon"]))
            c["front_nm"] = round(_nm(c["lat"], c["lon"], near["lat"], near["lon"]), 1)
            c["front_grad_c_nm"] = near["grad_c_per_nm"]
        else:
            c["front_nm"] = c["front_grad_c_nm"] = None
        if st:
            nearest = min(st, key=lambda r: _nm(c["lat"], c["lon"], r["lat"], r["lon"]))
            c["structure_nm"] = round(_nm(c["lat"], c["lon"], nearest["lat"], nearest["lon"]), 1)
            c["structure_slope"] = nearest["slope_m_per_km"]
        else:
            c["structure_nm"] = c["structure_slope"] = None
    return out, ctx


def grid(species: str, start, hours: int = 48, step_minutes: int = 30,
         sst_grid: dict | None = None, bathy_grid=None) -> dict:
    """The forecast grid for an offshore species, in the shape server.build_grid
    produces, so the page, the ranked list and the slider work unchanged.

    Nothing the literature gives these fish varies within a day, and the SST
    product is daily, so the score is flat across the horizon; the detail row
    says what the number is made of and that it is unvalidated. The time axis
    is kept so the interface has one, not because anything moves on it.
    """
    from datetime import timedelta
    positions, ctx = candidates(species, sst_grid=sst_grid, bathy_grid=bathy_grid)
    buoy = ctx.get("buoy") or {}
    wave = buoy.get("wave_m")
    n = int(hours * 60 / step_minutes)
    times = [(start + timedelta(minutes=step_minutes * i)) for i in range(n)]
    out_spots = []
    for c in positions:
        feat = {"sst_f": c["sst_f"], "front_nm": c["front_nm"],
                "front_grad_c_nm": c["front_grad_c_nm"],
                "structure_nm": c["structure_nm"], "structure_slope": c["structure_slope"],
                "month": start.month, "wave_m": wave}
        res = score(species, feat)
        why = explain(res, feat)
        detail = {
            "sst_f": c["sst_f"], "front_nm": c["front_nm"],
            "front_grad_f_nm": (None if c["front_grad_c_nm"] is None
                                else round(c["front_grad_c_nm"] * 1.8, 2)),
            "structure_nm": c["structure_nm"], "structure_slope": c["structure_slope"],
            "wave_m": wave,
            "wind_kt": buoy.get("wind_kt"), "wind_dir": buoy.get("wind_dir"),
            "terms": res.get("terms"), "unvalidated": True, "why": why,
            # the inshore keys the page reads, present and honest
            "current_speed": None, "current_dir": None, "water_temp_f": c["sst_f"],
            "light_phase": None, "moon_phase": None, "moon_illum": None,
            "next_tide": None, "season_note": None, "bait_note": None, "bait_signal": None,
        }
        out_spots.append({
            "key": c["key"], "label": c["label"], "lat": c["lat"], "lon": c["lon"],
            "private": c["private"], "kind": c["kind"], "notes": c["notes"],
            "best_stage": None, "prior": None, "depth_ft": c["depth_ft"], "bottom": None,
            "scores": [res["score"]] * n,
            "detail": [detail] * n,
        })
    return {
        "offshore": True,
        "unvalidated": True,
        "sst_date": ctx.get("sst_date"),
        "buoy": buoy or None,
        "fronts": ctx.get("fronts"),
        "structure": ctx.get("structure"),
        "times": [t.isoformat() for t in times],
        "spots": out_spots,
        "note": ("Offshore: surface temperature, temperature breaks, the shelf break and "
                 "the month, weighted by priors nobody has validated. Sea state from "
                 "buoy 44097 is fishability, not fish. SST is %s." % ctx.get("sst_date")),
    }
