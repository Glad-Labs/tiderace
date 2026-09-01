"""A camera roll into draft trips.

The catch log has two rows in it. `voicelog` attacked that by removing the
keyboard from the boat; this attacks the other half of the problem, which is
the trip you meant to log and didn't. Those trips are not lost -- you
photographed them. A phone photo already carries the coordinate and the
second it was taken, so an evening spent pointing this at last month's camera
roll reconstructs sessions that were never written down.

**Where the reconstruction stops, and why.**

EXIF is measurement and the model is a guess, so they are never allowed to
touch the same field:

    where, when   <- the camera. Never inferred, never overridden.
    which fish    <- the vision model, then checked against the species we
                     actually model, and dropped if it is not one of them.
    how many      <- NOBODY. See below.

**Count is never filled in from photos, and this is the whole safety
property of this module.** People photograph the good one. A twenty-fish
morning produces two pictures and a blank morning produces a sunrise, so any
count derived from image content is systematically wrong in the direction
that flatters the day. The log's entire value is that it contains honest
blanks -- `evaluate` treats them as half its signal -- and a fabricated count
is indistinguishable from a real one six months later. So the drafts come
back with `count: None` and the form will not save until a human types it.

What the photos *do* give, which nothing else does, is **effort**: first
frame to last frame is a measured lower bound on how long you were out.
Public catch data has no effort term at all, which is a large part of why it
cannot be used for ranking.

A photo with no fish in it is not a failure either. It is how a blank gets
logged: the sunrise you shot at 05:40 off Beavertail proves you were there,
and the empty catch is the point.

Nothing here writes to the log. Same rule as `voicelog`, same reason.
"""

from __future__ import annotations

import base64
import os
from datetime import datetime, timedelta

from . import exif, llm, score, spots, stations

# Extensions worth opening. HEIC is included because it is what an iPhone
# shoots by default, even though `exif` can only scan rather than parse it.
PHOTO_EXT = {".jpg", ".jpeg", ".jpe", ".heic", ".heif", ".png", ".tif", ".tiff"}

# Frames further apart than this are different sessions. Three hours is long
# enough to cover a slow morning with no fish between pictures, and short
# enough that the evening trip does not merge into the dawn one.
SESSION_GAP_H = 3.0
# ...and further apart than this are different places, however close in time.
SESSION_RADIUS_NM = 2.0

# Narragansett Bay and the south shore, generously. A photo from a holiday in
# Florida should not quietly become a bay trip; this warns rather than
# rejects, because the coordinate might be a legitimate trip out of area.
AREA = (40.9, -71.9, 42.1, -70.8)          # south, west, north, east

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["fish_visible", "confidence"],
    "properties": {
        "fish_visible": {"type": "boolean"},
        "species": {
            "type": "string",
            # Constrained to what the rest of the project models. A grammar
            # cannot stop the model being wrong, but it can stop it inventing
            # a fish that has no profile, no regulations and no thermal curve.
            "enum": sorted(score.PROFILES) + ["unknown", "other"],
        },
        "held_up": {"type": "boolean"},
        "scene": {"type": "string"},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
    },
}

SYSTEM = """You identify fish in a photograph taken by a saltwater angler in
Rhode Island. You are one step in a logging tool, not a naturalist.

Answer only about what is actually visible in this image.

* fish_visible: is there a fish in the picture at all? A photo of the water,
  a sunrise, a boat, bait in a bucket or an empty net is fish_visible false.
  That is a completely normal answer and it is useful — it records that the
  angler was out.
* species: only if you can actually tell. These are the fish that matter here:
    striped_bass    silver flanks with seven or eight solid horizontal black
                    stripes running nose to tail; forked tail
    bluefish        blue-green back, blunt forehead, obvious sharp teeth,
                    single dark blotch at the pectoral base
    fluke           flatfish lying on its side, BOTH eyes on the left side as
                    you look at it with the head up; large mouth
    black_sea_bass  stocky, dark charcoal or blue-black, high rounded
                    forehead on larger males, long dorsal fin
    scup            deep-bodied, compressed, silvery with a faint purple
                    sheen, small mouth; much smaller than a sea bass
    tautog          blunt rubbery lips, mottled dark green-brown, thick
                    body; looks like it lives in rocks
  If it is a fish but you cannot place it, say "unknown". If it is clearly a
  fish that is not on this list, say "other". Do not guess between two
  candidates — "unknown" costs nothing and a wrong species poisons a
  training row.
* held_up: is a person holding the fish up for the camera? This usually means
  it was kept or at least measured.
* scene: a short plain description, under twelve words. "striper held over
  the gunwale at dawn", "empty net on a rocky shore", "bunker schooled at the
  surface".

Never estimate a length. Never estimate how many fish were caught. You are
looking at one photograph, not at the day."""


def _b64(path: str, cap: int = 12 * 1024 * 1024) -> str:
    size = os.path.getsize(path)
    if size > cap:
        raise ValueError(f"{os.path.basename(path)} is {size/1e6:.0f} MB, too big to send")
    with open(path, "rb") as fh:
        return base64.b64encode(fh.read()).decode("ascii")


def look(path: str, backend: llm.Backend | None = None) -> dict:
    """What one photograph shows. No EXIF, no judgement about the trip."""
    backend = backend or llm.Ollama(llm.DEFAULT_VISION_MODEL)
    out = backend.complete(
        SYSTEM,
        "Describe this photograph using the fields. Only what you can see.",
        SCHEMA, images=[_b64(path)])
    sp = out.get("species")
    if sp in ("unknown", "other", "", None) or sp not in score.PROFILES:
        out.pop("species", None)
    if not out.get("fish_visible"):
        # A model that says "no fish" and then names one is contradicting
        # itself; trust the boolean, which is the easier judgement.
        out.pop("species", None)
    return out


