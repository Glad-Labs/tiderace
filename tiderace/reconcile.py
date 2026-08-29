"""Compare what RIDEM currently says against what `regs.py` claims.

Reviewing twenty-two notices to find the one that matters is how staleness
survives review. This narrows the page to disagreements.

Three things make the comparison less obvious than it sounds:

  * **Notices supersede each other.** Black sea bass ran 750 -> 150 -> 200 ->
    300 -> 400 lb/day across the season. Only the most recent notice on or
    before today describes the rule in force; everything after it is a
    scheduled change, which is a different and equally useful finding.

  * **One species can carry several fisheries.** "vessels with a Summer
    Flounder Exemption Certificate" and "participants in the Summer/Fall
    period of the Aggregate program" are distinct limits that share a species,
    a date and a unit. The parser cannot tell them apart, so where several
    notices collide on the same key this reports the collision rather than
    silently picking one.

  * **`regs.py` stores limits as prose.** "300 lb/day with Exemption
    Certificate, 200 lb/day without" has no single number to compare against.
    So the test is deliberately weak and honest: does the stored text mention
    the number RIDEM is publishing? A miss means look, not that the code is
    definitely wrong.

Nothing here edits anything. It tells you where to point your eyes.
"""

from __future__ import annotations

import re
from datetime import date

from . import regs


def _key(n: dict) -> tuple:
    # The Aggregate Program is a distinct fishery, so its notices key
    # separately -- comparing a 6,000 lb bi-weekly aggregate limit against the
    # general 300 lb/day one is not a disagreement, it is a category error.
    return (n.get("species_key"), n["license_mode"], n["change_type"],
            n.get("period"), n.get("aggregate_program"), n.get("sub_fishery"))


def _promote(n: dict, on_date: str) -> dict | None:
    """Turn a spent notice into the rule its own text says replaced it."""
    sc = n.get("successor")
    if not sc:
        return None                       # the fishery simply ended
    if sc.get("closes"):
        return None
    promoted = dict(n)
    promoted.update({
        "effective_date": on_date,
        "amount": sc.get("amount"),
        # An unlimited successor has no period to speak of; inheriting the
        # parent's split one fishery into two identical-looking rows.
        "period": None if sc.get("unlimited")
                  else (sc.get("period") or n.get("period")),
        "change_type": "possession_limit",
        "superseded_on": None,
        "successor": None,
        "unlimited": sc.get("unlimited", False),
        "derived_from": n["effective_date"],
        "quote": n["quote"],
    })
    return promoted


def effective_state(notices: list[dict], on: date | None = None) -> dict:
    """The most recent notice per rule on or before `on`."""
    on = on or date.today()
    state: dict[tuple, dict] = {}
    collisions: dict[tuple, int] = {}
    for n in notices:
        if not n.get("species_key"):
            continue
        try:
            eff = date.fromisoformat(n["effective_date"])
        except (KeyError, ValueError):
            continue
        if eff > on:
            continue
        # A notice that names its own successor date is spent once that date
        # passes -- for possession limits exactly as much as for closures.
        sup = n.get("superseded_on")
        if sup and sup <= on.isoformat():
            # The amendments page lists *changes*, not current state, so for
            # several fisheries the rule actually in force is only written
            # inside a spent notice's tail: "...or until the next sub period
            # begins on May 1, 2026 at ten thousand (10,000) pounds per week".
            # Promoting that successor is the difference between being able to
            # check scup at all and having nothing to compare.
            n = _promote(n, sup)
            if n is None:
                continue
        k = _key(n)
        prev = state.get(k)
        if prev is None or n["effective_date"] > prev["effective_date"]:
            state[k] = n
            collisions[k] = 1
        elif n["effective_date"] == prev["effective_date"]:
            collisions[k] = collisions.get(k, 1) + 1
    for k, c in collisions.items():
        state[k]["same_date_notices"] = c
    return state


def upcoming(notices: list[dict], on: date | None = None,
             within_days: int = 60) -> list[dict]:
    on = on or date.today()
    out = []
    for n in notices:
        if not n.get("species_key"):
            continue
        try:
            eff = date.fromisoformat(n["effective_date"])
        except (KeyError, ValueError):
            continue
        if on < eff <= date.fromordinal(on.toordinal() + within_days):
            out.append(n)
    return sorted(out, key=lambda n: n["effective_date"])


