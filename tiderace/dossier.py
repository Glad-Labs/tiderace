"""Everything the app is willing to claim about one fish, and what each claim
rests on.

`survey.py` answers "everything true at this place and time". This answers the
other axis: everything true about this species, wherever you are. The two are
the same idea and deliberately the same shape -- a value, its source, and the
sentence that says how far the source actually reaches.

The reason this module exists is an embarrassment worth writing down. On
16 September 2026 the research in this project looked like this:

    score.PROFILES     temperature band + temp_claim, depth band +
                       depth_claim, substrate + bottom_claim, season months,
                       current curve, light curve, wind ceiling, barometer
                       preference, evidence tier + basis_claim, notes
    species.py         names, the aliases a person actually says on a boat,
                       group, HMS flag, the three tiers of claim
    regs.py / hms.py   the rules, hand-transcribed, with the date checked
    pelagic.py         the same again for the offshore fourteen

and the app showed: the species NAME in a picker, `notes`, the legal strip,
and `basis_claim` only when the tier was not "this water". Nothing else. The
tautog `temp_claim` is 293 characters explaining that its warm edge is the
least defensible pair in the file; the `bottom_claim` added the same day is
501 characters naming a document and a page. Both were reachable only by
opening the source.

So this is not new research. It is the research that was already done,
assembled in one place so that a person on a boat can see it. Nothing here
invents a number, and where a term rests on nothing better than somebody's
judgement it says so in those words -- because the point of the card is not
to look authoritative, it is to let you tell the cited half from the guessed
half at a glance.

That distinction is the whole design. `cited` on every term is the field to
read: tautog's temperature band is half literature and half angling knowledge,
and a card that rendered those two halves identically would be worse than no
card, in exactly the way a blank legal strip is worse than "rules not
modelled".
"""

from __future__ import annotations

from datetime import date

