"""When each source was last read, and whether it worked.

Scheduling the scrapes is the easy half. The half that decides whether they
are worth having is this one: a scrape that runs on a timer and fails quietly
is strictly worse than one you run by hand, because the manual one at least
fails in front of you. Once it is automatic you stop checking, and the app goes
on rendering a regulation read in August as though it were read this morning.

So every run writes what happened here, per source, and the desk shows it. A
source that has not reported in longer than it should is called stale in the
interface rather than left to look current.

Nothing in here is a fact about fishing. It is a fact about whether the facts
about fishing are any good, which is the sort of thing that only gets built
after something has already gone unnoticed for a while.
"""

from __future__ import annotations

import os
from datetime import datetime

from . import cache

PATH = os.path.join(os.path.dirname(__file__), "..", "data", "scrape_runs.json")

# How long a source may go unread before the interface says so. Regulations
# are checked daily and a two-day gap means something is broken; the report
# outlets publish weekly, so ten days is a missed edition rather than a fault.
STALE_AFTER_H = {"regulation": 48, "report": 240}


def record(source: str, kind: str, ok: bool, detail: str = "",
           path: str = PATH) -> None:
    """Note one source's outcome. Never raises: a bookkeeping failure must not
    take down the scrape it was bookkeeping."""
    try:
        runs = cache.read_json(path) or {}
        prev = runs.get(source) or {}
        now = datetime.now().isoformat(timespec="seconds")
        entry = {
            "kind": kind,
            "last_attempt": now,
            "ok": bool(ok),
            "detail": detail[:300],
            # Kept separately so a run of failures cannot erase the memory of
            # when the data was actually last any good.
            "last_success": now if ok else prev.get("last_success"),
            "fails_in_a_row": 0 if ok else int(prev.get("fails_in_a_row", 0)) + 1,
        }
        runs[source] = entry
        cache.write_json(path, runs)
    except Exception:                                             # noqa: BLE001
        pass


def status(path: str = PATH, now: datetime | None = None) -> dict:
    """Every source, with an explicit verdict on whether it is current."""
    runs = cache.read_json(path) or {}
    now = now or datetime.now()

    # Every CONFIGURED source, not just the ones with a record. A source that
    # has never run once has no entry at all, so listing only what is recorded
    # leaves it out of the interface entirely -- invisible rather than overdue,
    # which is the precise failure this module exists to prevent. The six
    # report outlets were missing from the first status for exactly this
    # reason while the two RIDEM ones looked healthy.
    try:
        from . import fetch
        for key, src in fetch.SOURCES.items():
            runs.setdefault(key, {"kind": src.get("kind", "report")})
    except Exception:                                             # noqa: BLE001
        pass

    out = []
    for source, e in sorted(runs.items()):
        kind = e.get("kind", "report")
        limit = STALE_AFTER_H.get(kind, 240)
        last_ok = e.get("last_success")
        age_h = None
        if last_ok:
            try:
                age_h = (now - datetime.fromisoformat(last_ok)).total_seconds() / 3600
            except ValueError:
                age_h = None
        # Never succeeded is stale, not unknown: an interface that shows a
        # blank there reads as "fine so far".
        stale = age_h is None or age_h > limit
        out.append({
            "source": source, "kind": kind,
            "last_attempt": e.get("last_attempt"),
            "last_success": last_ok,
            "age_hours": None if age_h is None else round(age_h, 1),
            "stale_after_hours": limit,
            "stale": stale,
            "ok": bool(e.get("ok")),
            "fails_in_a_row": int(e.get("fails_in_a_row", 0)),
            "detail": e.get("detail", ""),
            "ever_ran": bool(e.get("last_attempt")),
        })
    return {
        "sources": out,
        "stale": [r["source"] for r in out if r["stale"]],
        # Tried and failed. A source that has never been asked is overdue,
        # not broken, and calling it failing sends you looking for a fault
        # that is really just a timer that has not fired yet.
        "failing": [r["source"] for r in out if r["ever_ran"] and not r["ok"]],
        "never_run": not out,
    }


def summary_line(st: dict | None = None) -> str:
    st = st or status()
    if st["never_run"] or not any(r["last_success"] for r in st["sources"]):
        return ("No scrape has ever succeeded. The reports and the review "
                "queue are as empty as they look.")
    bad = st["stale"]
    if not bad:
        return "Every source read within its window."
    return "%d source%s overdue: %s" % (
        len(bad), "" if len(bad) == 1 else "s", ", ".join(bad))
