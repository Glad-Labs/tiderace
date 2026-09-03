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

from . import config as cfgmod
from . import features, spots

LOG_PATH = os.environ.get(
    "TIDERACE_LOG", os.path.join(os.path.dirname(__file__), "..", "data", "catch_log.jsonl")
)
# Photos of the fish, kept beside the log. Same tier of privacy as the log
# itself: a catch photo carries the coordinate it was taken at in its EXIF,
# which is the one thing this project has never shared. Gitignored, served
# only to the page over the tailnet, never transmitted anywhere else.
PHOTO_DIR = os.environ.get(
    "TIDERACE_PHOTOS", os.path.join(os.path.dirname(__file__), "..", "data", "photos")
)
PHOTO_MAX_BYTES = 4 * 1024 * 1024     # the page shrinks to ~0.3 MB; this is slack
PHOTOS_PER_ENTRY = 6

# What an LLM should pull out of a voice memo or a written fishing report.
# Kept deliberately small: every field is either something you actually know
# or something the physics layer can fill in for you.
EXTRACTION_SCHEMA = {
    "spot": "spot key from `tiderace spots`, or a free-text place name",
    "lat": "decimal latitude, if the report gives one (optional)",
    "lon": "decimal longitude, negative in Rhode Island (optional)",
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
    # Where, exactly. A spot key is a label and labels drift -- "the reef" is
    # four different rocks over a season. The coordinate is what a future
    # fitted model can actually group on, so it is recorded on every entry,
    # filled in from the spot when the trip was logged against a known one.
    lat: float | None = None
    lon: float | None = None
    # One row per species, and rows from the same session share a trip_id.
    # Bottom fishing produces sea bass, scup and tautog in one afternoon on one
    # piece of structure -- three catches, one trip. Keeping a row per species
    # is what `evaluate` needs (it correlates each species against its own
    # score), and the trip_id is what stops three rows being counted as three
    # separate outings when anything asks how often you go.
    trip_id: str | None = None
    source: str = "manual"          # manual | voice | report
    decided_by: str = "angler"      # angler | app -- who picked the spot
    # Which rules applied to this trip. Recorded rather than inferred: RI
    # commercial licences are issued to a named individual, and a log that
    # cannot say which licence a trip belonged to is no use as a record.
    license_mode: str = "recreational"
    license_holder: str | None = None
    confidence: str = "high"
    conditions: dict = field(default_factory=dict)
    logged_at: str = ""
    # Paths under PHOTO_DIR, relative, of the photos saved with this trip.
    # Older rows have no field and load as an empty list downstream.
    photos: list[str] = field(default_factory=list)


def snapshot(spot_key: str | None, when: datetime, species: str | None = None,
             lat: float | None = None, lon: float | None = None) -> dict:
    """Freeze the physical conditions at a spot and time.

    Called at log time so the training example is complete even if NOAA later
    revises or retires the station. A coordinate is resolved to its stations
    the same way `tiderace at` does, so a trip logged at a mark carries the
    same feature vector as one logged at a named spot.
    """
    if lat is not None and lon is not None:
        spot, _ = spots.at_coord(lat, lon)
    else:
        spot = spots.get(spot_key)
    rows = features.build(spot, when.replace(minute=0, second=0, microsecond=0),
                          hours=2, step_minutes=30, species=species)
    if not rows:
        return {}
    row = min(rows, key=lambda r: abs((r["time"] - when).total_seconds()))
    return {k: v for k, v in row.items()
            if k not in ("time", "spot") and not isinstance(v, datetime)}


# Two taps on a phone are one intention. A double-tap on the save button wrote
# a real trip and then a blank three seconds later at the same coordinate, and
# the blank went into a log with three entries in it -- a 33% corruption of the
# scarcest data in the project. The client is now guarded too, but the log is
# the thing that has to be right, so it refuses the duplicate itself.
#
# Deliberately narrow: same spot, same species, same count, within a minute.
# Two genuinely separate drifts on one piece of water an hour apart are two
# trips and must both survive.
DUPLICATE_WINDOW_S = 60


class DuplicateEntry(ValueError):
    """A trip that looks like the previous one submitted seconds ago."""


def _is_duplicate(entry: Entry, rows: list[dict]) -> bool:
    # Count is deliberately NOT compared. The double-tap that started this
    # wrote 2 fish and then a blank at the same coordinate three seconds later,
    # so a rule keyed on matching counts would have missed the only case it
    # exists to catch. Same water, same fish, seconds apart is one intention
    # however the numbers came out.
    if not rows:
        return False
    last = rows[-1]
    if last.get("spot") != entry.spot or last.get("species") != entry.species:
        return False
    try:
        prev = datetime.fromisoformat(last["logged_at"])
    except (KeyError, ValueError):
        return False
    # entry.logged_at is already set by the caller; using it rather than "now"
    # keeps a queued offline flush honest -- those arrive together but describe
    # trips minutes or hours apart.
    try:
        this = datetime.fromisoformat(entry.logged_at)
    except (TypeError, ValueError):
        this = datetime.now()
    return abs((this - prev).total_seconds()) <= DUPLICATE_WINDOW_S


def record(entry: Entry, path: str = LOG_PATH) -> Entry:
    # A trip logged against a known spot still gets its coordinate written
    # down. Spot keys can be renamed or retired; 41.4408,-71.4228 cannot.
    if entry.lat is None or entry.lon is None:
        try:
            known = spots.get(entry.spot)
            entry.lat, entry.lon = known.lat, known.lon
        except KeyError:
            pass

    if not entry.conditions:
        try:
            entry.conditions = snapshot(entry.spot,
                                        datetime.fromisoformat(entry.started_at),
                                        entry.species, entry.lat, entry.lon)
        except Exception:
            entry.conditions = {}
    cfg = cfgmod.load()
    if entry.license_mode == "recreational" and cfg["license_mode"] != "recreational":
        entry.license_mode = cfg["license_mode"]
    if entry.license_holder is None:
        entry.license_holder = cfg.get("license_holder")
    entry.logged_at = datetime.now().isoformat(timespec="seconds")

    # Checked here rather than in the caller so every route in -- the web form,
    # a queued offline flush, the CLI -- is covered by the same rule.
    if _is_duplicate(entry, load(path)):
        raise DuplicateEntry(
            f"a {entry.species} trip with {entry.count} fish was already logged "
            f"at {entry.spot} moments ago — not saving it twice")

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a") as fh:
        fh.write(json.dumps(asdict(entry)) + "\n")
    return entry


def record_trip(entries: list[Entry], path: str = LOG_PATH) -> list[Entry]:
    """One session, several species. Writes a row each, sharing a trip id.

    The conditions snapshot is taken once and copied, not recomputed per row:
    they were all caught in the same water at the same time, and three
    independent snapshots would differ by whatever the tide did while the loop
    ran.
    """
    import uuid
    if not entries:
        return []
    tid = entries[0].trip_id or uuid.uuid4().hex[:12]
    first = entries[0]
    if not first.conditions:
        try:
            first.conditions = snapshot(
                first.spot, datetime.fromisoformat(first.started_at),
                first.species, first.lat, first.lon)
        except Exception:                                         # noqa: BLE001
            first.conditions = {}
    out = []
    for e in entries:
        e.trip_id = tid
        if not e.conditions:
            e.conditions = dict(first.conditions)
        out.append(record(e, path))
    return out


def store_photos(blobs: list[bytes], when: datetime | None = None,
                 root: str | None = None) -> list[str]:
    """Keep photos of the fish beside the log. Returns their relative paths.

    JPEG only, because that is what a phone produces and what photolog can
    read EXIF out of; a PNG screenshot of a photo is not a photo of a fish.
    Each file is created by mkstemp -- atomically, owner-only -- and moved
    into its final name with os.replace, so a torn write is a temp file and
    never a half photo under a real name. A failure part-way removes what
    this call already wrote: the entry is not saved, so its photos must not
    be either.
    """
    import tempfile
    import uuid
    root = root or PHOTO_DIR
    if len(blobs) > PHOTOS_PER_ENTRY:
        raise ValueError(f"{len(blobs)} photos on one trip; keep it to "
                         f"{PHOTOS_PER_ENTRY}")
    day = (when or datetime.now()).strftime("%Y-%m-%d")
    stamp = uuid.uuid4().hex[:10]
    folder = os.path.join(root, day)
    os.makedirs(folder, exist_ok=True)
    out: list[str] = []
    try:
        for i, b in enumerate(blobs):
            if b[:2] != b"\xff\xd8":
                raise ValueError(f"photo {i + 1} is not a JPEG")
            if len(b) > PHOTO_MAX_BYTES:
                raise ValueError(f"photo {i + 1} is {len(b) / 1048576:.1f} MB; "
                                 f"the limit is {PHOTO_MAX_BYTES // 1048576} MB")
            rel = f"{day}/{stamp}-{i}.jpg"
            fd, tmp = tempfile.mkstemp(prefix=".tmp-", suffix=".jpg", dir=folder)
            try:
                view = memoryview(b)
                while view:
                    n = os.write(fd, view)
                    view = view[n:]
            finally:
                os.close(fd)
            os.replace(tmp, os.path.join(root, rel))
            out.append(rel)
    except BaseException:
        discard_photos(out, root)
        raise
    return out


def discard_photos(rels: list[str], root: str | None = None) -> None:
    """Remove photos whose entry did not make it into the log."""
    root = root or PHOTO_DIR
    for rel in rels:
        p = photo_path(rel, root)
        if p:
            try:
                os.unlink(p)
            except OSError:
                pass


def photo_path(rel: str, root: str | None = None) -> str | None:
    """The file for a relative path, or None if it is missing or the path
    tries to leave the photo directory."""
    base = os.path.abspath(root or PHOTO_DIR)
    p = os.path.abspath(os.path.join(base, os.path.normpath(rel or "")))
    if not p.startswith(base + os.sep) or not os.path.isfile(p):
        return None
    return p


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
