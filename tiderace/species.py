"""Every fish you might catch here, and what the app is willing to claim about it.

Until now `score.PROFILES` was the only species registry, and everything gated
on it: you could not log a bonito because the model had no opinion about
bonito. That is backwards. Whether the app can forecast a fish and whether you
can record catching one are different questions, and conflating them meant the
catch log -- the scarcest thing in the project -- silently refused most of what
comes over the rail.

So there are three tiers here, and the difference between them is what is being
claimed:

  **loggable**    Everything. Costs nothing, claims nothing, and is the whole
                  point: you caught a bonito, the log should hold that.

  **scored**      The fourteen in `score.PROFILES`. Their temperature bands
                  are grounded in published literature and cited in that file;
                  the weights are still hand-set priors waiting on a catch log.
                  Adding a fifteenth means doing that research, not guessing.

                  It was six until 2026-09-02, when the inshore and nearshore
                  species got the same treatment the original six had. The
                  other twenty-one are not a backlog: `score.NOT_PROFILED`
                  carries a reason for every one of them, and for eleven of
                  those the reason is that somebody looked and the answer was
                  no. An absence and a refusal are different facts.

  **regulated**   Only where the rules were actually read out of a RIDEM or
                  DMF notice. Anything else says so and points at the book.

That last tier is the one that matters most and the one most tempting to fill
in from memory. A wrong size limit is not a bad forecast -- it is a fine, and
under a commercial licence it is worse than a fine. When this file says the
rules are not modelled for a species, that is a fact about this app, not
permission to keep the fish.

Nothing here invents a season, a size or a bag limit. Where a number is absent
it is because nobody verified it, and the app says exactly that.
"""

from __future__ import annotations

from dataclasses import dataclass, field


# Where a fish lives, which decides whether the inshore model could ever apply
# to it. The bay model is built on tidal current; that is the right signal for
# a striper in a rip and meaningless for a mahi under a weedline seventy miles
# out, where the question is water temperature and where the break is.
INSHORE = "inshore"          # the bay, the shore, the breachways
NEARSHORE = "nearshore"      # the sounds and out to the wind farm
OFFSHORE = "offshore"        # the canyons, the shelf, blue water
FRESHWATER = "freshwater"    # runs into the bay, not the target of this app


@dataclass
class Species:
    key: str
    name: str
    group: str
    # What people actually call it on a boat, for the voice log and for reading
    # reports. "Squeteague" is what an older fisherman calls a weakfish and no
    # speech recogniser has ever heard of it.
    aliases: tuple[str, ...] = ()
    # HMS species are federally managed and need a permit; the rules live in
    # hms.py, not in the state tables.
    hms: bool = False
    notes: str = ""

    @property
    def scored(self) -> bool:
        """Does a forecast model have an opinion about this fish? Two of them
        can: score.PROFILES inshore, pelagic.PROFILES offshore."""
        from .score import PROFILES
        from .pelagic import PROFILES as OFFSHORE
        return self.key in PROFILES or self.key in OFFSHORE

    @property
    def regulated(self) -> bool:
        """Have the rules for this fish actually been read from a notice?"""
        from .regs import RULES
        return self.key in RULES