def scan(paths: list[str]) -> tuple[list[dict], list[dict]]:
    """Read EXIF from every photo. Returns (usable, skipped)."""
    usable, skipped = [], []
    for p in sorted(paths):
        if os.path.splitext(p)[1].lower() not in PHOTO_EXT:
            continue
        try:
            meta = exif.read(p)
        except (exif.NoExif, OSError, ValueError) as e:
            skipped.append({"file": os.path.basename(p), "path": p,
                            "why": str(e)})
            continue
        if not meta["has_time"]:
            skipped.append({"file": meta["file"], "path": p,
                            "why": "no capture time — nothing to place it on "
                                   "a tide with"})
            continue
        meta["path"] = p
        usable.append(meta)
    usable.sort(key=lambda m: m["taken_at"])
    return usable, skipped


def sessions(photos: list[dict]) -> list[list[dict]]:
    """Split a sorted photo list into trips.

    A new session starts on a long enough gap in time, or on a jump in
    distance -- running from the bay to the south shore mid-morning is two
    trips even with ten minutes between frames.
    """
    out: list[list[dict]] = []
    for m in photos:
        if not out:
            out.append([m]); continue
        prev = out[-1][-1]
        gap = (datetime.fromisoformat(m["taken_at"])
               - datetime.fromisoformat(prev["taken_at"])).total_seconds() / 3600
        moved = 0.0
        if m["has_gps"] and prev["has_gps"]:
            moved = stations.distance_nm(prev["lat"], prev["lon"],
                                         m["lat"], m["lon"])
        if gap > SESSION_GAP_H or moved > SESSION_RADIUS_NM:
            out.append([m])
        else:
            out[-1].append(m)
    return out


def _place(group: list[dict]) -> tuple[float | None, float | None, str | None, list[str]]:
    """Where the session was, and the nearest known spot if there is one."""
    fixes = [(m["lat"], m["lon"]) for m in group if m["has_gps"]]
    warn: list[str] = []
    if not fixes:
        return None, None, None, ["no photo in this session carries a GPS fix"]
    lat = sum(f[0] for f in fixes) / len(fixes)
    lon = sum(f[1] for f in fixes) / len(fixes)
    if not (AREA[0] <= lat <= AREA[2] and AREA[1] <= lon <= AREA[3]):
        warn.append(f"{lat:.4f},{lon:.4f} is outside the modelled area — "
                    "conditions for it will be thin or wrong")
    if len(fixes) < len(group):
        warn.append(f"{len(group) - len(fixes)} of {len(group)} photos had no "
                    "GPS; position is the mean of the rest")

    best, best_nm = None, 1e9
    for s in spots.SPOTS:
        d = stations.distance_nm(lat, lon, s.lat, s.lon)
        if d < best_nm:
            best, best_nm = s, d
    # Half a mile. Beyond that it is a different piece of ground, and
    # inheriting a spot's current station would be worse than using none.
    key = best.key if best and best_nm <= 0.5 else None
    return round(lat, 6), round(lon, 6), key, warn


def draft(paths: list[str], backend: llm.Backend | None = None,
          identify: bool = True) -> dict:
    """Camera roll in, draft trips out. Never writes to the log."""
    photos, skipped = scan(paths)
    backend = backend or (llm.Ollama(llm.DEFAULT_VISION_MODEL) if identify else None)

    trips = []
    for group in sessions(photos):
        lat, lon, spot_key, warn = _place(group)
        seen: dict[str, int] = {}
        shots = []
        for m in group:
            shot = {"file": m["file"], "taken_at": m["taken_at"],
                    "lat": m["lat"], "lon": m["lon"]}
            if not m["exact"]:
                shot["exif_scanned"] = True
            if identify:
                try:
                    shot.update(look(m["path"], backend))
                except Exception as e:                            # noqa: BLE001
                    shot["error"] = f"{type(e).__name__}: {e}"
            if shot.get("species"):
                seen[shot["species"]] = seen.get(shot["species"], 0) + 1
            shots.append(shot)

        start = datetime.fromisoformat(group[0]["taken_at"])
        end = datetime.fromisoformat(group[-1]["taken_at"])
        # First frame to last frame. A lower bound on the session and the only
        # effort measurement available anywhere -- but only a real one if more
        # than one photo was taken.
        span = (end - start) if len(group) > 1 else timedelta(0)

        trips.append({
            "started_at": start.isoformat(timespec="minutes"),
            "ended_at": end.isoformat(timespec="minutes") if span else None,
            "span_minutes": int(span.total_seconds() // 60) or None,
            "lat": lat, "lon": lon,
            "spot": spot_key or (f"at:{lat:.5f},{lon:.5f}" if lat is not None else None),
            # count is deliberately absent from every entry. See the module
            # docstring: it is the one field a photograph cannot honestly fill.
            "catch": [{"species": s, "count": None, "photos_showing": n}
                      for s, n in sorted(seen.items(), key=lambda kv: -kv[1])]
                     or [{"species": None, "count": None, "photos_showing": 0}],
            "photos": shots,
            "fish_in_any_photo": any(s.get("fish_visible") for s in shots),
            "notes": "; ".join(
                dict.fromkeys(s["scene"] for s in shots if s.get("scene")))[:300],
            "source": "photo",
            "warnings": warn,
        })

    return {"trips": trips, "skipped": skipped,
            "photos_read": len(photos),
            "identified": identify}
