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

What this file deliberately does not contain: weights, or a score. Those
come with the scorer, and they will be unvalidated priors until there are
offshore trips in the log -- `evaluate` has five trips today, none of them
offshore, and cannot tell a good offshore scorer from a bad one. The bands
are the part that can be checked against a document. The weights cannot,
and saying which is which is the point of keeping them apart.

Temperatures are Fahrenheit, converted from the cited Celsius and rounded to
the degree, because that is what the boat's gauge and the MUR product show.
A trapezoid is (zero, full, full, zero): outside the outer pair the term is
0, between the inner pair it is 1, and it ramps linearly between.
"""

from __future__ import annotations

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
             "Jul-Oct, 154 in August and 102 in September. Records are where people were "
             "and reported, not where fish were; they say when, not how many."),
}


@dataclass(frozen=True)
class PelagicProfile:
    key: str
    name: str
    sst: tuple[int, int, int, int]      # trapezoid, F: zero, full, full, zero
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
}
