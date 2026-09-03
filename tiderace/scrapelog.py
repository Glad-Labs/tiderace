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

import difflib
import hashlib
import os
from datetime import date, datetime

from . import cache

PATH = os.path.join(os.path.dirname(__file__), "..", "data", "scrape_runs.json")

# How long a source may go unread before the interface says so. Regulations
# are checked daily and a two-day gap means something is broken; the report
# outlets publish weekly, so ten days is a missed edition rather than a fault.
STALE_AFTER_H = {"regulation": 48, "report": 240}


# A diff is kept so the interface can show WHAT moved, not just that
# something did. Bounded, because a site redesign would otherwise put the
# whole page into a JSON file the desk reads on every request.
DIFF_MAX_CHARS = 4000


def _snapshot_path(path: str, source: str) -> str:
    """Where the last-seen text of a source lives, beside the runs file.

    data/cache/snapshots/<source>.txt for the real path, which is inside the
    gitignored cache; a test's temp path gets a temp snapshot dir beside it.
    """
    return os.path.join(os.path.dirname(os.path.abspath(path)),
                        "cache", "snapshots", source + ".txt")


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def record(source: str, kind: str, ok: bool, detail: str = "",
           path: str = PATH, content: str | None = None,
           at: datetime | None = None) -> None:
    """Note one source's outcome. Never raises: a bookkeeping failure must not
    take down the scrape it was bookkeeping.

    `content` is the page as fetched, normalised. Given, this also answers the
    question Matt actually asks of a regulation source -- "did anything change
    at all?" -- which the scrape could not answer before: it re-fetched both
    RIDEM pages every morning and re-derived everything from nothing, with no
    memory of yesterday, so it could say neither "unchanged since the 30th"
    nor "the table moved". The fingerprint is of the text, the date it last
    changed is carried forward across unchanged runs, and a bounded diff of
    the last change is kept so the desk can show what moved.

    The full page is hashed, chrome and all, on purpose. A site redesign will
    read as a change; the diff will show it is chrome, and one glance at
    chrome costs less than a normalisation rule that quietly strips the
    wrong thing. A false "unchanged" is the failure that costs money here.
    """
    try:
        runs = cache.read_json(path) or {}
        prev = runs.get(source) or {}
        # `at` exists for tests: the stamp has second resolution, so two runs
        # inside one second cannot tell "carried the old date" from "stamped
        # a fresh one that happens to match".
        now = (at or datetime.now()).isoformat(timespec="seconds")
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
        # What the page last said, carried across runs that could not read
        # it or did not bring the text. A failed fetch is not a change.
        for k in ("content_sha", "content_changed_on", "content_first_seen", "diff"):
            if k in prev:
                entry[k] = prev[k]
        if ok and content is not None:
            sha = fingerprint(content)
            snap = _snapshot_path(path, source)
            if prev.get("content_sha") is None:
                # First sighting. Not a change, but the clock starts here so
                # "unchanged since" has a date rather than a blank.
                entry.update(content_sha=sha, content_changed_on=now,
                             content_first_seen=now, diff="")
                cache.write_bytes(snap, content.encode("utf-8"))
            elif sha != prev["content_sha"]:
                before = ""
                try:
                    with open(snap, encoding="utf-8") as fh:
                        before = fh.read()
                except OSError:
                    pass
                d = "\n".join(difflib.unified_diff(
                    before.splitlines(), content.splitlines(),
                    "before", "after", lineterm="", n=1))
                entry.update(content_sha=sha, content_changed_on=now,
                             diff=d[:DIFF_MAX_CHARS])
                cache.write_bytes(snap, content.encode("utf-8"))
        runs[source] = entry
        cache.write_json(path, runs)
    except Exception:                                             # noqa: BLE001
        pass


def baseline_moved(row: dict, checked_on: date) -> bool:
    """Did this page change after somebody last transcribed it by hand?

    The limits table is the annual baseline that `regs.py` is typed in from,
    and a change there is the one event that still needs a person -- the
    reconciler only plays notices forward. Nothing watched for it before.
    """
    when = row.get("content_changed_on")
    if not when or when == row.get("content_first_seen"):
        return False        # never seen, or seen once: no change was observed
    try:
        return datetime.fromisoformat(when).date() > checked_on
    except ValueError:
        return False


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
        changed_on = e.get("content_changed_on")
        first_seen = e.get("content_first_seen")
        # A first sighting stamps the date and is not a change: nothing was
        # observed to move. Reporting it as one put "CHANGED today" on the
        # desk and a false alarm about the limits table on the first run.
        observed = bool(changed_on and first_seen and changed_on != first_seen)
        unchanged_days = None
        changed_today = False
        if changed_on:
            try:
                t = datetime.fromisoformat(changed_on)
                unchanged_days = round((now - t).total_seconds() / 86400, 1)
                changed_today = observed and t.date() == now.date()
            except ValueError:
                pass
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
            # Content, as distinct from freshness. A page can be read every
            # morning and not have changed since June; that is the useful fact.
            "content_sha": e.get("content_sha"),
            "content_first_seen": first_seen,
            "content_changed_on": changed_on,
            "change_observed": observed,
            "unchanged_days": unchanged_days,
            "changed_today": changed_today,
            "diff": e.get("diff") or "",
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
