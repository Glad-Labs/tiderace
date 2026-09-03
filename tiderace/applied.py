"""Rules RIDEM published, applied without waiting for anybody.

`regs.py` is hand-written on purpose: nothing goes in that a person did not
read off a notice. That discipline is right, and it is also why the app spent
three days telling Matt black sea bass was 300 lb/day after RIDEM raised it to
400 -- the change was extracted, queued, and then sat there because the only
path into the rules was somebody editing Python.

So this is a machine-managed overlay beside the hand-written file, not a
rewrite of it. `regs.py` stays exactly as it is; this layers on top and every
field it sets carries the notice it came from, the date that notice took
effect, and the sentence it was read out of. Nothing is anonymous: if the app
says 400 lb/day, one tap shows you the RIDEM page that said so.

WHAT MADE THIS SAFE ENOUGH TO DO AUTOMATICALLY

Not confidence scores. The chain is deterministic end to end -- `ridem.py`
parses the amendments page by rule, not by model, and `reconcile.py` plays the
resulting stream forward to a current state. Applying it is mirroring a source,
not forming an opinion about one.

What was actually broken was a lossy hand-off. `ridem.parse_notice` read "the
commercial Tautog fishery will close, until the next sub-period begins on
August 1, 2026" correctly, reopening date and all, and the queue record kept
nine fields and dropped that one. The reconciler, seeing an open-ended closure,
reported tautog shut on 2 September when it had reopened on 1 August. Fixing
the hand-off turned two false mismatches into two true ones, which is the
difference between a source worth mirroring and one worth gating.

WHAT IS STILL NOT SAFE, AND IS DONE ANYWAY

A parse error that makes a rule *looser* is the one that costs money. Matt
asked for unconditional auto-apply with a source link instead of an approval
step, which is a real trade rather than a shortcut: checking one link beats
reviewing forty-four claims that never get reviewed. So every applied rule
carries `source_url` and `quote` and the interface shows them, and this module
flags a loosening rather than hiding it -- `relaxes` is set on any change that
raises a limit, lowers a size, or opens a season, so the interface can say
which way the change went.
"""

from __future__ import annotations

import os
from datetime import date, datetime

from . import cache

PATH = os.path.join(os.path.dirname(__file__), "..", "data", "regs_applied.json")


def _num(amount) -> float | None:
    if isinstance(amount, dict):
        v = amount.get("value")
        return float(v) if isinstance(v, (int, float)) else None
    return float(amount) if isinstance(amount, (int, float)) else None


def _relaxes(change_type: str, new, old) -> bool | None:
    """Does this change give more room than what it replaces?

    Unknown is not False. A change whose direction cannot be worked out is
    reported as unknown so the interface can say so, rather than being quietly
    filed as harmless.
    """
    if change_type == "season_open":
        return True
    if change_type in ("season_close", "quota_closure"):
        return False
    a, b = _num(new), _num(old)
    if a is None or b is None:
        return None
    if change_type == "possession_limit":
        return a > b            # a bigger bag is more room
    if change_type == "minimum_size":
        return a < b            # a smaller minimum is more room
    return None


def apply_state(state: dict, path: str = PATH,
                now: datetime | None = None) -> dict:
    """Write the reconciler's current view to the overlay.

    `state` is `reconcile.effective_state()` output: the notice in force per
    rule, already played forward past its own supersession.
    """
    now = now or datetime.now()
    out: dict = {"applied_at": now.isoformat(timespec="seconds"), "rules": {}}
    prev = (cache.read_json(path) or {}).get("rules", {})

    for key, n in state.items():
        sp = n.get("species_key")
        if not sp:
            continue
        mode = n.get("license_mode") or "unstated"
        # Keyed the way `reconcile._identity` keys, deliberately WITHOUT
        # period. Adding it here looks right -- RIDEM sets black sea bass at
        # 400 lb/day and 2800 lb/week in one notice, and collapsing them loses
        # the daily figure -- but reconcile has already collapsed them before
        # this sees them, and it excludes period for a reason worth keeping:
        # Massachusetts raised a pot limit from 500 to 600 and did not repeat
        # the word "daily", so keying on period left two contradictory limits
        # both in force with no signal which was live.
        #
        # The answer is not to re-split the key. It is that one number is not
        # the whole rule, so the interface lists every applied rule for a
        # species with its own notice rather than picking one to display.
        rid = "%s|%s|%s|%s" % (sp, mode, n.get("change_type"),
                               n.get("sub_fishery") or "-")
        old = prev.get(rid) or {}
        rec = {
            "species": sp,
            "license_mode": mode,
            "change_type": n.get("change_type"),
            "sub_fishery": n.get("sub_fishery"),
            "effective_date": n.get("effective_date"),
            "reopens_on": n.get("reopens_on"),
            "value": n.get("value") or _fmt(n),
            "amount": n.get("amount"),
            "period": n.get("period"),
            # Provenance is the whole point. Without these the overlay is a
            # number of unknown origin sitting on top of a cited one.
            "source_url": n.get("source_url"),
            "quote": (n.get("quote") or "")[:400],
            "parser": n.get("parser", "rule"),
            "applied_at": now.isoformat(timespec="seconds"),
        }
        rec["relaxes"] = _relaxes(rec["change_type"], n.get("amount"),
                                  old.get("amount"))
        rec["changed"] = (old.get("value") != rec["value"]) if old else True
        rec["previous"] = old.get("value") if old else None
        out["rules"][rid] = rec

    cache.write_json(path, out)
    return out


def _fmt(n: dict) -> str:
    a = n.get("amount") or {}
    v = ("%s %s" % (a.get("value"), a.get("unit"))).strip() if a else ""
    if n.get("period"):
        v = ("%s %s" % (v, n["period"])).strip()
    if n.get("change_type") in ("season_close", "quota_closure"):
        return "closed" + (" until %s" % n["reopens_on"] if n.get("reopens_on") else "")
    return v or n.get("change_type", "")


def load(path: str = PATH) -> dict:
    return cache.read_json(path) or {"rules": {}}


def overlay_for(species: str, mode: str = "commercial",
                when: date | None = None, path: str = PATH) -> list[dict]:
    """Applied rules in force for one species and licence mode.

    A closure whose `reopens_on` has passed is not in force. That is the whole
    reason this exists -- reading a closure without its end is what put tautog
    shut on a day it was open.
    """
    when = when or date.today()
    out = []
    for rec in load(path).get("rules", {}).values():
        if rec.get("species") != species:
            continue
        if rec.get("license_mode") not in (mode, "unstated"):
            continue
        try:
            eff = date.fromisoformat(rec["effective_date"])
        except (KeyError, TypeError, ValueError):
            continue
        if eff > when:
            continue
        ro = rec.get("reopens_on")
        if ro:
            try:
                if date.fromisoformat(ro) <= when:
                    continue          # spent: the period it closed has ended
            except ValueError:
                pass
        out.append(rec)
    return out


def summary(path: str = PATH) -> dict:
    d = load(path)
    rules = list(d.get("rules", {}).values())
    return {
        "applied_at": d.get("applied_at"),
        "count": len(rules),
        "changed": [r for r in rules if r.get("changed")],
        # Surfaced separately because this is the direction a parse error can
        # cost money rather than fishing days.
        "relaxed": [r for r in rules if r.get("relaxes") is True],
        "direction_unknown": [r for r in rules if r.get("relaxes") is None],
    }