def _numbers(text: str) -> set[int]:
    return {int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", text or "")}


def compare(notices: list[dict], on: date | None = None,
            mode: str = "commercial", only_fishery: str | None = None) -> dict:
    """Findings, most actionable first.

    `only_fishery` filters to the sub-fishery you actually operate in.
    """
    on = on or date.today()
    state = effective_state(notices, on)
    findings = []

    for k, n in sorted(state.items(), key=lambda kv: str(kv[0])):
        species, notice_mode, change, period, program, sub = k
        # Skip fisheries you are not in. A Floating Fish Trap limit is not a
        # disagreement with a General Category one.
        if sub and only_fishery and sub != only_fishery:
            continue
        if notice_mode not in (mode, "unstated"):
            continue
        rule = regs.COMMERCIAL.get(species) if mode == "commercial" \
            else regs.RULES.get(species)
        if rule is None:
            findings.append({
                "severity": "unknown", "species": species,
                "detail": f"RIDEM publishes a rule for {species} that "
                          f"{mode} regs.py does not model",
                "notice": n})
            continue

        amount = n.get("amount") or {}
        value = amount.get("value")

        if program:
            ap = regs.AGGREGATE.get(program)
            if ap is None:
                findings.append({
                    "severity": "unknown", "species": species,
                    "detail": f"aggregate programme '{program}' is not modelled",
                    "notice": n})
                continue
            # A multiplier-based limit tracks the daily one, so the published
            # poundage is derived and matching it against a stored number would
            # be checking arithmetic, not policy.
            if ap.multiplier:
                findings.append({
                    "severity": "ok", "species": species,
                    "detail": f"{ap.name}: {ap.multiplier:g}x daily (published "
                              f"{value} {amount.get('unit','')} {period or ''})",
                    "notice": n})
            elif ap.fixed_amount and value in _numbers(ap.fixed_amount):
                findings.append({
                    "severity": "ok", "species": species,
                    "detail": f"{ap.name}: {ap.fixed_amount} {ap.unit}",
                    "notice": n})
            else:
                findings.append({
                    "severity": "mismatch", "species": species,
                    "detail": (f"{ap.name}: RIDEM {value} {amount.get('unit','')} "
                               f"{period or ''}  ·  regs.py {ap.fixed_amount}"),
                    "notice": n})
            continue

        stored = getattr(rule, "limit", "") or getattr(rule, "bag", "")

        if change in ("season_close", "season_open"):
            ridem_open = change == "season_open"
            # A closure that names its own reopen date has expired once that
            # date passes. Reading the closure alone reported tautog and scup
            # as shut months after they legally reopened.
            reopened = n.get("reopens_on")
            if change == "season_close" and reopened and reopened <= on.isoformat():
                findings.append({
                    "severity": "ok", "species": species,
                    "detail": f"closed {n['effective_date']}, reopened {reopened}",
                    "notice": n})
                continue
            code_open = rule.is_open(on)
            if ridem_open != code_open:
                findings.append({
                    "severity": "mismatch", "species": species,
                    "detail": (f"RIDEM says {'open' if ridem_open else 'closed'} "
                               f"since {n['effective_date']}; regs.py says "
                               f"{'open' if code_open else 'closed'}"),
                    "notice": n})
            continue

        if n.get("unlimited"):
            findings.append({
                "severity": "ok" if "unlimited" in (stored or "").lower()
                            else "mismatch",
                "species": species,
                "detail": f"RIDEM: unlimited  ·  regs.py: {stored or '(nothing)'}",
                "notice": n})
            continue

        if value is None:
            continue

        if value in _numbers(stored):
            severity = "ok"
            detail = f"{value} {amount.get('unit','')} {period or ''}".strip()
        else:
            severity = "mismatch"
            detail = (f"RIDEM: {value} {amount.get('unit','')} {period or ''}"
                      f"  ·  regs.py: {stored or '(nothing stored)'}")

        if n.get("same_date_notices", 1) > 1:
            severity = "ambiguous" if severity == "mismatch" else severity
            detail += (f"  [{n['same_date_notices']} notices share this date — "
                       "separate fisheries, check which applies to you]")

        findings.append({"severity": severity, "species": species,
                         "detail": detail, "notice": n})

    order = {"mismatch": 0, "ambiguous": 1, "unknown": 2, "ok": 3}
    findings.sort(key=lambda f: (order.get(f["severity"], 9), f["species"] or ""))

    return {
        "as_of": on.isoformat(),
        "mode": mode,
        "findings": findings,
        "upcoming": upcoming(notices, on),
        "checked_on": (regs.COMMERCIAL_CHECKED_ON if mode == "commercial"
                       else regs.CHECKED_ON).isoformat(),
        "counts": {s: sum(1 for f in findings if f["severity"] == s)
                   for s in ("mismatch", "ambiguous", "unknown", "ok")},
    }
