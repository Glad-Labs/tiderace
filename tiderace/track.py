"""Where you actually were, so a trip gets logged whether or not you remember.

The catch log depends on discipline, and discipline is worst exactly when the
data is most valuable. Nobody forgets to log four keepers. Everybody forgets to
log the blank -- and blanks are half of what the evaluation harness has to work
with, because a model trained only on good days learns that every day is good.

A track fixes that by being passive. The phone records where it went; at the
end there is a trip whether or not anyone typed anything, with the conditions
that were actually present rather than the ones at the moment you remembered.

**Dwell is the interesting part, not the line.** A track is mostly transit --
running out, running home, moving between pieces. What matters is where the
boat stopped, because a boat stopped is a boat fishing. So the line is reduced
to dwell segments, and it is those, not the midpoint of the whole track, that
become candidate positions for a log entry. The midpoint of a Charlestown trip
is somewhere in the middle of the breachway channel, which is where you drove,
not where you fished.

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

# A boat holding station on a piece is not perfectly still -- it swings on the
# anchor, it drifts and gets repositioned. These are what separate "working a
# spot" from "running somewhere".
DWELL_RADIUS_NM = 0.12          # ~220 m: a drift, not a passage
DWELL_MIN_MINUTES = 6           # shorter than this is a look, not a session
MOVING_KT = 2.5                 # above this the boat is going somewhere


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


def dwells(points: list[dict]) -> list[dict]:
    """The places the boat stopped, which is where the fishing happened.

    Greedy: walk the track, and keep extending the current cluster while the
    next fix is still within DWELL_RADIUS_NM of its centre. That is enough for
    a boat working one piece and correctly refuses to merge two spots half a
    mile apart into one long average.
    """
    pts = clean(points)
    if len(pts) < 2:
        return []

    out, i = [], 0
    while i < len(pts):
        clat, clon = pts[i]["lat"], pts[i]["lon"]
        j = i + 1
        while j < len(pts) and _nm(clat, clon, pts[j]["lat"], pts[j]["lon"]) <= DWELL_RADIUS_NM:
            # Re-centre as it grows, so a slow drift stays one dwell instead of
            # falling out of a circle pinned to where it started.
            n = j - i + 1
            clat += (pts[j]["lat"] - clat) / n
            clon += (pts[j]["lon"] - clon) / n
            j += 1
        span = (_when(pts[j - 1]) - _when(pts[i])).total_seconds() / 60.0
        if span >= DWELL_MIN_MINUTES:
            out.append({
                "lat": round(clat, 6), "lon": round(clon, 6),
                "from": pts[i]["t"], "to": pts[j - 1]["t"],
                "minutes": round(span, 1), "fixes": j - i,
            })
        i = max(j, i + 1)
    return out


def summarise(points: list[dict]) -> dict:
    """What the track amounts to: how long, how far, and where you stopped."""
    pts = clean(points)
    if not pts:
        return {"points": 0, "dwells": []}
    t0, t1 = _when(pts[0]), _when(pts[-1])
    dist = sum(_nm(pts[k]["lat"], pts[k]["lon"], pts[k + 1]["lat"], pts[k + 1]["lon"])
               for k in range(len(pts) - 1))
    d = dwells(pts)
    return {
        "points": len(pts),
        "started_at": pts[0]["t"],
        "ended_at": pts[-1]["t"],
        "minutes": round((t1 - t0).total_seconds() / 60.0, 1),
        "distance_nm": round(dist, 2),
        "dwells": d,
        # The dwell you spent longest on. Not the midpoint of the track, which
        # is usually the channel you drove down.
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
