"""Place names that resolve to a coordinate, from public sources.

Matt, 5 September 2026: "landmark naming should be searchable based on maps
shouldn't it?" It should. The curated list of nineteen named spots went on
3 September because the RANKING must not depend on anybody's list; a voice
note that says "three bass off Beavertail" is a different thing, and losing
the ability to put that on the chart was a cost this file pays back.

Two sources, both public, both already public knowledge:

  charts     the ENC layers this app caches carry names on 66 rocks, one
             obstruction and every one of 452 buoys -- "Seal Rock",
             "Dennison Rock", "Wicopesset Rock Buoy 7". Offline, no fetch.
  GNIS       the USGS Geographic Names Information System, the federal
             gazetteer, public domain. Points, islands, bays, beaches, bars,
             rocks (GNIS calls a sea rock a "Pillar"), channels and towns for
             Rhode Island, Massachusetts and Connecticut, clipped to the
             charted box. `refresh()` downloads the three state files and
             writes data/gazetteer.json (gitignored, regenerable, like
             stations.json) so the boat has it without signal.

Nothing here ranks anything. A name resolves to a coordinate and the rest of
the app treats that coordinate like any other. The matcher is deliberately
conservative -- an unmatched sighting is better than one pinned to the wrong
rock -- so generic words alone ("the point", "the reef") never match, and a
tie between two features goes to the more specific kind: a rock before a
point, a point before a bay, a bay before a town.
"""

from __future__ import annotations

import io
import json
import os
import re
import urllib.request
import zipfile

CHART_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "charts")
GNIS_PATH = os.environ.get(
    "TIDERACE_GAZETTEER",
    os.path.join(os.path.dirname(__file__), "..", "data", "gazetteer.json"))

GNIS_URL = ("https://prd-tnm.s3.amazonaws.com/StagedProducts/GeographicNames/"
            "DomesticNames/DomesticNames_{state}_Text.zip")
GNIS_STATES = ("RI", "MA", "CT")
# The charted box plus a margin: Fishers Island to the Elizabeths.
GNIS_BBOX = (40.9, -72.3, 42.0, -70.4)          # south, west, north, east
# GNIS feature classes worth a coordinate on the water. "Pillar" is how GNIS
# files a sea rock. Streams and lakes are left out: nobody logs a bass in one.
GNIS_CLASSES = {"Cape", "Pillar", "Island", "Bay", "Bar", "Beach", "Channel",
                "Gut", "Cliff", "Bench", "Bend", "Canal", "Sea", "Harbor",
                "Park", "Military", "Populated Place"}

# Specific kinds first. A "rock" is a place you can hold a boat over; a town
# is somewhere to point at from a mile off; a buoy is named AFTER the place
# it marks ("Newport Harbor Buoy 4"), so it comes last unless the phrase is
# the buoy itself.
KIND_RANK = {"rock": 0, "obstruction": 0, "Pillar": 1, "Bar": 1,
             "Cape": 3, "Island": 3, "Gut": 3, "Channel": 4, "Bend": 4,
             "Cliff": 4, "Bench": 4, "Bay": 5, "Beach": 5, "Harbor": 5,
             "Canal": 5, "Park": 5, "Military": 5, "Sea": 6, "Populated Place": 6,
             "buoy": 8}

# Generic geography carries no identity. Matching on it alone once put
# "Newport Bridge" at the Mount Hope Bridge and "Block Island" -- twelve
# miles offshore -- at Rose Island. Only distinguishing words count.
# "bridge" is NOT generic: GNIS names no bridges here, so a phrase with one
# in it names something the gazetteer lacks, and dropping the word let
# "Newport Bridge area" resolve to Newport Neck, three miles away.
GENERIC = {"island", "point", "harbor", "harbour", "bay", "rock",
           "rocks", "cove", "beach", "river", "reef", "entrance", "pond",
           "north", "south", "east", "west", "upper", "lower", "area",
           "shore", "light", "neck", "hill", "refuge", "breachway", "ledge",
           "buoy", "channel", "the", "off", "near", "at", "by", "outside",
           "inside", "mouth", "head", "sound", "passage"}

UA = "tiderace (+https://github.com/Glad-Labs/tiderace)"

_cache: dict = {}


def _norm(text: str) -> str:
    t = (text or "").lower().replace("'s", "s").replace("’s", "s")
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _tokens(text: str) -> set[str]:
    return {w for w in _norm(text).split() if len(w) > 2 and w not in GENERIC}


def chart_names(chart_dir: str = CHART_DIR) -> list[dict]:
    """Named features off the cached ENC layers. Offline."""
    out = []
    for layer, kind in (("rocks", "rock"), ("obstructions", "obstruction"),
                        ("buoys", "buoy")):
        path = os.path.join(chart_dir, layer + ".geojson")
        if not os.path.exists(path):
            continue
        try:
            with open(path) as fh:
                gj = json.load(fh)
        except (OSError, ValueError):
            continue
        for f in gj.get("features", []):
            props = f.get("properties") or {}
            name = props.get("name") or props.get("OBJNAM")
            g = f.get("geometry") or {}
            if not name or g.get("type") != "Point":
                continue
            lon, lat = g["coordinates"][:2]
            out.append({"name": str(name), "lat": round(float(lat), 5),
                        "lon": round(float(lon), 5), "kind": kind, "source": "chart"})
    return out