MONTHS = ("", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

# What a term is, in one phrase, for somebody who has not read score.py. The
# key is the scorer's own term name so the card and the "helped by ..." line
# on a forecast use the same vocabulary.
TERM_LABEL = {
    "season": "Season",
    "temp": "Water temperature",
    "current": "Current",
    "light": "Light",
    "wind": "Wind",
    "pressure": "Barometer",
    "depth": "Depth",
    "bottom": "Bottom type",
    "solunar": "Solunar",
    "sst": "Surface temperature",
    "front": "Thermal break",
    "structure": "Structure",
    "convergence": "Surface convergence",
}

# Terms whose numbers are hand-set priors everywhere in this project rather
# than read out of a document. Naming them here, once, is better than an
# `if` per term: score.py's docstring says plainly that "every `current`
# tuple except dogfish's shape, every `weights` dict, every `wind_max_kt`,
# every `likes_falling_pressure` and every `peak_months`" are unvalidated, and
# a card that quietly let them look like the cited bands would be lying by
# omission.
UNCITED_PRIOR = (
    "a hand-set prior, not from a document. Nothing published says what this "
    "fish wants of this factor in this water, and no catch log has tested it "
    "yet -- see `tiderace evaluate`")


def _f(v) -> str:
    """A number without a pointless trailing zero."""
    return ("%g" % v) if isinstance(v, (int, float)) else str(v)


def _months(months, peak=()) -> str:
    """"Apr–Dec, peak Oct–Nov", and correct across the turn of the year.

    Bonito run (6,7,8,9,10) and cod run (11,12,1,2,3,4). Sorting the second
    one before formatting gives "Jan–Dec", which is the opposite of the truth
    about a winter fish."""
    if not months:
        return ""
    # The tuples are written in the order the fish arrives, so the run is the
    # tuple itself, not the sorted set.
    runs, cur = [], [months[0]]
    for m in months[1:]:
        if m == (cur[-1] % 12) + 1:
            cur.append(m)
        else:
            runs.append(cur)
            cur = [m]
    runs.append(cur)
    out = ", ".join(MONTHS[r[0]] if len(r) == 1
                    else "%s–%s" % (MONTHS[r[0]], MONTHS[r[-1]]) for r in runs)
    if peak:
        out += ", peak " + _months(tuple(peak))
    return out


def _trapezoid_text(band, unit: str) -> str:
    """(38, 47, 58, 68) -> "38–68 F, best 47–58". The outer pair is where the
    term reaches zero and the inner pair is the plateau; showing only one of
    them is how an envelope gets read as a preference."""
    lo_out, lo_in, hi_in, hi_out = band
    return "%s–%s%s, best %s–%s" % (_f(lo_out), _f(hi_out), unit,
                                    _f(lo_in), _f(hi_in))


def _current_text(cur) -> str:
    opt, _lo, _hi, hard = cur
    return "best %s kt, nothing above %s kt" % (_f(opt), _f(hard))


def _light_text(light: dict) -> str:
    """Best phases first. A card that listed them in dict order would put
    "day" first for a fish that feeds at night."""
    if not light:
        return ""
    ranked = sorted(light.items(), key=lambda kv: -kv[1])
    return " · ".join("%s %s" % (k, _f(round(v, 2))) for k, v in ranked)


def _bottom_text(bottom: dict) -> str:
    """Grouped by weight, because "rock 1.0, boulder 1.0, stone 1.0" is three
    ways of saying the same thing and reads as three findings."""
    if not bottom:
        return ""
    groups: dict[float, list[str]] = {}
    for k, v in bottom.items():
        groups.setdefault(round(v, 2), []).append(k)
    return " · ".join("%s (%s)" % (", ".join(sorted(names)), _f(w))
                      for w, names in sorted(groups.items(), reverse=True))


def _term(name: str, weight: float, value: str, claim: str,
          cited: bool) -> dict:
    return {"term": name, "label": TERM_LABEL.get(name, name),
            "weight": round(weight, 3), "value": value,
            "claim": claim or (UNCITED_PRIOR if not cited else ""),
            "cited": cited}


def _bay_terms(p) -> list[dict]:
    """One row per term the bay scorer actually weights for this fish.

    Only the weighted ones. A card that listed every term the scorer knows
    would report depth for a tautog -- which is precisely the thing score.py
    refuses to do, and for a documented reason.
    """
    out = []
    for name, w in p.weights.items():
        if name == "season":
            # No claim field of its own. The months are from the literature
            # cited for the species; the PEAK months are not, and saying so is
            # the difference between this card and a brochure.
            out.append(_term(name, w, _months(p.months, p.peak_months),
                             "months from the sources cited for this fish; "
                             "the peak months are a hand-set prior", False))
        elif name == "temp":
            out.append(_term(name, w, _trapezoid_text(p.temp, "°F"),
                             p.temp_claim, bool(p.temp_claim)))
        elif name == "current":
            out.append(_term(name, w, _current_text(p.current), "", False))
        elif name == "light":
            out.append(_term(name, w, _light_text(p.light), "", False))
        elif name == "wind":
            out.append(_term(name, w, "fishable to %s kt" % _f(p.wind_max_kt),
                             "", False))
        elif name == "pressure":
            out.append(_term(name, w,
                             "likes falling" if p.likes_falling_pressure
                             else "no preference for a falling glass",
                             "", False))
        elif name == "depth" and p.depth:
            out.append(_term(name, w, _trapezoid_text(p.depth, " ft"),
                             p.depth_claim, bool(p.depth_claim)))
        elif name == "bottom" and p.bottom:
            out.append(_term(name, w, _bottom_text(p.bottom),
                             p.bottom_claim, bool(p.bottom_claim)))
    out.sort(key=lambda r: -r["weight"])
    return out


# Which habitat feature each offshore term actually measures, and what the app
# measures it WITH. `features` on a profile is the set of things the document
# ties that fish to; the weights name the terms computed from them, and the
# mapping between the two is not one-to-one by name.
FEATURE_TERM = {
    "structure": ("shelf_break",
                  "shelf break or canyon wall — the steepest bottom in the "
                  "DEM grid within reach"),
    "front": ("front",
              "the sharpest temperature break in the MUR grid within reach"),
    "convergence": ("floating_structure",
                    "surface convergence, standing in for where floating "
                    "things collect — HF radar, which covers 18% of the box "
                    "and nothing south of 40.67 N"),
}


def _offshore_terms(p, weights: dict) -> list[dict]:
    """The pelagic scorer keeps its bands on the profile and its weights in a
    separate table, so this takes both. Every offshore score carries
    `unvalidated` and the card has to carry it too."""
    out = []
    for name, w in weights.items():
        if name == "sst" and getattr(p, "sst", None):
            out.append(_term(name, w, _trapezoid_text(p.sst, "°F"),
                             p.sst_claim, bool(p.sst_claim)))
        elif name == "season":
            out.append(_term(name, w, _months(p.months, p.peak_months),
                             p.season_claim, bool(p.season_claim)))
        elif name in FEATURE_TERM:
            # Each term measures ONE feature, and `features` is the whole set
            # this fish is tied to. Printing the set against all three terms
            # made bluefin's "thermal break" and "structure" rows read
            # identically -- two different measurements wearing one label.
            feature, what = FEATURE_TERM[name]
            if feature not in (p.features or ()):
                continue
            out.append(_term(name, w, what, p.features_claim,
                             bool(p.features_claim)))
    out.sort(key=lambda r: -r["weight"])
    return out


def _refusal(key: str) -> str | None:
    """Why this fish has no forecast, in the scorer's own words.

    `score.NOT_PROFILED` holds a sentence per refused species, and a refusal
    is a stronger answer than an absence -- somebody looked. A card that
    showed a blank where the reason lives would turn a finding back into a
    gap.
    """
    from . import score
    reason = score.NOT_PROFILED.get(key)
    return reason if isinstance(reason, str) else (
        reason.get("reason") if isinstance(reason, dict) else None)


def build(key: str, when: date | None = None) -> dict:
    """The card for one fish. Raises ValueError for a fish nothing knows."""
    from . import pelagic, regs, score, species as speciesmod
    sp = speciesmod.get(key)
    if sp is None:
        raise ValueError("unknown species %r" % key)
    when = when or date.today()

    out: dict = {
        "key": sp.key,
        "name": sp.name,
        # What people actually call it on a boat. These are what the voice log
        # and the report reader match against, so they are a real part of what
        # the app knows rather than decoration.
        "aliases": list(sp.aliases),
        "group": sp.group,
        "hms": sp.hms,
        "notes": sp.notes,
        "tiers": {"loggable": True, "scored": sp.scored,
                  "regulated": sp.regulated},
        "forecast": None,
        "photo": None,
        "unavailable": {},
    }

    # A reference photograph, and the binomial it was resolved through. Both
    # or neither: an image with no credit would be somebody's work taken
    # without the licence's one condition, and an image with no binomial
    # would hide exactly the failure this is most likely to have -- matching
    # "Monkfish" to a fish on the other side of the world that answers to the
    # same common name.
    try:
        from . import fishpic
        out["photo"] = fishpic.get(key)
        e = fishpic.entry(key)
        if out["photo"] is None:
            out["unavailable"]["photo"] = (
                "no Creative Commons photograph on this taxon"
                if e.get("resolved") and not e.get("file") else
                "no confident match on iNaturalist for this fish"
                if e.get("resolved") is False else
                "not fetched yet — run `tiderace species --photos`")
        else:
            out["photo"]["verified"] = e.get("verified") or ""
    except Exception:                                             # noqa: BLE001
        # A card is reference material and must render without a photo. The
        # forecast path never touches this module, so a failure here can cost
        # an image and nothing else.
        out["unavailable"]["photo"] = "photo lookup unavailable"

    if key in score.PROFILES:
        p = score.PROFILES[key]
        out["forecast"] = {
            "scorer": "bay",
            "basis": p.basis,
            "basis_claim": p.basis_claim,
            "notes": p.notes,
            "terms": _bay_terms(p),
            # The bay scorer's own honesty, carried onto the card: no weight
            # in this file has ever been tested against a catch.
            "unvalidated": p.basis != "this water",
            "weights_note": (
                "The weights are priors. None of them has been fitted to a "
                "catch, and `tiderace evaluate` will say how far the log is "
                "from being able to fit them."),
        }
    elif key in pelagic.PROFILES:
        p = pelagic.PROFILES[key]
        out["forecast"] = {
            "scorer": "offshore",
            "basis": p.basis,
            "basis_claim": p.basis_claim,
            "notes": getattr(p, "fish_depth_note", "") or "",
            "terms": _offshore_terms(p, pelagic.WEIGHTS.get(key, {})),
            # Every offshore score carries this. It is not a hedge, it is the
            # state of the evidence: the bands name a document, the weights
            # name nobody.
            "unvalidated": True,
            "weights_note": (
                "Offshore scores are unvalidated by construction: the bands "
                "cite a document and the weights are priors no document can "
                "give."),
        }
        out["sources"] = list(getattr(p, "sources", ()) or ())
    else:
        out["unavailable"]["forecast"] = (
            _refusal(key)
            or "No forecast model has an opinion about this fish. It is still "
               "loggable, which is the point of keeping the tiers apart.")

    # ---- the rules ------------------------------------------------------
    #
    # Never invented, and the absence is the message where there is one. This
    # reuses the same tables the legal strip reads rather than paraphrasing
    # them, because two descriptions of one rule is how they drift.
    out["rules"] = {
        "recreational": _rule_text(regs.RULES.get(key)),
        "commercial": _commercial_text(regs.COMMERCIAL.get(key)),
        "warning": speciesmod.unregulated_warning(key),
        "hms": sp.hms,
    }
    if sp.hms:
        out["rules"]["note"] = (
            "Federally managed. The rule lives in hms.py with the date it was "
            "checked, and this app does not track the in-season quota "
            "closures, so it will not tell you the fishery is open.")
    return out


def _rule_text(rule) -> dict | None:
    if rule is None:
        return None
    return {
        "min_inches": rule.min_inches,
        "max_inches": rule.max_inches,
        "slot": list(rule.slot) if rule.slot else None,
        "bag": rule.bag,
        "open_periods": [_period(a, b) for a, b in rule.open_periods],
        "note": rule.note,
    }


def _commercial_text(rule) -> dict | None:
    if rule is None:
        return None
    return {
        "min_inches": rule.min_inches,
        "limit": rule.limit,
        "open_periods": [_period(a, b) for a, b in rule.periods],
        "closed_weekdays": list(rule.closed_weekdays),
        "quota_closed": rule.quota_closed,
        "note": rule.note,
    }


def _period(a, b) -> str:
    return "%s %d – %s %d" % (MONTHS[a[0]], a[1], MONTHS[b[0]], b[1])
