"""Where you actually were, so a trip gets logged whether or not you remember.

The catch log depends on discipline, and discipline is worst exactly when the
data is most valuable. Nobody forgets to log four keepers. Everybody forgets to
log the blank -- and blanks are half of what the evaluation harness has to work
with, because a model trained only on good days learns that every day is good.

A track fixes that by being passive. The phone records where it went; at the
end there is a trip whether or not anyone typed anything, with the conditions
that were actually present rather than the ones at the moment you remembered.

**Speed is what separates fishing from travelling, not standing still.** The
first version of this looked for a stationary boat, and that was simply wrong
about how anybody fishes here. A fluke drift covers half a mile in twenty-five
minutes; it got chopped into two "dwells" and the drift itself -- the actual
fishing -- was invisible. Trolling covers miles and would have vanished
entirely.

So a track is cut into segments by speed:

    drift   under 2 kt      drifting, anchored, holding on a piece
    troll   2 to 4.5 kt     trolling, or working slowly along an edge
    run     over 4.5 kt     going somewhere

Everything that is not a run is fishing, and a fishing segment is a *path*, not
a dot. Bottom fishing is usually a sawtooth -- drift down, motor back up, drift
again over the same piece -- so two fishing segments separated by a short run
that ends up back where it started are merged into one session, because that is
one piece of structure being worked, not three.

This is the most sensitive file in the project. A saved mark is one place you
chose to write down; a track is every place you actually fished, in order, with
how long you sat on each. It is gitignored, it never leaves this machine, and
there is deliberately no export.
"""

from __future__ import annotations

import json
import math
import os
from datetime import datetime

from . import cache

TRACK_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "tracks.jsonl")

# Speed bands, in knots. The boundaries are where the boat's behaviour changes
# rather than round numbers: under 2 kt you are going wherever the water goes,
# and over about 4.5 kt you are burning fuel to be somewhere else.
DRIFT_MAX_KT = 2.0
TROLL_MAX_KT = 4.5

# A session shorter than this is a look, not fishing.
SESSION_MIN_MINUTES = 6

# Two drifts over the same piece, with a motor back up in between. The run
# between them is short and ends near where the previous drift began.
REJOIN_MAX_MINUTES = 6
# How close the resumed fishing has to be to ground already covered. A quarter
# mile is a boat repositioning over the same structure; further than that and
# it is a different piece, however briefly you drove there.
REJOIN_MAX_NM = 0.25

def _nm(lat1, lon1, lat2, lon2) -> float:
    """Distance in nautical miles. Longitude scaled by latitude, which matters
    at 41 N where a degree of longitude is three quarters of a degree of lat."""
    k = math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot((lat2 - lat1) * 60, (lon2 - lon1) * 60 * k)


def _when(p) -> datetime | None:
    try:
        return datetime.fromisoformat(str(p["t"]).replace("Z", ""))
    except (KeyError, TypeError, ValueError):
        return None


def clean(points: list[dict]) -> list[dict]:
    """Drop the fixes that are noise rather than movement.

    Phone GPS produces occasional wild outliers -- a fix that puts you a mile
    inland for one sample. Left in, one of those turns a dwell into a passage
    and hides the spot. Anything implying a speed no small boat reaches is
    dropped rather than smoothed, because the honest thing to do with a bad fix
    is discard it, not average it into the good ones.
    """
    out: list[dict] = []
    for p in points:
        if not isinstance(p, dict) or "lat" not in p or "lon" not in p:
            continue
        t = _when(p)
        if t is None:
            continue
        if out:
            prev = out[-1]
            dt = (t - _when(prev)).total_seconds() / 3600.0
            if dt <= 0:
                continue                       # out of order or duplicate
            kt = _nm(prev["lat"], prev["lon"], p["lat"], p["lon"]) / dt
            if kt > 60:                        # not a boat
                continue
        out.append({"lat": round(float(p["lat"]), 6),
                    "lon": round(float(p["lon"]), 6),
                    "t": t.isoformat(timespec="seconds")})
    return out


def _legs(pts: list[dict]) -> list[dict]:
    """Each step between fixes, with the speed it implies."""
    out = []
    for a, b in zip(pts, pts[1:]):
        hrs = (_when(b) - _when(a)).total_seconds() / 3600.0
        if hrs <= 0:
            continue
        d = _nm(a["lat"], a["lon"], b["lat"], b["lon"])
        out.append({"a": a, "b": b, "nm": d, "kt": d / hrs})
    return out


def kind_of(kt: float) -> str:
    """What the boat is doing at this speed."""
    if kt <= DRIFT_MAX_KT:
        return "drift"
    if kt <= TROLL_MAX_KT:
        return "troll"
    return "run"


