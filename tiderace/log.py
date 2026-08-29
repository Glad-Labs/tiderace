"""The catch log -- the only part of this project that is genuinely scarce.

Tides, weather and trawl surveys are public: anyone can have them, so they are
worth nothing as an edge. What nobody else has is *your outcomes joined to the
conditions that produced them*.

The one design decision that matters here: a log entry snapshots the full
feature vector at the moment and place you fished. "3 bass at Whale Rock on
Tuesday" is a memory. The same line with current speed, stage, water temp,
light phase, pressure trend and moon attached is a training example. Log the
former and you can never fit a model; log the latter and every trip -- including
the blanks -- makes the next forecast better.

Blanks are not failures. A model trained only on good days learns that every
day is good.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime

from . import features, spots

LOG_PATH = os.environ.get(
    "TIDERACE_LOG", os.path.join(os.path.dirname(__file__), "..", "data", "catch_log.jsonl")
)

# What an LLM should pull out of a voice memo or a written fishing report.
# Kept deliberately small: every field is either something you actually know
# or something the physics layer can fill in for you.
EXTRACTION_SCHEMA = {
    "spot": "spot key from `tiderace spots`, or a free-text place name",
    "species": "one of: striped_bass, bluefish, fluke, black_sea_bass, scup, tautog",
    "started_at": "ISO local datetime the session began",
    "ended_at": "ISO local datetime the session ended (optional)",
    "count": "number of fish landed (0 is a valid and useful answer)",
    "biggest_in": "length of the largest fish in inches (optional)",
    "method": "e.g. 'live eel on 3-way', 'bucktail + trailer', 'diamond jig'",
    "bait_observed": "e.g. 'peanut bunker', 'silversides', 'squid', 'none seen'",
    "notes": "anything else -- water clarity, boat traffic, birds, other anglers",
    "confidence": "high | medium | low -- how sure the extractor is about the above",
    "decided_by": "angler | app -- did you pick this spot, or did the forecast? "
                  "Without this the model cannot be told apart from its own influence.",
}


@dataclass
class Entry:
    spot: str
    species: str
    started_at: str
    count: int
    ended_at: str | None = None
    biggest_in: float | None = None
    method: str | None = None
    bait_observed: str | None = None
    notes: str | None = None
    source: str = "manual"          # manual | voice | report
    decided_by: str = "angler"      # angler | app -- who picked the spot
    confidence: str = "high"
    conditions: dict = field(default_factory=dict)
    logged_at: str = ""


def snapshot(spot_key: str, when: datetime, species: str | None = None) -> dict:
    """Freeze the physical conditions at a spot and time.

    Called at log time so the training example is complete even if NOAA later
    revises or retires the station.
    """
    spot = spots.get(spot_key)
    rows = features.build(spot, when.replace(minute=0, second=0, microsecond=0),
                          hours=2, step_minutes=30, species=species)
    if not rows:
        return {}
    row = min(rows, key=lambda r: abs((r["time"] - when).total_seconds()))
    return {k: v for k, v in row.items()
            if k not in ("time", "spot") and not isinstance(v, datetime)}


def record(entry: Entry, path: str = LOG_PATH) -> Entry:
    if not entry.conditions:
        try:
            entry.conditions = snapshot(entry.spot,
                                        datetime.fromisoformat(entry.started_at),
                                        entry.species)
        except Exception:
            entry.conditions = {}
    entry.logged_at = datetime.now().isoformat(timespec="seconds")

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a") as fh:
        fh.write(json.dumps(asdict(entry)) + "\n")
    return entry


def load(path: str = LOG_PATH) -> list[dict]:
    if not os.path.exists(path):
        return []
    out = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def summary(path: str = LOG_PATH) -> dict:
    rows = load(path)
    if not rows:
        return {"trips": 0}
    by_species: dict[str, dict] = {}
    for r in rows:
        b = by_species.setdefault(r["species"], {"trips": 0, "fish": 0, "blanks": 0})
        b["trips"] += 1
        b["fish"] += r.get("count") or 0
        if not r.get("count"):
            b["blanks"] += 1
    return {
        "trips": len(rows),
        "fish": sum(r.get("count") or 0 for r in rows),
        "blanks": sum(1 for r in rows if not r.get("count")),
        "by_species": by_species,
        "ready_to_fit": len(rows) >= 60,
    }