def parse_gnis(text: str, bbox=GNIS_BBOX, classes=GNIS_CLASSES) -> list[dict]:
    """One state's pipe-delimited GNIS file, clipped and filtered."""
    south, west, north, east = bbox
    lines = text.lstrip("﻿").splitlines()
    if not lines:
        return []
    hdr = lines[0].split("|")
    try:
        i_name, i_cls = hdr.index("feature_name"), hdr.index("feature_class")
        i_lat, i_lon = hdr.index("prim_lat_dec"), hdr.index("prim_long_dec")
    except ValueError:
        raise ValueError("not a GNIS DomesticNames file: header lacks the expected columns")
    out = []
    for line in lines[1:]:
        f = line.split("|")
        if len(f) <= max(i_name, i_cls, i_lat, i_lon):
            continue
        if f[i_cls] not in classes:
            continue
        try:
            lat, lon = float(f[i_lat]), float(f[i_lon])
        except ValueError:
            continue
        if not (south <= lat <= north and west <= lon <= east):
            continue
        out.append({"name": f[i_name], "lat": round(lat, 5), "lon": round(lon, 5),
                    "kind": f[i_cls], "source": "gnis"})
    return out


def refresh(path: str = GNIS_PATH, states=GNIS_STATES) -> dict:
    """Download the state files and write the clipped gazetteer. Regenerable,
    gitignored; the same shape of cache as stations.json."""
    from . import cache
    rows: list[dict] = []
    for st in states:
        req = urllib.request.Request(GNIS_URL.format(state=st), headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=180) as r:
            blob = r.read()
        z = zipfile.ZipFile(io.BytesIO(blob))
        txt = [n for n in z.namelist() if n.lower().endswith(".txt")]
        if not txt:
            raise ValueError(f"GNIS {st}: no text file in the archive")
        rows.extend(parse_gnis(z.read(txt[0]).decode("utf-8", "replace")))
    out = {"source": GNIS_URL.replace("{state}", "<state>"), "states": list(states),
           "bbox": list(GNIS_BBOX), "classes": sorted(GNIS_CLASSES), "names": rows}
    cache.write_json(path, out)
    _cache.clear()
    return {"path": path, "names": len(rows)}


def gnis_names(path: str = GNIS_PATH) -> list[dict]:
    if not os.path.exists(path):
        return []
    try:
        with open(path) as fh:
            return json.load(fh).get("names", [])
    except (OSError, ValueError):
        return []


def names(chart_dir: str = CHART_DIR, gnis_path: str = GNIS_PATH) -> list[dict]:
    key = (chart_dir, gnis_path)
    if key not in _cache:
        _cache[key] = chart_names(chart_dir) + gnis_names(gnis_path)
    return _cache[key]


def resolve(place: str, candidates: list[dict] | None = None) -> dict | None:
    """The best public feature for a place said in prose, or None.

    Exact name first. Then a two-word-or-longer feature name contained in
    the phrase, longest first -- but never a town that way, because "the
    Mount Hope Bridge" contains the name of a town in Connecticut and the
    bay of the same name is what was meant. Then the phrase contained in a
    name, shortest first, so "Whale Rock" beats "Whale Rock Light". Then
    distinguishing-word overlap, accepted when either every word of the
    feature is in the phrase or every word of the phrase is in the feature
    ("Fort Wetherill" -> Fort Wetherill State Park), and never on one shared
    word unless that word is the whole phrase: "Fort Wetherill" must not
    land on Fort Neck. Generic words alone never match. Ties go to the more
    specific kind, and buoys last.
    """
    if not place:
        return None
    pool = names() if candidates is None else candidates
    p = _norm(place)
    if not p:
        return None
    ptoks = _tokens(place)

    def rank(c):
        return (KIND_RANK.get(c["kind"], 9), len(c["name"]))

    exact = [c for c in pool if _norm(c["name"]) == p]
    if exact:
        return min(exact, key=rank)

    # Feature name inside the phrase: the longest such name is the most of
    # the phrase explained. A one-word name needs two-word evidence it does
    # not have, so it only counts here when it IS the phrase (handled above).
    within = [c for c in pool
              if len(_tokens(c["name"])) >= 2 and _norm(c["name"]) in p
              and c["kind"] != "Populated Place"]
    if within:
        return min(within, key=lambda c: (-len(_norm(c["name"])), rank(c)))
    # Phrase inside a feature name: the shortest such name adds the least.
    around = [c for c in pool
              if len(p) >= 4 and _tokens(c["name"]) and p in _norm(c["name"])]
    if around:
        return min(around, key=lambda c: (len(_norm(c["name"])), rank(c)))

    if not ptoks:
        return None
    best, best_score = None, None
    for c in pool:
        ct = _tokens(c["name"])
        if not ct:
            continue
        overlap = len(ptoks & ct)
        if overlap == 0:
            continue
        feature_explained = overlap == len(ct)      # "Mount Hope Bay" in "the Mount Hope Bridge"
        phrase_explained = overlap == len(ptoks)    # "Fort Wetherill" in "Fort Wetherill State Park"
        if not (feature_explained or phrase_explained):
            continue
        # One shared word is not a match unless it is the whole phrase.
        if overlap < 2 and not phrase_explained:
            continue
        if overlap < 2 and not feature_explained:
            continue
        score = (overlap, -KIND_RANK.get(c["kind"], 9), -len(c["name"]))
        if best is None or score > best_score:
            best, best_score = c, score
    return best