def _finish(pts: list[dict]) -> dict:
    """Turn a run of fixes into a session record.

    Carries the whole path, not just a centre. A drift is a line -- where it
    started and where it ended are both real information, and a half-mile drift
    reduced to its midpoint loses which end of the piece produced the fish.
    """
    t0, t1 = _when(pts[0]), _when(pts[-1])
    nm = sum(_nm(a["lat"], a["lon"], b["lat"], b["lon"])
             for a, b in zip(pts, pts[1:]))
    mins = (t1 - t0).total_seconds() / 60.0
    kt = (nm / (mins / 60.0)) if mins > 0 else 0.0
    return {
        "kind": "troll" if kt > DRIFT_MAX_KT else "drift",
        "lat": round(sum(p["lat"] for p in pts) / len(pts), 6),
        "lon": round(sum(p["lon"] for p in pts) / len(pts), 6),
        "start": [pts[0]["lat"], pts[0]["lon"]],
        "end": [pts[-1]["lat"], pts[-1]["lon"]],
        "path": [[p["lat"], p["lon"]] for p in pts],
        "from": pts[0]["t"], "to": pts[-1]["t"],
        "minutes": round(mins, 1), "fixes": len(pts),
        "distance_nm": round(nm, 2), "avg_kt": round(kt, 2),
    }


def sessions(points: list[dict]) -> list[dict]:
    """The stretches where you were fishing, drifting or trolling included.

    Anything that is not a run counts. Consecutive fishing legs accumulate; a
    run ends the session -- unless it is a short one that comes back to where
    the last drift started, which is a reset for another pass over the same
    piece and belongs to the same session.
    """
    pts = clean(points)
    if len(pts) < 2:
        return []

    out: list[dict] = []
    cur: list[dict] = []
    pending_run: list[dict] = []

    def close():
        nonlocal cur, pending_run
        if cur:
            s = _finish(cur)
            if s["minutes"] >= SESSION_MIN_MINUTES:
                out.append(s)
        cur, pending_run = [], []

    for leg in _legs(pts):
        if kind_of(leg["kt"]) != "run":
            if pending_run:
                # A run happened, and now we are fishing again. Was it a motor
                # back up over the same ground, or did we leave?
                # Did we come back over ground we already worked? Measured
                # against the whole path, not the session's start: a drift is
                # half a mile long, so "near where this started" is a poor
                # proxy for "the same piece" -- it is both too strict at the
                # far end of a long drift and too loose for a second wreck
                # that happens to sit near the first one's beginning.
                back = min((_nm(q["lat"], q["lon"],
                                leg["a"]["lat"], leg["a"]["lon"])
                            for q in cur), default=999)
                gap = (_when(pending_run[-1]["b"]) -
                       _when(pending_run[0]["a"])).total_seconds() / 60.0
                if cur and gap <= REJOIN_MAX_MINUTES and back <= REJOIN_MAX_NM:
                    cur.extend([leg["a"]])      # same piece, keep going
                else:
                    close()
                pending_run = []
            if not cur:
                cur = [leg["a"]]
            cur.append(leg["b"])
        else:
            pending_run.append(leg)
            # A long run means we have genuinely left; end it now rather than
            # waiting to see whether fishing resumes.
            gap = (_when(pending_run[-1]["b"]) -
                   _when(pending_run[0]["a"])).total_seconds() / 60.0
            if gap > REJOIN_MAX_MINUTES:
                close()
    close()
    return out


# Kept as the old name so nothing that used it breaks; sessions is the honest
# word now, because most of these are moving.
def dwells(points: list[dict]) -> list[dict]:
    return sessions(points)


def summarise(points: list[dict]) -> dict:
    """What the track amounts to: how long, how far, and where you stopped."""
    pts = clean(points)
    if not pts:
        return {"points": 0, "dwells": []}
    t0, t1 = _when(pts[0]), _when(pts[-1])
    dist = sum(_nm(pts[k]["lat"], pts[k]["lon"], pts[k + 1]["lat"], pts[k + 1]["lon"])
               for k in range(len(pts) - 1))
    d = sessions(pts)
    return {
        "points": len(pts),
        "started_at": pts[0]["t"],
        "ended_at": pts[-1]["t"],
        "minutes": round((t1 - t0).total_seconds() / 60.0, 1),
        "distance_nm": round(dist, 2),
        "sessions": d,
        "dwells": d,                    # old name, same list
        "fishing_minutes": round(sum(x["minutes"] for x in d), 1),
        # The session you spent longest in. Not the midpoint of the track,
        # which is usually the channel you drove down.
        "best": max(d, key=lambda x: x["minutes"]) if d else None,
    }


def record(points: list[dict], path: str = TRACK_PATH) -> dict:
    """Append one finished track. Local file, never anywhere else."""
    s = summarise(points)
    if not s.get("points"):
        return s
    row = {"logged_at": datetime.now().isoformat(timespec="seconds"), **s,
           "points": points if isinstance(points, list) else []}
    row["point_count"] = s["points"]
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "a") as fh:
        fh.write(json.dumps(row) + "\n")
    return s


def load(path: str = TRACK_PATH) -> list[dict]:
    if not os.path.exists(path):
        return []
    out = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except ValueError:
                    continue                   # a torn line is not worth dying over
    return out
