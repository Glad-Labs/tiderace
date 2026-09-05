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
    "A10ALB": ("NOAA Fisheries, 2017. Final Amendment 10 (as A10), Section 6.2.1 North "
               "Atlantic albacore tuna, life history, p. 99: 'generally found in surface "
               "waters with temperatures between 15.6 and 19.4 C, although larger "
               "individuals have a wider depth and temperature range (13.5 to 25.2 C). "
               "Albacore may dive into cold water (9.5 C) for short periods'; EFH for "
               "juveniles and adults 'offshore, pelagic habitats ... from the outer edge of "
               "the U.S. EEZ through Georges Bank to pelagic habitats south of Cape Cod'."),
    "A10SWO": ("NOAA Fisheries, 2017. Final Amendment 10 (as A10), Section 6.4 swordfish, "
               "pp. 128-129: 'epipelagic to meso-pelagic, and are usually found in waters "
               "warmer than 13 C. Their optimum temperature range is believed to be 18 to "
               "22 C, but they will dive into 5 to 10 C waters at depths of up to 650 m "
               "(Nakamura 1985)'; 'Concentrations of adult swordfish seem to occur at ocean "
               "fronts between water masses associated with boundary currents, including the "
               "Gulf Stream (Arocha 1997; Govoni et al. 2003)'; 'another group moves from deep "
               "water westward toward the continental shelf in summer (Palko et al. 1981)'."),
    "A10BUM": ("NOAA Fisheries, 2017. Final Amendment 10 (as A10), Section 6.3 blue marlin, "
               "pp. 134-138: 'epipelagic and oceanic, generally found in blue water with a "
               "temperature range of 22 to 31 C'; 'Adults are found primarily in the tropics "
               "within the 24 C isotherm, and make seasonal movements related to changes in "
               "sea surface temperatures'."),
    "A10WHM": ("NOAA Fisheries, 2017. Final Amendment 10 (as A10), Section 6.3 white marlin, "
               "p. 142: 'It is believed that white marlin prefer slightly cooler temperatures "
               "than blue marlin. Spawning occurs in early summer, in subtropical, deep "
               "oceanic waters with high surface temperatures and salinities (20 to 29 C and "
               "over 35 ppt)'; 'Concentrations of white marlin ... from Cape Hatteras to Cape "
               "Cod are probably related to feeding rather than spawning (Mather et al. 1975)'."),
    "VAUDO2016": ("Vaudo, J.J. et al., 2016. Vertical movements of shortfin mako sharks "
                  "Isurus oxyrinchus in the western North Atlantic Ocean are strongly "
                  "influenced by temperature. Marine Ecology Progress Series 547: 163-175. "
                  "Eight sharks tagged off the northeastern United States and the Yucatan, "
                  "587 days: temperatures below 15 C 'creating a lower depth limit to most "
                  "diving'; 'sharks spent considerable time in waters ranging from 22 to "
                  "27 C'; overall 5.2 to 31.1 C. Abstract as published by Inter-Research."),
    "A10THR": ("NOAA Fisheries, 2017. Final Amendment 10 (as A10), Section 6.7 common "
               "thresher, p. 224: 'coastal and oceanic waters, but according to Strasburg "
               "(1958) it is more abundant near land'; the only temperature figure is a "
               "nursery: 'nearshore waters of North Carolina consisted of temperatures from "
               "18.2 to 20.9 C and at depths from 4.6 to 13.7 m (McCandless et al. 2002)'."),
    "A10POR": ("NOAA Fisheries, 2017. Final Amendment 10 (as A10), Section 6.7 porbeagle, "
               "p. 221: satellite-tagged sharks 'moved through temperatures ranging from 2 to "
               "26 C, they spent 76 percent of the time in water ranging from 8 to 16 C. In "
               "the spring and summer months, the sharks were epipelagic, swimming in the "
               "upper 200 m'."),
    "A10BSH": ("NOAA Fisheries, 2017. Final Amendment 10 (as A10), Section 6.7 blue shark, "
               "p. 216: 'a pelagic species that inhabits clear, deep, blue waters, usually in "
               "temperatures of 10 to 20 C, at depths greater than 180 m (Castro 1983)'."),
    "SAFMC2003W": ("South Atlantic Fishery Management Council, 2003. Dolphin Wahoo FMP, "
                   "Section 3.3.1, p. 97, wahoo: juveniles 'assumed' to inhabit 22-30 C water "
                   "with Sargassum, 'no data exist'; adults 'pelagic in nature and generally "
                   "associated with Sargassum (Manooch and Hogarth, 1983). Rathjen and Squire "
                   "(1960) recorded wahoo in similar temperature ranges of 22 to 28 C and from "
                   "May to October off the coast of North Carolina'."),
    "OBIS2": ("OBIS occurrence records within 60 nm of 40.9 N, 71.3 W, fetched 5 September "
              "2026. Albacore 1,481 records Jun-Dec, 148 in October and 129 in September. "
              "Swordfish 1,826, May-Dec, 117 in September and 108 in August. Blue shark 750, "
              "Apr-Nov, 82 in October and 81 in August. Mako 51, Jun-Oct, 19 in July. Thresher "
              "26, Jun-Nov, 4 each in July and August. Wahoo 26, Jul-Oct, 13 in September. "
              "White marlin 15, Jul-Sep, 9 in July. Blue marlin 2 and porbeagle 3: too few to "
              "place a season, so those two carry none."),
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
    # Which tier of claim the bands are. Matt, 5 September 2026: "we should
    # be able to make guesstimates based on general species knowledge and
    # bio, even if there's no info on them in the bay area ... don't invent
    # any number from nothing, but we are inventing forecasts based on fact."
    # So a band from another ocean's literature is allowed, and it is
    # labelled: "regional" means measured in this part of the Atlantic,
    # "general biology" means the species' published biology from wherever
    # it was studied. The card says which. Nothing is "this water" offshore.
    basis: str = "general biology"
    basis_claim: str = ""


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
        basis="regional",
        basis_claim="tagged off Cape Cod and on the Gulf of Maine grounds [GALUARDI2012, LAWSON2010]",
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
        basis="general biology",
        basis_claim="Straits of Florida adults and Atlantic-wide range statements [SAFMC2003]",
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
        basis="general biology",
        basis_claim="a species-wide range with no regional preference [A10YFT]",
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
        basis="general biology",
        basis_claim="'scientific knowledge of Atlantic bigeye tuna is limited' [A10BET]",
    ),
    "albacore": PelagicProfile(
        key="albacore", name="Albacore Tuna",
        sst=(f(13.5), f(15.6), f(19.4), f(25.2)),   # 56, 60, 67, 77
        sst_claim=("Full credit 60-67 F: 'generally found in surface waters with "
                   "temperatures between 15.6 and 19.4 C' [A10ALB]. Zero at 56 and 77 F, "
                   "the wider range of larger individuals, 13.5 to 25.2 C [A10ALB]. The "
                   "9.5 C dives are excursions, not habitat."),
        months=(6, 7, 8, 9, 10, 11, 12), peak_months=(9, 10),
        season_claim="1,481 records off Rhode Island, June to December, peak September-October [OBIS2].",
        features=("shelf_break",),
        features_claim=("EFH is 'offshore, pelagic habitats ... through Georges Bank to "
                        "pelagic habitats south of Cape Cod' [A10ALB]: seaward of the shelf."),
        fish_depth_note="Surface waters by the band's own wording [A10ALB]; deeper for larger fish.",
        sources=("A10ALB", "OBIS2"), basis="general biology",
        basis_claim="species-wide temperature statements, region unstated [A10ALB]",
    ),
    "wahoo": PelagicProfile(
        key="wahoo", name="Wahoo",
        sst=(f(22), f(22), f(28), f(30)),           # 72, 72, 82, 86
        sst_claim=("Full credit 72-82 F: adults recorded 'in similar temperature ranges of 22 "
                   "to 28 C and from May to October off the coast of North Carolina' "
                   "[SAFMC2003W]. Nothing cited below 22 C, so the cold side is a step. Zero "
                   "above 86 F, the 30 C top of the juvenile range the plan itself calls an "
                   "assumption [SAFMC2003W]."),
        months=(7, 8, 9, 10), peak_months=(9,),
        season_claim="26 records off Rhode Island, July to October, half of them in September [OBIS2].",
        features=("front", "floating_structure"),
        features_claim=("Adults 'generally associated with Sargassum' [SAFMC2003W], which "
                        "nothing here can see; the gear is set on weed lines and temperature "
                        "breaks [SAFMC2003 Section 3.4], and the break is measurable."),
        fish_depth_note="Pelagic; 'do not feed readily at the surface' [SAFMC2003W].",
        sources=("SAFMC2003W", "SAFMC2003", "OBIS2"), basis="general biology",
        basis_claim="North Carolina and Atlantic-wide statements [SAFMC2003W]",
    ),
    "swordfish": PelagicProfile(
        key="swordfish", name="Swordfish",
        sst=(f(13), f(18), f(22), f(30)),           # 55, 64, 72, 86
        sst_claim=("Full credit 64-72 F: 'optimum temperature range is believed to be 18 to "
                   "22 C' [A10SWO]. Zero at 55 F: 'usually found in waters warmer than 13 C' "
                   "[A10SWO]. The warm edge is DERIVED: the source gives no upper limit, only "
                   "spawning in surface water above 20-22 C in the tropics, so 30 C is taken "
                   "as the warmest surface water the species is described in, and said so."),
        months=(5, 6, 7, 8, 9, 10, 11, 12), peak_months=(8, 9, 10),
        season_claim="1,826 records off Rhode Island, May to December, peak August-October [OBIS2].",
        features=("front", "shelf_break"),
        features_claim=("'Concentrations of adult swordfish seem to occur at ocean fronts between "
                        "water masses' and a group 'moves from deep water westward toward the "
                        "continental shelf in summer' [A10SWO]."),
        fish_depth_note="Deep by day, 'coming to the surface at night (Palko et al. 1981)' [A10SWO].",
        sources=("A10SWO", "OBIS2"), basis="general biology",
        basis_claim="Atlantic-wide statements; the summer shelf movement is the western Atlantic [A10SWO]",
    ),
    "blue_marlin": PelagicProfile(
        key="blue_marlin", name="Blue Marlin",
        sst=(f(22), f(22), f(31), f(31)),           # 72, 72, 88, 88: a step
        sst_claim=("A step: 'generally found in blue water with a temperature range of 22 to "
                   "31 C' [A10BUM], a range with no preference inside it. 'Primarily in the "
                   "tropics within the 24 C isotherm' [A10BUM], which off Rhode Island is a "
                   "few weeks of late summer, if that."),
        months=(), peak_months=(),
        season_claim="Two records within 60 nm [OBIS2]: too few to place a season, so there is none.",
        features=(),
        features_claim="Nothing in the source ties adults to a front or the shelf; surface temperature is the whole claim [A10BUM].",
        fish_depth_note="Epipelagic [A10BUM].",
        sources=("A10BUM", "OBIS2"), basis="general biology",
        basis_claim="a tropical fish described Atlantic-wide [A10BUM]",
    ),
    "white_marlin": PelagicProfile(
        key="white_marlin", name="White Marlin",
        sst=(f(20), f(20), f(29), f(29)),           # 68, 68, 84, 84: a step
        sst_claim=("A step on the only figures given, 20 to 29 C, which are spawning water "
                   "[A10WHM]; 'white marlin prefer slightly cooler temperatures than blue "
                   "marlin' [A10WHM], and the band sits two degrees below blue marlin's."),
        months=(7, 8, 9), peak_months=(7,),
        season_claim="15 records off Rhode Island, July to September, nine of them in July [OBIS2].",
        features=(),
        features_claim=("Concentrations 'from Cape Hatteras to Cape Cod are probably related to "
                        "feeding' [A10WHM]; the source names no front or bottom for that."),
        fish_depth_note="Epipelagic, like the other billfish [A10WHM].",
        sources=("A10WHM", "OBIS2"), basis="general biology",
        basis_claim="spawning-water temperatures standing in for a preference [A10WHM]",
    ),
    "mako": PelagicProfile(
        key="mako", name="Shortfin Mako",
        sst=(f(15), f(22), f(27), f(31.1)),         # 59, 72, 81, 88
        sst_claim=("Full credit 72-81 F: tagged makos 'spent considerable time in waters "
                   "ranging from 22 to 27 C' [VAUDO2016]. Zero at 59 F: below 15 C was 'a "
                   "lower depth limit to most diving' [VAUDO2016]. Zero at 88 F, the warmest "
                   "water any tagged shark experienced, 31.1 C [VAUDO2016]."),
        months=(6, 7, 8, 9, 10), peak_months=(7,),
        season_claim="51 records off Rhode Island, June to October, 19 of them in July [OBIS2].",
        features=("shelf_break",),
        features_claim="EFH 'includes pelagic habitats seaward of the continental shelf break' [A10 s.6.7.4].",
        fish_depth_note="Diel divers to 866 m; most time in the warm surface layer [VAUDO2016].",
        sources=("VAUDO2016", "A10", "OBIS2"), basis="regional",
        basis_claim="tagged off the northeastern United States [VAUDO2016]",
    ),
    "thresher": PelagicProfile(
        key="thresher", name="Common Thresher",
        sst=None,
        sst_claim=("No band. The only temperature in the source is a North Carolina NURSERY, "
                   "18.2 to 20.9 C for young of the year [A10THR]; an adult band built from a "
                   "nursery would be a number from nothing. Surface temperature is reported "
                   "and not scored, like bigeye."),
        months=(6, 7, 8, 9, 10, 11), peak_months=(7, 8),
        season_claim="26 records off Rhode Island, June to November, July and August highest [OBIS2].",
        features=(),
        features_claim=("'More abundant near land' [A10THR] is not a front or a wall. This "
                        "profile scores on season and sea state alone, and the card says so."),
        fish_depth_note="Coastal and oceanic [A10THR].",
        sources=("A10THR", "OBIS2"), basis="general biology",
        basis_claim="a distribution statement and a nursery figure, nothing more [A10THR]",
    ),
    "porbeagle": PelagicProfile(
        key="porbeagle", name="Porbeagle",
        sst=(f(2), f(8), f(16), f(26)),             # 36, 46, 61, 79
        sst_claim=("Full credit 46-61 F: tagged porbeagles 'spent 76 percent of the time in "
                   "water ranging from 8 to 16 C' [A10POR]. Zero at 36 and 79 F, the 2 to "
                   "26 C they moved through [A10POR]. A cold-water shark; the band is above "
                   "this bay's summer water only in spring."),
        months=(), peak_months=(),
        season_claim="Three records within 60 nm [OBIS2]: too few to place a season, so there is none.",
        features=("shelf_break",),
        features_claim="Epipelagic in spring and summer 'in the upper 200 m' [A10POR], over the shelf edge.",
        fish_depth_note="Upper 200 m in spring and summer; 200-1,000 m in late autumn and winter [A10POR].",
        sources=("A10POR", "OBIS2"), basis="general biology",
        basis_claim="North Atlantic tagging, region unstated in the source [A10POR]",
    ),
    "blue_shark": PelagicProfile(
        key="blue_shark", name="Blue Shark",
        sst=(f(10), f(10), f(20), f(20)),           # 50, 50, 68, 68: a step
        sst_claim=("A step: 'usually in temperatures of 10 to 20 C' [A10BSH], a range with no "
                   "preference inside it and nothing cited outside it."),
        months=(4, 5, 6, 7, 8, 9, 10, 11), peak_months=(8, 10),
        season_claim="750 records off Rhode Island, April to November, August and October highest [OBIS2].",
        features=("shelf_break",),
        features_claim="'clear, deep, blue waters ... at depths greater than 180 m' [A10BSH]: the shelf edge and beyond.",
        fish_depth_note="Pelagic, deep water [A10BSH].",
        sources=("A10BSH", "OBIS2"), basis="general biology",
        basis_claim="a cosmopolitan species described Atlantic-wide [A10BSH]",
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
    "albacore":  {"sst": 0.45, "structure": 0.25, "season": 0.30},
    "wahoo":     {"sst": 0.40, "front": 0.35, "season": 0.25},
    "swordfish": {"sst": 0.35, "front": 0.25, "structure": 0.15, "season": 0.25},
    "blue_marlin": {"sst": 0.7, "season": 0.3},      # season is absent: no records
    "white_marlin": {"sst": 0.65, "season": 0.35},
    "mako":      {"sst": 0.45, "structure": 0.25, "season": 0.30},
    "thresher":  {"season": 1.0},
    "porbeagle": {"sst": 0.50, "structure": 0.25, "season": 0.25},   # season absent
    "blue_shark": {"sst": 0.45, "structure": 0.25, "season": 0.30},
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
        if not prof.months:
            absent["season"] = "too few records here to place a season"
        elif m is None:
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
    tier = ("general biology, not this water" if prof.basis == "general biology"
            else "regional literature")
    return "; ".join(bits) + ". Unvalidated: no offshore trips in the log yet; bands from %s." % tier


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
    # A fish whose literature ties it to neither a front nor the shelf break
    # (blue marlin, white marlin, thresher) still needs somewhere for its
    # water to be read. It gets both kinds of position as sample points, and
    # the kind says so: the fronts and walls are where the water was sampled,
    # not a claim that this fish uses them. Its scorer carries no front or
    # structure term, so the position's own feature never enters its score.
    sampled = not ({"front", "shelf_break"} & set(prof.features))
    if "front" in prof.features or sampled:
        for b in fr:
            out.append({"lat": b["lat"], "lon": b["lon"],
                        "kind": "water sample" if sampled else "front",
                        "notes": ("temperature break: %.2f °F/nm at %.1f °F on %s"
                                  % (b["grad_c_per_nm"] * 1.8, b["sst_c"] * 9 / 5 + 32,
                                     ctx["sst_date"]))
                                 + (" — a place the water was read, not a feature this "
                                    "fish is tied to" if sampled else ""),
                        "depth_ft": None, "private": False})
    if "shelf_break" in prof.features or sampled:
        for c in st:
            out.append({"lat": c["lat"], "lon": c["lon"],
                        "kind": "water sample" if sampled else "shelf break",
                        "notes": ("bottom falls %.0f m per km here, %.0f m deep — modelled "
                                  "bathymetry, the shelf break or a canyon wall"
                                  % (c["slope_m_per_km"], c["depth_m"]))
                                 + (" — a place the water was read, not a feature this "
                                    "fish is tied to" if sampled else ""),
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
    prof = PROFILES[species]
    return {
        "offshore": True,
        "unvalidated": True,
        "basis": prof.basis,
        "basis_claim": prof.basis_claim,
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
