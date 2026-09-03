"""Species response models.

Every species is a set of named response curves over physical features. The
scorer returns the total *and* the per-term contributions, for two reasons:

  1. You can read why a window scored well, and argue with it.
  2. The weights are data, not code. Once there is a catch log, these become
     the initial values of a fitted model instead of hand-tuned priors.

Nothing here is magic. Where a number has a published source it is cited on
the line that uses it. Where it does not, it is conventional Narragansett Bay
angling wisdom and should be read as a hypothesis, not a measurement.

A caution that matters more than any single number: the literature answers
"where is this fish and is it physiologically comfortable", which is NOT the
question this file asks. This file asks "will it bite". Those diverge -- a
tautog is alive and present all summer and still nearly uncatchable. So a
published occurrence range is an upper bound on the band, never a substitute
for it, and the two must not be silently swapped.

Sources, consulted 2026-08-29 except the depth work, consulted 2026-09-02:
  [BB-SB]  Buzzards Bay species account, striped bass (after Bigelow &
           Schroeder; Setzler et al. 1980; Coutant 1986; Rogers & Westin 1978;
           Hollis 1952).  buzzardsbay.org/.../striped-bass.pdf
  [BB-TOG] Buzzards Bay species account, tautog (after Olla et al. 1974, 1975a,
           1978; Cooper 1966; Arendt et al. 2001a; Pearce 1969; McCormack 1976).
           buzzardsbay.org/.../tautog.pdf
  [SCUP]   Steimle et al. 1999, EFH source doc NMFS-NE-149, via ASMFC scup
           species profile.
  [ASMFC-BSB] ASMFC black sea bass habitat fact sheet, January 2018.
           asmfc.org/.../BlackSeaBass.pdf
  [NEFSC-SF]  NOAA Fisheries summer flounder science pages, and Packer,
           Griesbach, Berrien, Zetlin, Johnson & Morse 1999, EFH source doc
           NMFS-NE-151 -- p.3 and Fig 8 are the RIDEM Narragansett Bay bottom
           trawl survey, 1990-1996.
  [BSB-AS] Slesinger et al. 2019, aerobic scope of black sea bass (PMC6564031).
  [EFH-BSB] Drohan, Manderson & Packer 2007, EFH source doc NMFS-NE-200
           (2nd ed.), p.10 and Fig 31 -- the same RIDEM survey.
  [EFH-TOG] Steimle & Shaheen 1999, EFH source doc NMFS-NE-118.
  [EFH-BLU] Fahay, Berrien, Johnson & Morse 1999, EFH source doc NMFS-NE-144.
  [ASMFC-SB] ASMFC 2009, Atlantic Coast Diadromous Fish Habitat, Habitat
           Management Series #9, ch. 9 (striped bass), habitat summary table.
  [LANGAN] Langan, McManus, Schonfeld, Truesdale & Collie 2019, Mar. Coast.
           Fish. 11(1):76-85, doi:10.1002/mcf2.10065.

Second cohort, consulted 2026-09-02, for the inshore and nearshore species:
  [EFH-WF]  Pereira, Goldberg, Ziskowski, Berrien, Morse & Johnson 1999, EFH
           source doc NMFS-NE-138 (winter flounder) -- Table 1 and the ADULTS
           section.
  [EFH-MACK] Studholme, Packer, Berrien, Johnson, Zetlin & Morse 1999, EFH
           source doc NMFS-NE-141 (Atlantic mackerel).
  [EFH-SQ]  Cargnelli, Griesbach, Packer & Weissberger 1999, EFH source doc
           NMFS-NE-146 (longfin inshore squid) -- Fig 8 is again the RIDEM
           Narragansett Bay trawl survey, 1990-1996, the same series the fluke
           and black sea bass depth bands come from.
  [EFH-DOG] Stehlik 2007, EFH source doc NMFS-NE-203 (spiny dogfish).
  [ASMFC-SCI] ASMFC 2017, Atlantic Sciaenid Habitats, Habitat Management
           Series #14 -- ch. 7 (weakfish), ch. 8 (northern kingfish). Same
           series as [ASMFC-SB], which is #9.
  [SEAROBIN] Roberts-Goodwin 1981, Biological and Fisheries Data on Striped
           Searobin, Prionotus evolans, NMFS Sandy Hook Laboratory.
  [FGOM]   Bigelow & Schroeder 1953, Fishes of the Gulf of Maine, Fishery
           Bulletin 74; species accounts read in the online edition. Already
           the ancestor of [BB-SB] and [BB-TOG]; here it is read directly, for
           weakfish and bonito.
  [RIDEM-AB] RI Division of Marine Fisheries, "Albie and Bonito" pilot project
           page, 2025: "Little tunny and Atlantic bonito are most prevalent in
           our region from late May to late September."
           dem.ri.gov/.../surveys/Albie_Bonito
  [ASGA-LT] Calabrese (Univ. of Massachusetts Dartmouth / American Saltwater
           Guides Association) 2023, Little Tunny literature review.
  [COLLIE] Collie, Wood & Jeffries 2008, Can. J. Fish. Aquat. Sci.
           65:1352-1365 -- the GSO trawl series. Its 25 species are 96% of
           every animal caught in the series, out of 130 recorded.
  [GSO]    the trawl series itself, read through `gso.build_trends()`. Annual
           means per species at Fox Island and Whale Rock, 1959-2024.

Depth, added 2026-09-02, is scored for **two** of the fourteen species. The
other twelve are not "no number was found" -- most of them are "the source
says depth is the wrong variable", which is a stronger answer and worth
keeping. For the original six:

  * **fluke** and **black_sea_bass** have a depth band. Both come from the same
    RIDEM Narragansett Bay trawl survey the temperature work already leans on,
    both are about adults, and both are stated as in-bay modal depths rather
    than a shelf-wide range.
  * **scup** has only an occurrence envelope -- 2-38 m, summer adults, shelf
    wide [SCUP Table 1]. In Narragansett Bay that is nearly every cell, and the
    header caution above forbids swapping an envelope for a band.
  * **tautog**: the envelope is <24 m from Cape Cod to New Jersey [EFH-TOG,
    after Chang 1990], and the same document says what actually decides where
    a tautog is -- they are "extremely local", and a few feet either way is the
    difference between success and failure. Structure, not depth.
  * **bluefish**: [EFH-BLU] reports that occurrence by bottom depth "closely
    mirror[s] the distribution of depths sampled" -- i.e. the survey measured
    its own effort. Adults were also rarely caught in the bay, and a bottom
    otter trawl is the wrong gear for a pelagic fish, the same reason gso.py
    has no striped bass in it.
  * **striped_bass**: [ASMFC-SB] tabulates depth for at-sea juveniles and
    adults as Tolerable "NIF", Optimal "NIF" -- No Information Found -- with
    only a reported range of 0.6-46 m. The coastwide habitat compendium looked
    and came back empty; this file is not going to do better by guessing.

None of the eight added below earns one either, and the reasons are worth
having in one place because four of them are findings rather than gaps:

  * **winter_flounder**: [EFH-WF Table 1] gives adults "Most 1-30 m inshore".
    That is 3-98 ft, which is nearly every cell in the bay. Envelope, not band
    -- the same call as scup.
  * **squid**: the closest thing to a band anywhere in this file's second
    cohort, and refused anyway. [EFH-SQ] reports Narragansett Bay recruits at
    3-37 m, "in spring and summer at 3-37 m with most at 30-34 m". A 98-112 ft
    mode in THIS bay, from the same RIDEM survey as fluke -- but three things
    are wrong with it. The document never says the mode is effort-controlled,
    where the fluke statement explicitly is. The mode sits at the extreme deep
    end of its own stated range, which is what an effort artifact looks like.
    And the same document records that squid "make diurnal vertical migrations
    up into the water column at night" -- so a daytime bottom trawl cannot see
    the fishery, which in this bay is a night fishery under lights in twenty
    feet of water off the Jamestown and Newport docks. Gear that cannot reach
    the fish cannot describe where they are.
  * **dogfish**: [EFH-DOG Table 4] gives three regional envelopes -- eastern
    Long Island Sound 25-40 m, Scotian Shelf 36-364 m, New Zealand 100-300 m
    -- and none of them is about this bay. The same document has them "near
    the bottom in daylight" and rising 125 m off it at night [after Sameoto et
    al. 1994], so even the depth they were caught at is a time of day.
  * **weakfish**: a finding, like tautog's. [FGOM] says few descend deeper
    than 5-6 fathoms in summer "but the precise level at which they are to be
    caught at any given locality is governed by their food at the time", and
    [ASMFC-SCI ch.7] says flatly that "specific habitat use or habitat
    preference in adult weakfish has not been reported" and that they are
    "pelagic, open water foragers". Depth is downstream of the bait.
  * **atlantic_mackerel**: [EFH-MACK] has fall adults "spread from 10-340 m"
    in the NEFSC bottom trawl. That is a shelf-wide envelope measured with a
    bottom trawl on a fish that is not on the bottom -- the [EFH-BLU] failure
    exactly, and the reason gso.py has no striped bass in it.
  * **striped_searobin**: [SEAROBIN] describes an inshore-to-mid-shelf range
    south of Cape Hatteras. Nothing about this bay at any depth.
  * **bonito** and **false_albacore**: surface pelagics. The most specific
    statement found is [ASGA-LT]: "Adult Little Tunny remain within the waters
    of the continental shelf". That is a range, not a depth.

A band also has to *discriminate* to be worth its weight. Measured over the
40x40 lattice heat.py scores across the bay (878 water cells, median 24 ft):

    fluke           sd 0.411    band, from a stated in-bay preference
    black_sea_bass  sd 0.427    band, from in-bay summer modal depths
    scup            sd 0.274    envelope only
    tautog          sd 0.170    envelope only
    striped_bass    sd 0.103    nothing published

For scale, the terms already here measure sd 0.263 (current), 0.182 (temp),
0.152 (season) and 0.000 (light, wind, pressure) on the same lattice. The two
envelopes sit closer to the constants than to the signals: a term worth 1.0
over ninety per cent of the bay does not inform the forecast, it dilutes the
terms that do.

--------------------------------------------------------------------------
The second cohort, added 2026-09-02: eight inshore and nearshore species.

Every temperature band now carries a `temp_claim`, for the same reason depth
carries a `depth_claim`: the bands are not equally strong and reading four
numbers off a tuple hides that. Compare

    winter_flounder   all four edges cited, three of them to named studies
    bonito            two edges derived from a season statement, two inert

and it is obvious the two should not be read the same way, but nothing in
`temp=(...)` says so. `temp_claim` does, and it travels -- `gso.thermal_season`
turns this exact tuple into the season term, so a weak band silently becomes a
weak season, and the caveat has to arrive with the number.

Three of the eight are as well sourced as anything already in this file:

  * **winter_flounder** [EFH-WF]. Occurrence floor 0.6C, preferred 12-15C
    (McCracken 1963), and 23C where "feeding ceased and the flounder buried
    themselves in the substrate" (Olla et al. 1969). That last one is the
    thing this file almost never gets: a published number about *feeding*
    rather than about presence. Note how close it runs -- the bay's warmest
    climatological week at Fox Island is 72.9F and the cutoff is 73F, so in an
    average year the band shuts by about a tenth of a degree and in a warm
    year it does not shut at all.
  * **squid** [EFH-SQ]. Uniquely, the numbers are from Narragansett Bay
    itself: recruits at 7-26C overall, most at 17-21C in summer and 15C in
    autumn. Four cited edges, in this water.
  * **atlantic_mackerel** [EFH-MACK]. Intolerant below 5-6C (Overholtz &
    Anderson 1976), laboratory preferred 7.3-15.8C (Olla et al. 1975, 1976),
    and 20C as "the highest temperature at which mackerel are commonly found"
    (Bigelow & Schroeder 1953).

Two are cited on one side and honest about the other -- the tautog pattern:

  * **dogfish** [EFH-DOG] has all four edges cited but from three different
    oceans, the plateau being the Long Island Sound spring/autumn range, which
    is the nearest comparable water rather than this one.
  * **weakfish** has a cited warm edge (28C estuarine egress, Wuenschel et al.
    2014 via [ASMFC-SCI]) and a cold half that nobody has measured. [FGOM]
    says so in as many words: "The lower limit to the temperature range
    preferred by the weakfish has not been determined." The cold pair here is
    derived from the [FGOM] Woods Hole season laid over the GSO climatology,
    and is the weakest pair in the second cohort.

Three rest on a derivation rather than a measurement, and say so:

  * **striped_searobin** [SEAROBIN] has a cold edge from Long Island Sound
    (Mann 1974: first fish at 10C in May, last at 8C in December) and NO warm
    edge anywhere in the literature. The warm pair is an inert spacer, the
    same device as the fluke depth band's deep side.
  * **bonito** and **false_albacore**. There is no thermal band for either
    species that applies to this water. What exists is a global tolerance
    envelope, a Gulf of Mexico *spawning* optimum of 24-28C [ASGA-LT, after
    Cruz-Castan et al. 2019] which is warmer than Narragansett Bay has ever
    been, and a review that says plainly that "little work has been done in
    the western Atlantic". So the band is built the other way round: [RIDEM-AB]
    says when these fish are here, and sixty-five years of GSO temperature say
    what the water does across that window -- 57F when it opens in late May,
    66F when it closes in late September. That is a real derivation from two
    cited sources and it is NOT a thermal preference. The consequence has to
    be stated: for these two, `temp` and `season` are not independent
    evidence, because `gso.thermal_season` builds the season out of this
    tuple. The temp weight is set low for exactly that reason. What the term
    still earns is a response to the water on the day rather than to the
    65-year normal, which is the whole point of `season_shift_days`.

    Worth knowing where the reference literature stands: [FGOM] describes
    false albacore in 1953 as strays, "picked up from time to time near Woods
    Hole, in July or August". The standard regional account predates the
    fishery. For bonito it is better -- a Provincetown pound-net series with
    the earliest catch in July and the latest on 4 October -- and that October
    record is why month 10 is in both month tuples when [RIDEM-AB] stops at
    late September.

Measured, as the depth work was: the temp term's standard deviation across the
52 climatological weeks at Fox Island. Every one of the eight discriminates as
well as the six already here (which run 0.410 to 0.483):

    striped_searobin 0.480    weakfish 0.469    bonito/false_albacore 0.446
    atlantic_mackerel 0.440   squid 0.430       dogfish 0.400
    winter_flounder 0.322

winter_flounder is last because its band never fully closes -- see the tenth
of a degree above -- which is a fact about a collapsing fishery in a warming
bay, not a defect in the band.

Everything not cited is a hand-set prior, and there are more of them here than
in the first six. Specifically: every `current` tuple except dogfish's shape
(where [EFH-DOG], after Zamon 2003, has tidal rips and jets concentrating prey
and dogfish following the schools -- the direction is cited, the magnitude is
not), every `weights` dict, every `wind_max_kt`, every `likes_falling_pressure`
and every `peak_months`. Four of the eight light curves do have a source, which
is four more than any of the original six: squid at night [EFH-SQ, after MAFMC
1996], mackerel and dogfish by day [EFH-MACK after Olla et al. 1975; EFH-DOG
after Sameoto et al. 1994], and weakfish dawn-to-dusk [ASMFC-SCI, after Mercer
1989] -- that last one against local angling practice, which fishes them at
night. Where the literature and the folklore disagree and neither has been
measured here, this file follows the literature and says that it did.

--------------------------------------------------------------------------
`NOT_PROFILED` is the other half of the work, and the more important half.

Eleven species were looked at and refused, and the refusal is recorded next to
the reason rather than showing up as an absence somebody fills in later by
feel. Three shapes of refusal:

  * **no band, only an envelope** -- northern_kingfish. [ASMFC-SCI ch.8] gives
    a 7.8-35.8C tolerance and a >31C avoidance limit this bay has never
    reached. Its one narrow statement, rarely seen below 20C, is explicitly
    about water south of Cape Hatteras.
  * **no source about this water at all** -- summer_triggerfish, cobia,
    spanish_mackerel. Warm-water strays that arrive on Gulf Stream eddies. The
    management documents are South Atlantic and Gulf of Mexico, and none of
    the three is among the 25 species that make up 96% of everything the GSO
    trawl has caught here since 1959 [COLLIE].
  * **effectively gone from this water** -- cod, pollock, monkfish. Same
    evidence, read the other way: the [COLLIE] analysis of this series is the
    documented shift away from exactly this group, "from benthic to pelagic
    species" since 1980, and the boreal demersals it names as declining are
    winter flounder and silver hake, both of which ARE in the 25. Cod, pollock
    and goosefish are not. A profile for them would forecast a fishery that
    the longest continuous record of this bay does not contain. This is not
    the same claim as "they are absent" -- the 25 leave 4% unaccounted, and a
    codfish still turns up. It is the claim that the app should not tell you
    to go looking.

Note what this does NOT change: all three stay loggable. If a cod comes over
the rail the log takes it, which is the entire point of the three tiers in
species.py.

--------------------------------------------------------------------------
The fourteen offshore species are deliberately absent, and the reason is
structural rather than a shortage of reading.

All 21 entries in `spots.SPOTS` are inside Narragansett Bay -- latitude 41.36
to 41.72 -- and every term in this scorer that carries any signal is built on
bay tidal current: `current` is a CO-OPS current-station prediction, the
`spring_tide` and `tide_stage` modifiers are tidal, and heat.py measures
`current` as the term that carries the whole map. Give bluefin tuna a profile
here and the app will score bluefin tuna at Whale Rock, on the strength of an
ebb rip forty miles from the nearest fish.

Offshore needs a different scorer keyed on different inputs -- SST break
gradient, chlorophyll, canyon structure -- and prospect.py already fetches all
three (`offshore.sst_grid`, `offshore.breaks`, `offshore.chlorophyll`). That is
where a tuna model goes. Not here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


# ------------------------------------------------------------- response curves

# Past this the current prediction is not about this water. stations.FAR_NM
# is 3.0 and is what `resolve` already uses to call a binding poor; the same
# number decides it here so the interface and the scorer agree about when a
# reading has stopped being one.
_FAR_BINDING_NM = 3.0


def _clip(v, default: float = 0.0) -> float:
    """A signal into 0..1. Missing is 0, not a middling 0.5: nobody reporting
    bait is not the same as somebody reporting some."""
    if v is None:
        return default
    try:
        return max(0.0, min(1.0, float(v)))
    except (TypeError, ValueError):
        return default


def trapezoid(x: float, lo_out: float, lo_in: float, hi_in: float, hi_out: float) -> float:
    """0 outside [lo_out, hi_out], 1 inside [lo_in, hi_in], linear ramps between."""
    if x <= lo_out or x >= hi_out:
        return 0.0
    if lo_in <= x <= hi_in:
        return 1.0
    if x < lo_in:
        return (x - lo_out) / (lo_in - lo_out)
    return (hi_out - x) / (hi_out - hi_in)


def gaussian(x: float, mu: float, sigma: float) -> float:
    return math.exp(-((x - mu) ** 2) / (2 * sigma * sigma))


def peaked(x: float, opt: float, sigma_lo: float, sigma_hi: float,
           hard_max: float) -> float:
    """Asymmetric bell: rewards being near the optimum instead of merely
    inside a wide acceptable band. A flat-topped trapezoid cannot tell
    0.6 kt from 1.4 kt, and that difference is the whole forecast."""
    if x >= hard_max:
        return 0.0
    sigma = sigma_lo if x < opt else sigma_hi
    val = gaussian(x, opt, sigma)
    # Taper to exactly zero at the hard limit so nothing survives a rip.
    if x > opt:
        val *= max(0.0, min(1.0, (hard_max - x) / (hard_max - opt)))
    return val


@dataclass
class Profile:
    key: str
    name: str
    months: tuple[int, ...]          # months present in the bay
    peak_months: tuple[int, ...]     # months of peak abundance
    temp: tuple[float, float, float, float]      # trapezoid on water temp F
    current: tuple[float, float, float, float]   # (optimum, sigma_lo, sigma_hi, hard_max) kt
    light: dict[str, float]          # multiplier by light phase
    weights: dict[str, float]        # term weights, should sum to ~1
    # What the four numbers in `temp` actually rest on, in one sentence. Unlike
    # `depth`, temperature is never optional -- every species gets a band -- so
    # the tuple alone cannot distinguish four cited edges from two cited edges
    # and two derived ones. This can, and it travels: gso.thermal_season turns
    # `temp` into the season term, so a weak band becomes a weak season
    # somewhere the reader is no longer looking at this file.
    temp_claim: str = ""
    wind_max_kt: float = 25.0
    likes_falling_pressure: bool = True
    notes: str = ""
    # Trapezoid on depth in FEET, or None where no publication supports one.
    # None is not a placeholder to be filled in later by feel -- see the depth
    # section of the module docstring for why four of six carry it.
    depth: tuple[float, float, float, float] | None = None
    # One sentence saying what the band above actually claims, carried with it
    # so a reader who meets the number somewhere else -- a bump in
    # structure.py, a cell in heat.py -- gets the caveat at the same time as
    # the number instead of having to come back here for it.
    depth_claim: str = ""
    # Substrate preference: {"sand": 1.0, "mud": 0.5, ...} or None where no
    # publication supports one. Matched as a substring, because ENC records
    # mixtures -- "sand,shells" and "mud,shells" are both real values in the
    # bay. Absent bottom scores 0.6 (unknown), a bottom present but unlisted
    # scores 0.15 (charted, and not what this fish uses).
    bottom: dict[str, float] | None = None
    bottom_claim: str = ""


PROFILES: dict[str, Profile] = {
    "striped_bass": Profile(
        key="striped_bass", name="Striped Bass",
        months=(4, 5, 6, 7, 8, 9, 10, 11), peak_months=(5, 6, 9, 10),
        # 43F = 6C and 70F = 21C are the bounds of the "active" range for adult
        # bass; 78F ~ 26C is where feeding measurably declines in seawater. All
        # three from [BB-SB]. Only the 55F plateau start is still hand-set.
        temp=(43, 55, 70, 78),
        current=(1.40, 0.62, 1.15, 4.0),
        # No depth band: [ASMFC-SB] records optimal depth as "NIF" -- No
        # Information Found -- for at-sea juveniles and adults alike.
        temp_claim=("three cited edges from [BB-SB] -- 6C and 21C bound the "
                    "active range for adults, 26C is where feeding measurably "
                    "declines -- and a hand-set 55F plateau start"),
        light={"golden": 1.0, "twilight": 0.96, "night": 0.88, "day": 0.40},
        weights={"season": 0.20, "temp": 0.15, "current": 0.28,
                 "light": 0.22, "wind": 0.07, "pressure": 0.08},
        wind_max_kt=25,
        notes="Moving water and low light. In August heat the day bite dies; "
              "night and the first hour of grey light carry the month.",
    ),
    "bluefish": Profile(
        key="bluefish", name="Bluefish",
        months=(6, 7, 8, 9, 10), peak_months=(7, 8, 9),
        # Checked, unchanged: 58F lower matches the 14C tolerance floor and the
        # 12-16C (54-60F) spring arrival [EFH-BLU]. The warm half is unsourced
        # -- no published upper feeding limit was found.
        #
        # The tag was written "[bluefish EFH / ASMFC]" until 2026-09-02, which
        # is a description of a source rather than a reference to one: it
        # named no document this file declares, so nothing could be looked up
        # and nothing could check it. The EFH source document it means is the
        # one already declared as [EFH-BLU] for the depth finding two lines
        # down. Found by the temperature-band citation test, which is the
        # first thing to hold `temp` to the standard `depth` was already held
        # to.
        temp=(58, 64, 78, 84),
        current=(1.30, 0.75, 1.40, 4.5),
        # No depth band: [EFH-BLU] found occurrence by depth "closely
        # mirror[ing] the distribution of depths sampled" -- effort, not fish.
        temp_claim=("cold half cited to the 14C tolerance floor and the "
                    "12-16C spring arrival; the warm half is unsourced -- no "
                    "published upper feeding limit was found"),
        light={"golden": 1.0, "twilight": 0.88, "day": 0.74, "night": 0.60},
        weights={"season": 0.18, "temp": 0.14, "current": 0.24,
                 "light": 0.18, "wind": 0.10, "pressure": 0.16},
        wind_max_kt=28,
        notes="Far less fussy than bass. Follows bait; a blitz beats any forecast.",
    ),
    "fluke": Profile(
        key="fluke", name="Fluke (Summer Flounder)",
        months=(5, 6, 7, 8, 9), peak_months=(6, 7, 8),
        # Checked, unchanged: 80F upper matches the 27C top of the inshore
        # occurrence range [NEFSC-SF]. The 56F lower is deliberately warmer
        # than the 9C (48F) occurrence floor -- they are present in cold water,
        # they just are not a fishery yet.
        temp=(56, 62, 74, 80),
        current=(1.00, 0.42, 0.52, 2.6),   # drift speed -- too fast is as bad as slack
        # The best-supported depth statement found for any species here, and
        # the only one that uses the word "preference": adults in THIS bay,
        # 1990-1996 RIDEM trawl, abundance compared against the survey's own
        # station distribution so it is effort-controlled. "Abundance in
        # relation to bottom depth shows a preference for depths greater than
        # 12.2-15.2 m (40-50 ft) and that few were captured in depths less
        # than 9.1 m (30 ft)" [NEFSC-SF, Fig 8]. So 30 -> 50 is the cited ramp,
        # taking the deep end of the stated 40-50 ft threshold.
        #
        # The upper pair is DELIBERATELY INERT. Nothing published bounds adult
        # fluke on the deep side inside the bay -- the offshore 150 m figure is
        # about where they winter, not where they are caught in August -- and
        # the bay bottoms out near 163 ft on the lattice, so 300/400 never
        # bites. It is a spacer, not a claim, and must not be read as one.
        #
        # Read this band with [LANGAN] next to it, because it complicates what
        # "better" means. Working the same bay in 2016-17 they found females
        # more prevalent shallow (<=15 m, about 49 ft) and males deeper, at
        # sizes above 30 cm. So the deep water this band rewards holds MORE
        # fluke and SMALLER ones, and the shallow water it penalises is where
        # the doormats are. The two findings do not contradict -- one is about
        # abundance, the other about who is there -- but a keeper-hunting
        # angler should know the term is tuned on the first and not the
        # second. This is the presence-vs-catchability caution at the top of
        # the file, arriving through a second door.
        depth=(30, 50, 300, 400),
        depth_claim=("a lower bound only: few adults were caught below 30 ft "
                     "and they are preferred above 40-50 ft, but nothing "
                     "published bounds them on the deep side inside the bay, "
                     "so a deep reading here is the absence of a limit rather "
                     "than a recommendation"),
        temp_claim=("warm edge is the 27C top of the inshore occurrence "
                    "range [NEFSC-SF]; the cold pair is hand-set, "
                    "deliberately warmer than the published 9C floor, "
                    "because presence in cold water is not yet a fishery"),
        light={"day": 1.0, "golden": 0.90, "twilight": 0.58, "night": 0.30},
        weights={"season": 0.18, "temp": 0.13, "current": 0.31, "depth": 0.10,
                 "light": 0.13, "wind": 0.10, "pressure": 0.05},
        wind_max_kt=20,
        likes_falling_pressure=False,
        notes="Drift speed is the whole game: 0.5-1.5 kt over sand and edges. "
              "Wind against tide ruins the drift even when the numbers look fine.",
    ),
    "black_sea_bass": Profile(
        key="black_sea_bass", name="Black Sea Bass",
        months=(6, 7, 8, 9, 10, 11), peak_months=(7, 8, 9),
        # Aerobic scope peaks at 24.4C = 76F [BSB-AS]; inshore summer water
        # reaches 27C = 81F [ASMFC-BSB]. Lower bound stays angling knowledge --
        # the 7C migration threshold is presence, not catchability.
        temp=(55, 60, 76, 81),
        current=(0.90, 0.48, 0.68, 3.0),
        # Adults in this bay, same 1990-1996 RIDEM survey: "found mostly at a
        # depth of 100 ft (30 m) in the spring, 20-80 ft (6-24 m) in the
        # summer, and from 30-50 ft (9-15 m) and from 100-110 ft (30-34 m) in
        # the fall" [EFH-BSB, Fig 31]. Summer is the plateau because summer is
        # the fishery -- peak_months here are 7,8,9. The 120 ft cutoff is a
        # second, independent source: [ASMFC-BSB] puts the whole inshore
        # summer population in "waters at depths of less than 120 ft".
        #
        # 10 ft is the one hand-set number in this tuple, a short ramp under
        # the cited 20 ft rather than a cliff. Two things this band does not
        # capture, both real: the fall distribution is BIMODAL (30-50 and
        # 100-110 ft) and one trapezoid cannot hold that, and the survey is a
        # bottom otter trawl, which cannot be towed across the wrecks and rock
        # piles these fish actually sit on. So it samples sea bass that
        # strayed onto open bottom. That biases abundance down, not depth in
        # any obvious direction, but it is why this band is weaker evidence
        # than the fluke one above despite reading the same way.
        depth=(10, 20, 80, 120),
        depth_claim=("summer adults in this bay were found mostly at 20-80 ft, "
                     "and the inshore summer population within 120 ft; the "
                     "fall distribution is bimodal and this band does not "
                     "hold the deep 100-110 ft mode"),
        temp_claim=("plateau top is the 24.4C aerobic scope peak [BSB-AS] "
                    "and the warm edge the 27C inshore summer maximum "
                    "[ASMFC-BSB]; the cold half is angling knowledge, since "
                    "the 7C migration threshold is presence not catchability"),
        light={"day": 1.0, "golden": 0.90, "twilight": 0.60, "night": 0.36},
        weights={"season": 0.18, "temp": 0.14, "current": 0.24, "depth": 0.10,
                 "light": 0.14, "wind": 0.12, "pressure": 0.08},
        wind_max_kt=20,
        likes_falling_pressure=False,
        notes="Structure fish. Enough current to hold them on the piece, "
              "not so much you cannot stay on it.",
    ),
    "scup": Profile(
        key="scup", name="Scup (Porgy)",
        months=(5, 6, 7, 8, 9, 10), peak_months=(6, 7, 8, 9),
        # Adults are most commonly caught at 17-27C = 63-81F [SCUP]; the old
        # plateau stopped at 76F and was clipping the warm half of their range.
        # 56F lower is angling knowledge, not the 8-9C departure threshold.
        temp=(56, 63, 79, 84),
        current=(0.90, 0.55, 0.90, 3.2),
        # No depth band: [SCUP] gives summer adults ~2-38 m, an occurrence
        # envelope covering nearly the whole bay. An envelope is not a band.
        temp_claim=("plateau is the 17-27C range adults are most commonly "
                    "caught in [SCUP]; the 56F cold edge is angling knowledge, "
                    "not the published 8-9C departure threshold"),
        light={"day": 1.0, "golden": 0.85, "twilight": 0.50, "night": 0.28},
        weights={"season": 0.18, "temp": 0.14, "current": 0.24,
                 "light": 0.16, "wind": 0.18, "pressure": 0.10},
        wind_max_kt=18,
        likes_falling_pressure=False,
        notes="The reliable one. If the day is fishable at all, scup are catchable.",
    ),
    "tautog": Profile(
        key="tautog", name="Tautog (Blackfish)",
        months=(4, 5, 6, 7, 8, 9, 10, 11, 12), peak_months=(10, 11),
        # Cold half is well supported: adults off RI at 7.5C (46F) were torpid
        # with empty guts, and fish are active again by 10C (50F) [BB-TOG].
        # The WARM half is not. Upper lethal is 31-33C (88-91F), far above the
        # 68F cutoff here; the literature only says feeding is "depressed at
        # elevated temperatures" without giving a number. So 58/68 is angling
        # knowledge doing real work, and it is the single least defensible pair
        # in this file -- see the presence-vs-catchability caution up top.
        temp=(38, 47, 58, 68),
        current=(0.60, 0.38, 0.50, 2.4),
        # No depth band, and this one is a finding rather than a gap:
        # [EFH-TOG] says tautog are "extremely local" and that a few feet
        # either way decides the day. The variable is structure, not depth.
        temp_claim=("cold half well cited -- torpid at 7.5C, active again by "
                    "10C [BB-TOG]. The warm half is hand-set: upper lethal is "
                    "31-33C, far above the 68F used here, and the literature "
                    "says only that feeding is depressed at elevated "
                    "temperatures without giving a number. The least "
                    "defensible pair in this file"),
        light={"day": 1.0, "golden": 0.80, "twilight": 0.40, "night": 0.18},
        weights={"season": 0.26, "temp": 0.20, "current": 0.20,
                 "light": 0.14, "wind": 0.14, "pressure": 0.06},
        wind_max_kt=18,
        likes_falling_pressure=False,
        notes="Cold water, hard structure, anchored. Resident most of the year, "
              "so the temperature curve — not the calendar — is what shuts them "
              "off in summer. The October-November window is the one that matters.",
    ),
    # ---------------------------------------------------------------------
    # The second cohort, 2026-09-02. Inshore and nearshore only -- see the
    # closing section of the module docstring for why the offshore fourteen
    # are not here and what they would need instead.
    #
    # `weights` in all eight are hand-set priors exactly like the six above.
    # They are not fitted, they have not been validated against anything, and
    # `evaluate` will say how far off a catch log is from being able to fit
    # them. Read them as "these are the terms I think matter, in this rough
    # order", not as measurements.
    # ---------------------------------------------------------------------
    "bonito": Profile(
        key="bonito", name="Atlantic Bonito",
        # [RIDEM-AB]: "Little tunny and Atlantic bonito are most prevalent in
        # our region from late May to late September." Month 10 is not from
        # that sentence -- it is [FGOM], whose Provincetown pound-net series
        # has the latest bonito on 4 October, and Rhode Island sits south of
        # Provincetown. May is left out rather than claimed whole, because
        # "late May" is half a month and this tuple cannot hold half a month;
        # the thermal season, which is what actually runs when GSO data is
        # loaded, does hold it and opens the ramp in week 21.
        months=(6, 7, 8, 9, 10), peak_months=(8, 9),
        # DERIVED, NOT MEASURED, and the distinction is the whole point. No
        # thermal band exists for this species in this water. So: [RIDEM-AB]
        # says when they are here, and sixty-five years of GSO weekly
        # temperature say what the bay does across that window -- 56.9F in
        # week 21 (late May, window opens) and 65.7F in week 39 (late
        # September, window closes on the cooling limb). Rounded to 57 and 66.
        #
        # The warm pair is INERT, the same device as the fluke depth band's
        # deep side. Nothing published bounds these fish on the warm side and
        # the bay cannot approach 95F anyway: the warmest climatological week
        # at Fox Island is 72.9F and the highest weekly p90 in the whole
        # 1959-2024 record is 76.3F. It is a spacer, not a claim.
        temp=(57, 66, 95, 100),
        temp_claim=("derived, not measured: the cold pair is the GSO water "
                    "temperature at the two ends of the season window "
                    "[RIDEM-AB] states for this region, and the warm pair is "
                    "an inert spacer 19F above anything the 65-year record "
                    "holds. Because gso.thermal_season builds the season term "
                    "out of this tuple, temp and season are NOT independent "
                    "evidence for this fish -- which is why the temp weight "
                    "is the lowest in the file"),
        # Hand-set. Nothing published gives a current preference for bonito.
        # This is the local pattern -- rips and current lines at the mouth of
        # the bay and off the breachways -- written as a hypothesis.
        current=(1.30, 0.70, 1.20, 4.0),
        # No depth band: surface pelagic, and see the docstring.
        # Hand-set. Sight-feeders working bait on the surface; the bite is a
        # daylight one, unlike anything else in this file except the bottom
        # fish, and for the opposite reason.
        light={"day": 1.0, "golden": 0.95, "twilight": 0.55, "night": 0.15},
        weights={"season": 0.30, "temp": 0.06, "current": 0.26,
                 "light": 0.18, "wind": 0.14, "pressure": 0.06},
        wind_max_kt=18,
        likes_falling_pressure=False,
        notes="Fast fish on moving water at the mouth of the bay. Season "
              "carries this forecast and temperature deliberately does not — "
              "the band was derived from the season, so weighting it would "
              "count one fact twice.",
    ),
    "false_albacore": Profile(
        key="false_albacore", name="False Albacore",
        # Same [RIDEM-AB] sentence -- it names both species together, so the
        # season evidence for these two is literally one sentence covering
        # both. Only peak_months differ, and those are hand-set: bonito show
        # first, albies run late and are the September-October fish.
        months=(6, 7, 8, 9, 10), peak_months=(9, 10),
        # Identical derivation to bonito, from the identical sentence. See
        # that profile for the full reasoning and the module docstring for why
        # the published numbers -- a Gulf of Mexico spawning optimum of 24-28C
        # [ASGA-LT, after Cruz-Castan et al. 2019] -- do not transfer: that is
        # warmer than Narragansett Bay has ever been.
        temp=(57, 66, 95, 100),
        temp_claim=("derived exactly as bonito's is, from the same [RIDEM-AB] "
                    "sentence, which names the two species together. Not a "
                    "thermal preference; not independent of the season term"),
        # Hand-set, and slightly tighter than bonito: albies are the fish you
        # find on a hard rip line. Hypothesis, not measurement.
        current=(1.35, 0.65, 1.10, 4.0),
        # No depth band. The most specific published statement is [ASGA-LT],
        # "Adult Little Tunny remain within the waters of the continental
        # shelf" -- a range, not a depth.
        light={"day": 1.0, "golden": 0.95, "twilight": 0.50, "night": 0.12},
        weights={"season": 0.30, "temp": 0.06, "current": 0.26,
                 "light": 0.18, "wind": 0.14, "pressure": 0.06},
        wind_max_kt=18,
        likes_falling_pressure=False,
        notes="The fall run. [FGOM] called them strays here in 1953, which is "
              "worth knowing: the standard regional account is older than the "
              "fishery, so the literature is thinner for this fish than for "
              "anything else the model scores.",
    ),
    "weakfish": Profile(
        key="weakfish", name="Weakfish",
        # [FGOM], Woods Hole: "caught from May (some years as early as April,
        # other years not until June) until the middle of October". That is
        # the nearest long series to this bay and it is what the tuple holds.
        # peak_months are hand-set local knowledge, as everywhere here.
        months=(5, 6, 7, 8, 9, 10), peak_months=(6, 7, 8),
        # WARM HALF CITED, COLD HALF NOT, and the source says so itself.
        # 82F is 28C: "Temperatures above 28C but below 23C resulted in the
        # egress of adult weakfish from coastal estuaries (Wuenschel et al.
        # 2014)" [ASMFC-SCI ch.7]. 86F is a short ramp above it rather than a
        # cliff -- hand-set, the same device as black sea bass's 10 ft.
        #
        # The 23C half of that same sentence is deliberately NOT used. It is
        # an autumn egress threshold from a New Jersey estuary whose summer
        # water runs 25-28C; this bay averages 72.9F (22.7C) in its warmest
        # week, so transplanting it would put weakfish below their departure
        # temperature almost the entire time they are demonstrably here.
        # A range-edge extrapolation is not a measurement.
        #
        # So the cold pair is derived instead, the same way bonito's is: the
        # [FGOM] Woods Hole window is "from May ... until the middle of
        # October", and the GSO climatology says the bay is 52.7F in week 19
        # (early May) and 61.9F in week 41 (early-to-mid October). Rounded to
        # 53 and 62. [FGOM] is explicit that nothing better exists -- "The
        # lower limit to the temperature range preferred by the weakfish has
        # not been determined."
        temp=(53, 62, 82, 86),
        temp_claim=("warm edge cited to a 28C estuarine egress threshold "
                    "[ASMFC-SCI, after Wuenschel et al. 2014]; the cold pair "
                    "is derived from the [FGOM] Woods Hole season over the "
                    "GSO climatology, because [FGOM] states outright that the "
                    "lower limit has never been determined. The weakest pair "
                    "in the second cohort"),
        # Hand-set. [ASMFC-SCI] does place adults in "the main channel of
        # bays, sounds", which is moving water, but gives no speed.
        current=(0.85, 0.45, 0.75, 3.0),
        # No depth band, and this is a finding: [FGOM] says the level they are
        # caught at "is governed by their food at the time", and [ASMFC-SCI]
        # that "specific habitat use or habitat preference in adult weakfish
        # has not been reported". Same shape as the tautog answer.
        #
        # THIS LIGHT CURVE FOLLOWS THE LITERATURE AGAINST THE FOLKLORE.
        # [ASMFC-SCI, after Mercer 1989]: "Adult weakfish feed primarily
        # between dawn and dusk." Every angler in this bay fishes them after
        # dark on a moving tide. Nobody has measured which is right here, so
        # the file takes the published statement and says that it did -- and
        # night is kept well above zero rather than following the citation off
        # a cliff, because one 1989 review is not enough to overturn what the
        # boats actually do.
        light={"golden": 1.0, "twilight": 0.95, "day": 0.80, "night": 0.55},
        weights={"season": 0.22, "temp": 0.14, "current": 0.24,
                 "light": 0.18, "wind": 0.14, "pressure": 0.08},
        wind_max_kt=20,
        notes="[GSO] disagrees with the usual story of a collapse: at Whale "
              "Rock the 2020-2024 mean is 2.20 against a 0.70 long-term mean, "
              "the 91st percentile of 65 years. Up the bay at Fox Island it "
              "is 0.69 against 0.91. They are back, at the mouth.",
    ),
    "winter_flounder": Profile(
        key="winter_flounder", name="Winter Flounder",
        # [EFH-WF Table 1] has adults migrating "Inshore in fall; offshore in
        # spring". The summer months are left out because the band below
        # closes there on its own -- which is the thermal season doing the
        # work the calendar used to, exactly as it did for tautog.
        months=(1, 2, 3, 4, 5, 6, 10, 11, 12), peak_months=(4, 5),
        # THE BEST-SOURCED TEMPERATURE BAND IN THIS FILE. All four edges cited
        # and three of them to named studies, out of [EFH-WF]:
        #   33F  = 0.6C, the bottom of the adult occurrence range [Table 1]
        #   54F  = 12C   |  "adults have a preferred temperature range of
        #   59F  = 15C   |  12-15C" (McCracken 1963); Reynolds (1977) put the
        #                   laboratory preferred habitat temperature at 13.5C,
        #                   inside it
        #   73F  = 23C, rounded down from 73.4F: Olla et al. (1969) found
        #                active feeding up to 22.2C "but at 23C feeding ceased
        #                and the flounder buried themselves in the substrate"
        #
        # That last number is the rarest thing in this file -- a published
        # threshold about FEEDING rather than about presence, which is the
        # question the scorer actually asks. Note how narrowly it clears: the
        # warmest climatological week at Fox Island is 72.9F, so the band shuts
        # by a tenth of a degree in an average year and not at all in a warm
        # one. That is the finding, not a defect.
        temp=(33, 54, 59, 73),
        temp_claim=("all four edges cited to [EFH-WF]: 0.6C occurrence floor, "
                    "12-15C preferred (McCracken 1963), and 23C where feeding "
                    "ceased and the fish buried themselves (Olla et al. 1969) "
                    "-- the only feeding threshold, rather than a presence "
                    "range, anywhere in this file"),
        # Hand-set. Anchored over mud on a light tide; this is the least
        # current-driven fish in the file.
        current=(0.45, 0.30, 0.40, 1.8),
        # No depth band: [EFH-WF Table 1] gives adults "Most 1-30 m inshore",
        # which is 3-98 ft and therefore nearly the whole bay. Envelope.
        #
        # Hand-set, and against one line of the source: [EFH-WF] notes that
        # Casterlin and Reynolds (1982) found yearlings "more active at night"
        # in the laboratory. That is yearlings, in a tank, and the fishery is
        # a daylight one, so the curve follows the fishery and the
        # disagreement is recorded rather than hidden.
        light={"day": 1.0, "golden": 0.85, "twilight": 0.50, "night": 0.25},
        weights={"season": 0.24, "temp": 0.22, "current": 0.16,
                 "light": 0.14, "wind": 0.16, "pressure": 0.08},
        wind_max_kt=18,
        likes_falling_pressure=False,
        notes="Read the forecast against the stock. [GSO] at Fox Island: a "
              "2020-2024 mean of 0.67 against a 65-year mean of 72.03, the "
              "5th percentile — a ~99% collapse, and [COLLIE] names this "
              "species as one of the two boreal demersals whose decline "
              "defines the bay's shift. A good score here means good "
              "conditions for a fish that has mostly gone.",
    ),
    "atlantic_mackerel": Profile(
        key="atlantic_mackerel", name="Atlantic Mackerel",
        # Not a calendar guess: these are the months the band below is open
        # over the GSO climatology, which is April-June and October-December.
        # It matches the local pattern -- tinkers in spring, a thinner showing
        # late in the year -- without either being asserted.
        months=(4, 5, 6, 10, 11, 12), peak_months=(4, 5),
        # All four edges cited, out of [EFH-MACK]:
        #   41F = 5C   "mackerel are intolerant of temperatures < 5-6C or
        #               > 15-16C" (Overholtz and Anderson 1976)
        #   45F = 7.3C |  the laboratory preferred range, 7.3-15.8C, at which
        #   60F = 15.8C|  swimming speed is lowest (Olla et al. 1975, 1976);
        #               outside it speeds rise, "reflecting thermal avoidance"
        #   68F = 20C  "the highest temperature at which mackerel are commonly
        #               found" (Bigelow and Schroeder 1953)
        temp=(41, 45, 60, 68),
        temp_claim=("four cited edges from [EFH-MACK]: 5C intolerance floor "
                    "(Overholtz & Anderson 1976), the 7.3-15.8C laboratory "
                    "preferred range where swimming speed is lowest (Olla et "
                    "al. 1975, 1976), and 20C as the highest temperature they "
                    "are commonly found in (Bigelow & Schroeder 1953)"),
        # Hand-set. Jigged on the drift; they are obligate swimmers with no
        # swimbladder, so slack water is not their problem, holding a jig in a
        # hard rip is.
        current=(1.00, 0.55, 0.90, 3.5),
        # No depth band: the NEFSC figure is 10-340 m from a bottom trawl, on
        # a fish that is not on the bottom. See the docstring.
        #
        # Cited, unusually for a light curve here: [EFH-MACK] has adults
        # "swimming faster during the day than at night" and schooling with
        # "diurnal changes in cohesiveness" (Olla et al. 1975, 1976). An
        # active, tight daytime school is the one you can catch.
        light={"day": 1.0, "golden": 0.90, "twilight": 0.60, "night": 0.30},
        weights={"season": 0.28, "temp": 0.20, "current": 0.16,
                 "light": 0.14, "wind": 0.16, "pressure": 0.06},
        wind_max_kt=20,
        likes_falling_pressure=False,
        notes="A spring fish here, and a short window. The band shuts at 68°F, "
              "which the bay passes in late June and again coming down in "
              "early October.",
    ),
    "squid": Profile(
        key="squid", name="Longfin Squid",
        # These are the months the cited band is open over the GSO
        # climatology, weeks 19-45. [EFH-SQ] corroborates the shape from the
        # other direction -- they "migrate offshore during late autumn ...
        # and return inshore during the spring and early summer (MAFMC 1996)",
        # with larger individuals inshore off Massachusetts in April-May
        # (Lange 1982), which is what peak_months holds.
        months=(5, 6, 7, 8, 9, 10, 11), peak_months=(5, 6),
        # THE ONLY BAND IN THIS FILE WHOSE FOUR EDGES ALL COME FROM
        # NARRAGANSETT BAY ITSELF. [EFH-SQ Fig 8], Rhode Island Narragansett
        # Bay trawl surveys 1990-1996 -- the same series behind the fluke and
        # black sea bass depth bands -- for recruits (>= 9 cm mantle length,
        # which is essentially the catchable animal; L50 is 16 cm and most
        # mature above 10 cm):
        #   45F = 7C,  the coldest they were found at in this bay
        #   59F = 15C, the autumn mode ("in autumn 11-23C with most at 15C")
        #   70F = 21C, the top of the summer mode ("in summer 9-26C with most
        #              at 17-21C")
        #   79F = 26C, the warmest they were found at in this bay
        # Independently, [EFH-SQ] has the species "generally found at water
        # temperatures of at least 9C" (Lange and Sissenwine 1980), inside the
        # 7F cold edge above.
        temp=(45, 59, 70, 79),
        temp_claim=("four cited edges, and uniquely all four are from this "
                    "bay: 7C and 26C bound where recruits were found in the "
                    "1990-1996 RIDEM Narragansett Bay trawl, and the plateau "
                    "is that survey's own autumn mode (15C) to the top of its "
                    "summer mode (21C) [EFH-SQ Fig 8]"),
        # Hand-set. Jigged on a light tide, usually at anchor or against a
        # dock; heavy current makes the jig unfishable long before it moves
        # the squid.
        current=(0.55, 0.35, 0.50, 2.2),
        # No depth band despite a bay-specific modal depth being available --
        # the longest entry in the docstring's depth section explains why the
        # gear cannot see this fishery.
        #
        # Cited: [EFH-SQ] has them making "diurnal vertical migrations up into
        # the water column at night (MAFMC 1996)". That is the fishery: lights
        # over the side after dark. The one night-dominant curve in this file
        # that rests on a publication rather than on a striper fisherman.
        light={"night": 1.0, "twilight": 0.90, "golden": 0.55, "day": 0.20},
        weights={"season": 0.24, "temp": 0.18, "current": 0.16,
                 "light": 0.26, "wind": 0.12, "pressure": 0.04},
        wind_max_kt=16,
        likes_falling_pressure=False,
        notes="Both a target and the reason everything else shows up. Light "
              "carries this one — the published behaviour is a nightly rise "
              "into the water column, which is exactly what the lights exploit.",
    ),
    "dogfish": Profile(
        key="dogfish", name="Spiny Dogfish",
        # The months the band is open over the GSO climatology: weeks 16-21
        # and 44-49. [EFH-DOG] supports the shape -- Compagno (1984) "contends
        # their migrations are governed by temperature changes" -- so a
        # thermally-derived season is the right instrument for this fish.
        months=(4, 5, 10, 11, 12), peak_months=(5, 11),
        # Four cited edges, but from three different oceans, which is the
        # weakness. Out of [EFH-DOG]:
        #   43F = 6C,  "the lower limit of temperatures at which spiny dogfish
        #               are caught is 6-7C" in Bay of Fundy and Scotian Shelf
        #               summer trawls (Shepherd et al. 2002)
        #   45F = 7C   |  "Worldwide, spiny dogfish favor the temperature
        #   55F = 13C  |  range of 7-15C" (Compagno 1984); the plateau is
        #                 pulled in to 13C because [EFH-DOG Table 4] gives
        #                 eastern Long Island Sound adults at 7-13C in spring
        #                 and autumn, and Long Island Sound is the nearest
        #                 water to this bay that anyone measured
        #   59F = 15C, the top of that worldwide favoured range
        # [EFH-DOG] also records that "Laboratory studies of temperature and
        # salinity tolerances or preferences have not been done", so none of
        # this is physiology -- it is where the trawls found them.
        temp=(43, 45, 55, 59),
        temp_claim=("four cited edges from [EFH-DOG] but drawn from three "
                    "different oceans: 6C is the lower limit caught on the "
                    "Scotian Shelf (Shepherd et al. 2002), 7-15C is the "
                    "worldwide favoured range (Compagno 1984), and the "
                    "plateau top is pulled to the 13C ceiling of the eastern "
                    "Long Island Sound spring and autumn range, the nearest "
                    "comparable water. No laboratory preference exists"),
        # The one current tuple in the second cohort with any published
        # backing for its SHAPE: [EFH-DOG, after Zamon 2003] has tidal rips
        # and jets around rocky islands concentrating the plankton that
        # schooling fish feed on, "spiny dogfish follow these fish schools".
        # More current is better. The magnitude is still hand-set.
        current=(1.10, 0.60, 1.00, 3.5),
        # No depth band: three disjoint regional envelopes and a daily
        # vertical migration. See the docstring.
        #
        # Cited: [EFH-DOG, after Sameoto et al. 1994] found juveniles and
        # adults "near the bottom in daylight" and risen to 150 m at night.
        # A bait on the bottom meets them by day.
        light={"day": 1.0, "golden": 0.85, "twilight": 0.55, "night": 0.30},
        weights={"season": 0.26, "temp": 0.22, "current": 0.20,
                 "light": 0.12, "wind": 0.14, "pressure": 0.06},
        wind_max_kt=22,
        likes_falling_pressure=False,
        notes="Scored because knowing when they turn up is worth as much as "
              "knowing when a keeper does — a high score here is a warning "
              "that the drift is about to stop being worth making.",
    ),
    "striped_searobin": Profile(
        key="striped_searobin", name="Striped Sea Robin",
        # The months the band is open over the GSO climatology, weeks 17-47.
        # [SEAROBIN, after Mann 1974] independently brackets it in Long Island
        # Sound: first fish in May, last in December.
        months=(5, 6, 7, 8, 9, 10, 11), peak_months=(7, 8, 9),
        # COLD EDGE CITED, WARM EDGE ABSENT FROM THE LITERATURE ENTIRELY.
        # [SEAROBIN, after Mann 1974] at inshore Long Island Sound stations
        # off Shoreham, N.Y.: the first searobins appear at 10C (50F) in May
        # and the last are taken at 8C (46F) in December. Nearest comparable
        # water, and the two numbers are an arrival and a departure rather
        # than a tolerance envelope, which is what makes them usable.
        #
        # The warm pair is INERT -- 95/100F, the same spacer device as bonito
        # and as the fluke depth band's deep side. Nothing in [SEAROBIN]
        # bounds them warm; the one other figure it carries (Marshall 1946)
        # reads, in the scan, as entering New England waters above 4.4C and
        # leaving before the water fell below 15.5C, which is internally
        # contradictory and is not used. A number that might be an OCR error
        # is not a source.
        temp=(46, 50, 95, 100),
        temp_claim=("cold pair cited to Long Island Sound arrival at 10C in "
                    "May and departure at 8C in December [SEAROBIN, after "
                    "Mann 1974]; the warm pair is an inert spacer because no "
                    "publication found bounds this species on the warm side"),
        # Hand-set, and deliberately the fluke tuple with the peak widened:
        # you catch them on the fluke drift, over the same sand, at the same
        # speed. That is a statement about the fishery, not about the fish.
        current=(1.00, 0.45, 0.60, 2.6),
        # No depth band: [SEAROBIN]'s depth material is about the shelf south
        # of Cape Hatteras.
        light={"day": 1.0, "golden": 0.85, "twilight": 0.50, "night": 0.30},
        weights={"season": 0.24, "temp": 0.16, "current": 0.24,
                 "light": 0.12, "wind": 0.18, "pressure": 0.06},
        wind_max_kt=20,
        likes_falling_pressure=False,
        notes="Bycatch, scored on purpose: a high score means sand at the "
              "right speed, which is also the fluke drift. [GSO] has them "
              "rising — at Whale Rock the 2020-2024 mean is 4.82 against a "
              "1.92 long-term mean, the 87th percentile of 65 years.",
    ),
}


# ------------------------------------------------------ the ones that were not
#
# A species is missing from PROFILES for one of two reasons: nobody has looked
# at it, or somebody looked and the answer was no. Those are completely
# different facts and an empty dict cannot tell them apart -- which is the same
# argument the depth work made, that "no band" had to mean "the source said
# depth is the wrong variable" rather than "this is a gap to fill in later".
#
# So the refusals are written down. Everything here stays fully loggable; see
# the three tiers in species.py. This says only that the forecast declines to
# have an opinion, and why.

NOT_PROFILED: dict[str, str] = {
    "northern_kingfish": (
        "Envelope, no band. [ASMFC-SCI ch.8] gives adults a 7.8-35.8C "
        "tolerance and an avoidance limit above 31C, which this bay has never "
        "reached -- a trapezoid built from those would read 1.0 every day of "
        "the season and inform nothing. The one narrow figure in the chapter, "
        "rarely seen below 20C, is explicitly about water south of Cape "
        "Hatteras. Nothing in it is about Rhode Island."),
    "summer_triggerfish": (
        "No source about this water. Grey triggerfish reach here as warm-water "
        "strays; the management literature is South Atlantic and Gulf of "
        "Mexico, and the species is not among the 25 that make up 96% of "
        "everything the GSO trawl has caught in this bay since 1959 [COLLIE]. "
        "A band would be a Mid-Atlantic number wearing a Narragansett Bay "
        "label."),
    "spanish_mackerel": (
        "No source about this water, same shape as grey triggerfish. Caught "
        "here most years and described nowhere here; the available habitat "
        "documents are South Atlantic Fishery Management Council material "
        "about the core of the range, not its northern edge."),
    "cobia": (
        "No source about this water. Rare here and getting less so, which is "
        "a trend rather than a habitat description -- and a trend is not "
        "something a temperature band can be built out of. The literature is "
        "about Virginia southward."),
    "cod": (
        "Effectively gone from this water. [COLLIE] analysed the 25 species "
        "that are 96% of every animal the GSO trawl has caught here since "
        "1959, out of 130 recorded, and cod is not one of them; the shift the "
        "paper documents -- benthic to pelagic, cool-water to warm-water, "
        "sharply after 1980 -- is a shift away from exactly this group. "
        "Scoring cod would send a boat looking for a fishery the longest "
        "continuous record of this bay does not contain. Not the same as "
        "'absent': the 25 leave 4% unaccounted and one still turns up. Log it "
        "if it does."),
    "pollock": (
        "Effectively gone from this water, on the same [COLLIE] evidence as "
        "cod. A late-autumn fish of the rocks outside the bay if anywhere."),
    "monkfish": (
        "Effectively gone from this water, on the same [COLLIE] evidence. "
        "Goosefish appear in the EFH literature as a Gulf of Maine and "
        "Georges Bank animal; nothing describes a Narragansett Bay fishery."),
    # The offshore fourteen, refused together and for one structural reason
    # rather than for want of literature. Spelled out at the end of the module
    # docstring: every spot in spots.SPOTS is inside the bay and every term
    # here that carries signal is built on bay tidal current.
    **{k: ("Wrong scorer, not missing research. Every entry in spots.SPOTS is "
           "inside Narragansett Bay (41.36-41.72 N) and this model's load-"
           "bearing terms are bay tidal current -- a CO-OPS current-station "
           "prediction, plus tide-stage and spring-tide modifiers. A profile "
           "here would score this fish at Whale Rock off an ebb rip forty "
           "miles from the nearest one. Offshore needs its own scorer keyed "
           "on SST break gradient, chlorophyll and canyon structure; "
           "prospect.py already fetches all three.")
       for k in ("bluefin", "yellowfin", "bigeye", "albacore", "mahi",
                 "wahoo", "swordfish", "blue_marlin", "white_marlin",
                 "mako", "thresher", "porbeagle", "blue_shark", "haddock")},
}


# ------------------------------------------------------------------- the scorer

def _season_term(p: Profile, month: int, week: int | None = None,
                 thermal: dict[int, float] | None = None,
                 shift_days: int = 0) -> float:
    """Seasonal presence, from measurement where possible.

    Two different things are folded together here and it is worth keeping them
    apart in your head:

      * **Thermal presence** is derived from sixty-five years of weekly GSO
        temperature. It is measurement, and it replaces the hand-written month
        tuples -- which is how the tautog error surfaced, the data carving the
        summer closure out on its own.
      * **Migratory peak** is not thermal at all. Stripers peak in May-June and
        again in September-October because they are *moving through*, not
        because midsummer is too warm for them. No temperature series can tell
        you that, so those months stay hand-set.

    `shift_days` slides the thermal lookup when the year is running warm or
    cold: a spring five degrees ahead of normal pulls the whole run forward by
    a couple of weeks, which is exactly the local knowledge a fixed calendar
    cannot hold.
    """
    if thermal and week:
        eff = week + shift_days / 7.0
        lo = int(eff) % 52 or 52
        hi = (lo % 52) + 1
        frac = eff - int(eff)
        a, b = thermal.get(lo), thermal.get(hi)
        if a is not None and b is not None:
            presence = a + (b - a) * frac
        elif a is not None:
            presence = a
        else:
            presence = 1.0 if month in p.months else 0.0
    else:
        presence = 1.0 if month in p.months else 0.0

    peak = 1.0 if month in p.peak_months else 0.72
    return max(0.0, min(1.0, presence * peak))


def _wind_term(p: Profile, wind_kt: float | None, exposed: bool) -> float:
    if wind_kt is None:
        return 0.6
    cap = p.wind_max_kt * (0.8 if exposed else 1.0)
    if wind_kt >= cap:
        return 0.0
    # A little chop is better than glass for most of these species.
    return trapezoid(wind_kt, -1, 4, cap * 0.55, cap)


def _pressure_term(p: Profile, trend_mb_3h: float | None) -> float:
    if trend_mb_3h is None:
        return 0.6
    if p.likes_falling_pressure:
        # Falling pressure ahead of a front turns bass on; hard high is flat.
        return trapezoid(trend_mb_3h, -6.0, -2.5, -0.2, 2.5)
    return trapezoid(trend_mb_3h, -3.0, -1.0, 1.0, 3.0)


def score(species: str, feat: dict, exposed: bool = False,
          prior: float = 0.75, best_stage: str | None = None) -> dict:
    """Score one moment at one spot. Returns total 0..100 plus contributions.

    `prior` is the spot's standing reputation for this species and
    `best_stage` its preferred tide stage -- both local knowledge, both
    intended to be replaced by fitted values once a catch log exists."""
    p = PROFILES[species]

    # Every signal this scorer knows how to compute. A species uses the ones
    # its `weights` names and no others, which is the point: a term that does
    # not apply to a fish is absent for that fish rather than sitting at a
    # neutral 0.6 and reporting as "considered, found middling".
    #
    # The menu used to be these seven, hardcoded. features.build computes
    # thirty-seven fields and the scorer looked at six of them, so bait, birds,
    # whales and wind-against-tide were all calculated and thrown away -- built
    # and never wired, the same shape as the photo endpoint that had no caller.
    available: dict[str, float] = {
        "season": _season_term(p, feat["month"], feat.get("week"),
                               feat.get("thermal_season"),
                               feat.get("season_shift_days") or 0),
        "temp": trapezoid(feat["water_temp_f"], *p.temp) if feat.get("water_temp_f") else 0.6,
        "current": peaked(feat.get("current_speed", 0.0), *p.current),
        "light": p.light.get(feat["light_phase"], 0.6),
        "wind": _wind_term(p, feat.get("wind_kt"), exposed),
        "pressure": _pressure_term(p, feat.get("pressure_trend_3h")),
        # BAIT AND BIRDS ARE NOT HERE, and adding them was a mistake caught
        # before it shipped. They already reach the score, further down, as a
        # multiplicative modifier through `bait.combined_modifier` -- which is
        # the right shape for them: perfect water with nothing to eat in it is
        # an empty spot, so bait scales the whole answer rather than
        # contributing a slice of it. Making them terms as well would count
        # the same observation twice.
    }

    # Depth only exists as a term for the species that have a published band.
    # For the other four the key is ABSENT rather than neutral: a 0.6 sitting
    # in every result would be a number the literature never supplied, and
    # would report as though depth had been considered and found middling.
    if p.depth:
        d = feat.get("depth_ft")
        available["depth"] = trapezoid(float(d), *p.depth) if d is not None else 0.6

    # Bottom type, scored only where a profile names a preference. None do
    # yet, so this is inert -- deliberately. Fluke on sand and tautog on rock
    # are among the best-established habitat associations there are, and the
    # fluke profile's own notes already say "0.5-1.5 kt over sand and edges",
    # but a preference written from that sentence would be a number nobody
    # published. Same rule as depth: the machinery exists, the claim waits for
    # a citation.
    if p.bottom:
        b = feat.get("bottom")
        available["bottom"] = (0.6 if b is None
                               else max((w for k, w in p.bottom.items()
                                         if k in b), default=0.15))

    # Where the current prediction came from decides two things at once, and
    # they are the same decision seen from both ends.
    #
    # The scorer weights `current` more heavily than anything else and applied
    # that weight identically whether the station was 1.5 nm away or 64. At
    # the shelf edge the nearest in-bay station IS 64 nm off; a tidal
    # prediction carried that far is not a reading of this water, and scoring
    # it as one is how a forecast gets confident about places it knows nothing
    # about.
    #
    # And solunar was excluded because it is collinear with current -- it
    # peaks at lunar transit, transit drives the tide, the tide drives the
    # current, so the two agreeing is one witness heard twice. That argument
    # holds exactly where current is real, and dissolves where it is not. With
    # no usable current there is no second hearing of the same witness, and
    # solunar becomes an ordinary contested signal computed from lunar
    # geometry at THIS coordinate rather than a duplicate of a number
    # imported from sixty miles away.
    #
    # So: past FAR_NM the current term is dropped rather than discounted --
    # it is not a weak reading, it is not a reading -- and solunar is admitted
    # in its place for any profile that weights it.
    nm = feat.get("current_nm")
    far = nm is not None and nm > _FAR_BINDING_NM
    if far:
        available.pop("current", None)
        available["solunar"] = _clip(feat.get("solunar"))

    terms = {k: v for k, v in available.items() if k in p.weights}

    # Normalised by the weights actually used, so a species can opt into any
    # subset without the others silently rescaling. Adding `bait` to one fish
    # must not change what another fish scores.
    used = sum(p.weights[k] for k in terms) or 1.0
    total = sum(p.weights[k] * v for k, v in terms.items()) / used

    # Multiplicative modifiers -- things that gate rather than nudge.
    mods: dict[str, float] = {}

    # The spot's own reputation for this species. Compressed toward 1 so a
    # mediocre spot in perfect conditions still beats a great spot in bad ones.
    mods["spot_quality"] = 0.55 + 0.45 * prior

    # Spring tides move more water everywhere; neaps flatten the bay.
    spring = feat.get("spring_strength", 0.5)
    mods["spring_tide"] = 0.92 + 0.12 * spring
    if species == "tautog":
        mods["spring_tide"] = 1.0   # they sit on structure regardless

    # Some spots only really switch on when the water runs one way.
    if best_stage and feat.get("current_dir") in ("flood", "ebb"):
        mods["tide_stage"] = 1.0 if feat["current_dir"] == best_stage else 0.80

    # Bass specifically: hot water pushes the bite into darkness.
    if species == "striped_bass":
        wt = feat.get("water_temp_f") or 65
        if wt > 70 and feat["light_phase"] == "day":
            mods["heat_daytime"] = 0.55
        elif wt > 70 and feat["light_phase"] == "night":
            mods["heat_night"] = 1.06

    # Fluke: wind against tide wrecks the drift.
    if species == "fluke" and feat.get("wind_against_tide"):
        mods["wind_against_tide"] = 0.6

    # Bait scales everything rather than nudging one term: perfect water with
    # nothing to eat in it is still an empty spot. No reports means unknown,
    # which is neutral -- only an explicit "nothing around" scores below 1.
    # Bait and birds are different facts and combine rather than override.
    # Bait alone is food present; birds alone are a discounted proxy for it;
    # both together mean the bait is being driven up, which implies something
    # is driving it. See bait.combined_modifier.
    from .bait import combined_modifier as _combine
    m, which = _combine(feat.get("bait_signal"), feat.get("bird_signal"))
    if which:
        mods[which] = m

    for m in mods.values():
        total *= m

    return {
        "species": species,
        "name": p.name,
        "score": round(max(0.0, min(1.0, total)) * 100, 1),
        "terms": {k: round(v, 3) for k, v in terms.items()},
        "weighted": {k: round(p.weights[k] * v, 4) for k, v in terms.items()},
        "modifiers": {k: round(v, 3) for k, v in mods.items()},
    }


def explain(result: dict, top_n: int = 3) -> str:
    """Human sentence about what drove (or killed) the score."""
    p = PROFILES[result["species"]]
    ranked = sorted(result["weighted"].items(), key=lambda kv: kv[1], reverse=True)
    strong = [k for k, v in ranked if result["terms"][k] >= 0.75][:top_n]
    weak = [k for k, v in sorted(result["terms"].items(), key=lambda kv: kv[1])
            if v <= 0.35][:2]
    label = {
        "season": "seasonal timing", "temp": "water temperature",
        "current": "current speed", "light": "light level",
        "wind": "wind", "pressure": "barometer", "depth": "depth",
    }
    bits = []
    if strong:
        bits.append("helped by " + ", ".join(label[k] for k in strong))
    if weak:
        bits.append("held back by " + ", ".join(label[k] for k in weak))
    # spot_quality is always < 1 by construction, so only mention it when the
    # spot is genuinely a weak choice rather than merely not the very best.
    thresholds = {"spot_quality": 0.78}
    pretty = {"bait": "bait seen nearby", "birds": "birds working nearby",
              "bait_worked_by_birds": "bait being driven up — birds on it", "heat_night": "heat pushing the bite to dark",
              "heat_daytime": "daytime heat", "tide_stage": "wrong tide stage",
              "spot_quality": "spot quality", "spring_tide": "neap tide",
              "wind_against_tide": "wind against tide"}
    for k, v in result["modifiers"].items():
        name = pretty.get(k, k.replace("_", " "))
        if v < thresholds.get(k, 0.95):
            bits.append(f"held back by {name}")
        elif v > 1.05:
            bits.append(f"boosted for {name}")
    return "; ".join(bits) if bits else "middling on every axis"