# Ordered roughly by how often they turn up on a Narragansett Bay boat, because
# this list becomes a dropdown and the fish you catch weekly should not be
# below the one you catch once a decade.
SPECIES: tuple[Species, ...] = (
    # ---- the original six the model scored ----
    Species("striped_bass", "Striped Bass", INSHORE,
            ("striper", "stripers", "bass", "schoolie", "schoolies",
             "keeper", "linesider", "rockfish")),
    Species("bluefish", "Bluefish", INSHORE,
            ("blues", "blue", "chopper", "snapper blue", "cocktail blue")),
    Species("fluke", "Fluke (Summer Flounder)", INSHORE,
            ("summer flounder", "flounder", "doormat")),
    Species("black_sea_bass", "Black Sea Bass", INSHORE,
            ("sea bass", "seabass", "knothead", "humpback")),
    Species("scup", "Scup (Porgy)", INSHORE,
            ("porgy", "porgies", "pogy")),
    Species("tautog", "Tautog (Blackfish)", INSHORE,
            ("tog", "blackfish", "white chin")),

    # ---- inshore and nearshore: six of these eight are now modelled ----
    #
    # northern_kingfish and summer_triggerfish are the two that are not, and
    # both are recorded refusals rather than omissions — see
    # score.NOT_PROFILED for what was consulted and what it said.
    Species("weakfish", "Weakfish", INSHORE,
            ("squeteague", "squet", "sea trout", "grey trout"),
            notes="Was the bay's other great inshore fish. The GSO trawl "
                  "series says the recovery is further along at the mouth "
                  "than the usual story allows — a 2020-2024 mean of 2.20 at "
                  "Whale Rock against 0.70 across 65 years."),
    Species("winter_flounder", "Winter Flounder", INSHORE,
            ("blackback", "black back", "flatfish"),
            notes="Cold-water flatfish, a spring fishery when there is one."),
    Species("northern_kingfish", "Northern Kingfish", INSHORE,
            ("kingfish", "roundhead", "sea mullet")),
    Species("atlantic_mackerel", "Atlantic Mackerel", NEARSHORE,
            ("mackerel", "tinker", "tinkers", "boston mackerel")),
    Species("squid", "Longfin Squid", NEARSHORE,
            ("calamari", "loligo"),
            notes="Both a target and the bait that brings everything else in."),
    Species("summer_triggerfish", "Grey Triggerfish", NEARSHORE,
            ("trigger", "triggerfish"),
            notes="Arriving more often as the water warms."),
    Species("cobia", "Cobia", NEARSHORE,
            ("ling", "lemonfish"),
            notes="Rare here and getting less so."),
    Species("spanish_mackerel", "Spanish Mackerel", NEARSHORE,
            ("spanish",)),
    Species("striped_searobin", "Striped Sea Robin", INSHORE,
            ("sea robin", "robin", "searobin"),
            notes="Bycatch, but worth logging: they mean you are on sand and "
                  "usually mean the fluke are not there."),
    Species("dogfish", "Spiny Dogfish", NEARSHORE,
            ("dog", "dogs", "sand shark"),
            notes="Bycatch. Logging them is how you learn which drifts are "
                  "worth abandoning."),

    # ---- the fall run: modelled since 2026-09-02 ----
    Species("bonito", "Atlantic Bonito", NEARSHORE,
            ("bones", "boneeto")),
    Species("false_albacore", "False Albacore", NEARSHORE,
            ("albie", "albies", "little tunny", "fat albert")),

    # ---- cold water ----
    #
    # Loggable and deliberately never scored. `score.NOT_PROFILED` carries the
    # reasoning: none of these three is among the 25 species that make up 96%
    # of everything the GSO trawl has caught in this bay since 1959, and the
    # documented shift in that series is away from exactly this group. Absence
    # from the forecast is a finding here, not a gap.
    Species("cod", "Atlantic Cod", NEARSHORE,
            ("codfish", "market cod", "scrod"),
            notes="Not forecast: effectively gone from this water. Log it if "
                  "one turns up — that is worth more than a forecast would be."),
    Species("pollock", "Pollock", NEARSHORE, ("pollack",),
            notes="Not forecast: effectively gone from this water."),
    Species("haddock", "Haddock", OFFSHORE, ()),
    Species("monkfish", "Monkfish", NEARSHORE,
            ("goosefish", "monk"),
            notes="Not forecast: effectively gone from this water; the "
                  "literature describes a Gulf of Maine and Georges Bank fish."),

    # ---- offshore, HMS: federally managed, permit required ----
    Species("bluefin", "Bluefin Tuna", OFFSHORE,
            ("bluefin tuna", "blue fin", "giant"), hms=True),
    Species("yellowfin", "Yellowfin Tuna", OFFSHORE,
            ("yellowfin tuna", "yellow fin", "ahi"), hms=True),
    Species("bigeye", "Bigeye Tuna", OFFSHORE,
            ("bigeye tuna", "big eye"), hms=True),
    Species("albacore", "Albacore Tuna", OFFSHORE,
            ("longfin tuna", "longfin albacore"), hms=True),
    Species("mahi", "Mahi Mahi", OFFSHORE,
            ("dorado", "dolphinfish", "dolphin fish", "dolphin")),
    Species("wahoo", "Wahoo", OFFSHORE, ("ono",)),
    Species("swordfish", "Swordfish", OFFSHORE, ("broadbill", "sword"), hms=True),
    Species("blue_marlin", "Blue Marlin", OFFSHORE, ("blue",), hms=True),
    Species("white_marlin", "White Marlin", OFFSHORE, (), hms=True),
    Species("mako", "Shortfin Mako", OFFSHORE, ("mako shark",), hms=True),
    Species("thresher", "Common Thresher", OFFSHORE, ("thresher shark",), hms=True),
    Species("porbeagle", "Porbeagle", OFFSHORE, (), hms=True),
    Species("blue_shark", "Blue Shark", OFFSHORE, ("blue dog",), hms=True),
)

BY_KEY = {s.key: s for s in SPECIES}


def get(key: str) -> Species | None:
    return BY_KEY.get(key)


def resolve(said: str) -> str | None:
    """A spoken or written name onto a key.

    Longest alias wins, so "sea bass" beats "bass" and "bluefin tuna" beats
    "tuna". Getting that order wrong turns every sea bass into a striper, which
    is the kind of quiet error that is only visible a season later.
    """
    import re
    t = " " + (said or "").strip().lower() + " "
    hits = []
    for s in SPECIES:
        for name in (s.key.replace("_", " "), s.name.lower(), *s.aliases):
            n = name.lower()
            if re.search(r"\b" + re.escape(n) + r"s?\b", t):
                hits.append((len(n), s.key))
    if not hits:
        return None
    hits.sort(reverse=True)
    return hits[0][1]


def loggable() -> list[Species]:
    """Everything. The catch log should never refuse a fish you caught."""
    return list(SPECIES)


def scored() -> list[Species]:
    """The ones the forecast has a defensible opinion about."""
    return [s for s in SPECIES if s.scored]


def unregulated_warning(key: str) -> str | None:
    """What to say when the rules for this fish are not in the app.

    Deliberately not silent. Absence of a rule here means nobody checked, and
    on a commercial licence the difference between "no limit" and "not
    modelled" is the difference between a legal fish and a violation.
    """
    s = get(key)
    if not s or s.regulated:
        return None
    if s.hms:
        return (f"{s.name} is federally managed (HMS) and needs a permit. "
                "Limits are not modelled here — check your HMS category.")
    return (f"Size and season for {s.name} are not modelled in this app. "
            "That means nobody verified them, not that there are none — "
            "check the RIDEM table before keeping one.")
