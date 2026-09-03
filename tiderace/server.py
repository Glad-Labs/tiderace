"""Local web server for the map UI.

Stdlib only, same as the rest of the project. Runs on your machine, talks to
NOAA directly, and stores nothing anywhere else.

    python3 -m tiderace serve

The scoring grid is computed lazily per species and held in memory, because
scoring 19 spots across 48 hours touches ~15 NOAA stations and you do not want
that on every drag of the time slider.
"""

from __future__ import annotations

import gzip
import json
import mimetypes
import subprocess
import sys
import os
import re
import threading
import traceback
from datetime import date, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import bait as baitmod
from . import birds, charts, config as cfgmod, features, heat, point, regs, score, spots
from . import species as speciesmod
from . import evaluate, prospect, structure
from . import log as catchlog
from .sources import SourceError

WEB_DIR = os.path.join(os.path.dirname(__file__), "web")

_grid_lock = threading.Lock()
_grid: dict[tuple, dict] = {}


def build_grid(species: str, start: datetime, hours: int = 48,
               step_minutes: int = 30) -> dict:
    """Score every position for this species across the horizon."""
    key = (species, start.isoformat(), hours, step_minutes)
    with _grid_lock:
        if key in _grid:
            return _grid[key]

    times: list[str] = []
    out_spots = []
    # 29 of the 35 loggable species have no profile, and the picker offers all
    # of them now -- you catch a bonito whether or not the model has an opinion
    # about bonito. For those the grid still carries the water (current, tide,
    # light, wind) and simply has no score, rather than the picker refusing to
    # show the fish at all.
    #
    # `for_species` filters spots by which fish they are listed for, so it
    # returns nothing for an unscored one; those get every spot. And
    # `features.build` is passed species=None, which is what skips the bait,
    # bird and thermal-season work that only means something with a profile.
    modelled = species in score.PROFILES
    targets = list(spots.for_species(species)) if modelled else list(spots.SPOTS)
    feat_species = species if modelled else None
    # One eBird query for the whole set rather than one per spot.
    birds.prime([(s.lat, s.lon) for s in targets])
    for spot in targets:
        try:
            rows = features.build(spot, start, hours, step_minutes,
                                  species=feat_species)
        except SourceError as exc:
            out_spots.append({
                "key": spot.key, "label": spot.label, "lat": spot.lat, "lon": spot.lon,
                "private": spot.private,
                "kind": spot.kind, "notes": spot.notes, "best_stage": spot.best_stage,
                "error": str(exc), "scores": [], "detail": [],
            })
            continue

        results = ([score.score(species, r, exposed=r["exposed"],
                                prior=spot.prior(species),
                                best_stage=spot.best_stage) for r in rows]
                   if modelled else [])
        if not times:
            times = [r["time"].isoformat() for r in rows]

        # No name. The position is what the ranking reports, and `label` is
        # the position formatted once, server-side, so every list and card
        # prints the same string for the same water.
        out_spots.append({
            "key": spot.key, "label": spot.label, "lat": spot.lat, "lon": spot.lon,
            "private": spot.private,
            "kind": spot.kind, "notes": spot.notes, "best_stage": spot.best_stage,
            "prior": spot.prior(species) if modelled else None,
            "bottom": charts.bottom_at(spot.lat, spot.lon),
            # Empty, not zero. A spot with no score is not a bad spot.
            "scores": [r["score"] for r in results] if modelled else [None] * len(rows),
            "detail": [{
                "current_speed": r["current_speed"],
                "current_dir": r["current_dir"],
                "water_temp_f": r["water_temp_f"],
                "wind_kt": r["wind_kt"],
                "wind_dir": r["wind_dir"],
                "light_phase": r["light_phase"],
                "moon_phase": r["moon_phase"],
                "moon_illum": r["moon_illum"],
                "next_tide": r["next_tide"],
                "season_note": r.get("season_note"),
                "bait_note": r.get("bait_note"),
                "bait_signal": r.get("bait_signal"),
                "why": score.explain(res) if res else None,
            } for r, res in zip(rows, results or [None] * len(rows))],
        })

    grid = {
        "species": species,
        "species_name": (score.PROFILES[species].name if modelled
                         else (speciesmod.get(species).name
                               if speciesmod.get(species) else species)),
        # The picker offers every loggable fish; this says which of them the
        # forecast actually has an opinion about, so the interface can show
        # conditions without pretending to a score it does not have.
        "modelled": modelled,
        "license_mode": cfgmod.load()["license_mode"],
        "regulations": regs.status(species, start.date(),
                                   cfgmod.load()["license_mode"],
                                   cfgmod.load().get("aggregate_program")),
        "regulations_line": regs.summary_line(
            species, start.date(), cfgmod.load()["license_mode"],
            cfgmod.load().get("aggregate_program")),
        "regulations_differences": regs.differences(species, start.date()),
        "notes": (score.PROFILES[species].notes if modelled
                  else (speciesmod.get(species).notes or "")),
        # Two different absences, and they used to be one. Until 2 Sep 2026
        # every scored species was also a regulated one, so "no forecast" and
        # "no rule" arrived together and this field could key off `modelled`.
        # Eight of the fourteen profiles now have no transcribed rule -- the
        # alternative was typing eight size limits in from memory -- so the
        # forecast and the rulebook can be absent independently, and each says
        # so on its own.
        "not_modelled": (None if modelled else
                         speciesmod.unregulated_warning(species)),
        "rules_not_modelled": (None if regs.status(
            species, start.date(), cfgmod.load()["license_mode"]).get("known")
            else speciesmod.unregulated_warning(species)),
        "start": start.isoformat(),
        "step_minutes": step_minutes,
        "times": times,
        "spots": out_spots,
    }
    with _grid_lock:
        _grid[key] = grid
    return grid


_point_lock = threading.Lock()
_point_cache: dict[tuple, dict] = {}
POINT_CACHE_MAX = 64


def point_report(lat: float, lon: float, species: str, hours: int) -> dict:
    """Cached coordinate report.

    Tapping around a chart is the natural way to use this, and every tap is a
    fresh set of NOAA calls without a cache. Keyed on the coordinate rounded to
    ~11 m, which is far finer than any of the underlying data.
    """
    start = datetime.now().replace(minute=0, second=0, microsecond=0)
    key = (round(lat, 4), round(lon, 4), species, hours, start.isoformat())
    with _point_lock:
        if key in _point_cache:
            return _point_cache[key]

    rep = point.report(lat, lon, species=species, start=start, hours=hours)
    rep = {k: v for k, v in rep.items() if k not in ("rows", "results")}

    with _point_lock:
        if len(_point_cache) >= POINT_CACHE_MAX:
            _point_cache.clear()
        _point_cache[key] = rep
    return rep



# Where the basemap extract lives. Config wins so you can point at one built
# elsewhere; otherwise the conventional path, which is what `tiderace basemap`
# writes and what .gitignore already excludes.
BASEMAP_DEFAULT = os.path.join(os.path.dirname(__file__), "..",
                               "data", "pmtiles", "narragansett.pmtiles")


def _basemap_path(cfg: dict | None = None) -> str | None:
    """The local pmtiles extract, or None if there is not one.

    Returning None rather than raising is deliberate: no local basemap is a
    normal state -- a fresh clone has never run `tiderace basemap` -- and the
    map falls back to the hosted API, which works fine until you lose signal.
    """
    cfg = cfg or {}
    for cand in (cfg.get("pmtiles_path"), BASEMAP_DEFAULT):
        if cand and os.path.isfile(cand):
            return os.path.abspath(cand)
    return None

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # quiet; errors still surface through _send_json

    # ---------------------------------------------------------------- helpers
    # Chart GeoJSON is the bulk of what this server sends -- depth areas alone
    # are a few megabytes -- and a phone on the water is reaching it over a
    # tailnet, not a LAN. GeoJSON is nearly all digits and punctuation, so it
    # compresses about eightfold for a few milliseconds of CPU.
    GZIP_MIN = 1400          # below one packet there is nothing to win

    def _send(self, body: bytes, ctype: str, status: int = 200):
        encoding = None
        if (len(body) >= self.GZIP_MIN
                and "gzip" in self.headers.get("Accept-Encoding", "")
                and ("json" in ctype or ctype.startswith("text/")
                     or "javascript" in ctype)):
            body = gzip.compress(body, 6)
            encoding = "gzip"

        self.send_response(status)
        self.send_header("Content-Type", ctype)
        if encoding:
            self.send_header("Content-Encoding", encoding)
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _pmtiles(self):
        """Serve the basemap extract with byte-range support.

        PMTiles is a single file that the client reads in pieces -- a header,
        then directory pages, then individual tiles -- so range requests are
        not an optimisation here, they are the entire access pattern. Without
        a 206 the library falls back to fetching the whole archive to read one
        tile, which on a phone means a hundred megabytes to draw one square.

        Deliberately never gzipped: the ranges are byte offsets into the file,
        and compressing the body would make them refer to nothing. The tile
        data inside is already compressed anyway.
        """
        from . import config as _cfg
        path = _basemap_path(_cfg.load())
        if not path:
            return self._send_json(
                {"error": "no local basemap — run: tiderace basemap"}, 404)

        size = os.path.getsize(path)
        rng = self.headers.get("Range")
        start, end = 0, size - 1
        status = 200

        if rng:
            m = re.match(r"bytes=(\d*)-(\d*)$", rng.strip())
            if not m:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            a, b = m.group(1), m.group(2)
            if a == "":                      # suffix range: last N bytes
                if b == "":
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                start, end = max(0, size - int(b)), size - 1
            else:
                start = int(a)
                end = int(b) if b else size - 1
            if start >= size or start > end:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            end = min(end, size - 1)
            status = 206

        length = end - start + 1
        with open(path, "rb") as fh:
            fh.seek(start)
            body = fh.read(length)

        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        # A basemap extract changes when you rebuild it, not between requests.
        # Letting the browser and the service worker hold it is the whole point.
        self.send_header("Cache-Control", "public, max-age=604800")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, obj, status: int = 200):
        self._send(json.dumps(obj, default=str).encode(), "application/json", status)

    # -------------------------------------------------------------------- GET
    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)

        try:
            if url.path in ("/", "/index.html"):
                return self._static("index.html")
            # A service worker may only control paths at or below its own, so
            # this has to be served from the root even though it lives in web/.
            if url.path == "/sw.js":
                return self._static("sw.js")
            if url.path == "/manifest.webmanifest":
                return self._static("manifest.webmanifest")
            if url.path == "/api/health":
                return self._send_json({"ok": True})
            if url.path == "/api/meta":
                return self._send_json({
                    # Every loggable fish, scored ones first. The picker used
                    # to offer six of thirty-five, so the other twenty-nine --
                    # bonito, albies, tog in the wrong season, every tuna --
                    # could not even be looked at, let alone logged from the
                    # map. `scored` says which have a forecast behind them.
                    "species": [{"key": sp.key, "name": sp.name,
                                 "notes": sp.notes, "scored": sp.scored,
                                 "hms": sp.hms, "group": sp.group}
                                for sp in sorted(
                                    speciesmod.loggable(),
                                    key=lambda x: (not x.scored, x.name))],
                    "spot_count": len(spots.SPOTS),
                    # AGPL s13: users interacting over a network must be
                    # offered the corresponding source.
                    "source_url": __import__("tiderace").SOURCE_URL,
                    "license": "AGPL-3.0-or-later",
                })
            if url.path == "/api/grid":
                species = q.get("species", ["striped_bass"])[0]
                # Any loggable fish, not only the six with a profile. The grid
                # carries the water for the rest and says `modelled: false`.
                if not speciesmod.get(species):
                    return self._send_json({"error": f"unknown species {species}"}, 400)
                hours = min(int(q.get("hours", ["48"])[0]), 96)
                start = datetime.now().replace(minute=0, second=0, microsecond=0)
                return self._send_json(build_grid(species, start, hours))
            if url.path == "/api/best":
                sp = q.get("species", ["striped_bass"])[0]
                if sp not in score.PROFILES:
                    return self._send_json(
                        {"error": f"{sp} has no forecast profile"}, 400)
                try:
                    bbox = [float(v) for v in q.get("bbox", [""])[0].split(",")]
                except ValueError:
                    bbox = []
                if len(bbox) != 4:
                    return self._send_json(
                        {"error": "bbox=south,west,north,east required"}, 400)
                try:
                    nn = max(21, min(int(q.get("n", ["61"])[0]), 91))
                except ValueError:
                    nn = 61
                try:
                    return self._send_json(prospect.best(bbox, sp, n=nn))
                except (SourceError, ValueError) as exc:
                    return self._send_json({"error": str(exc)}, 502)
            if url.path == "/api/prospects":
                sp = q.get("species", ["striped_bass"])[0]
                if sp not in score.PROFILES:
                    return self._send_json({"error": f"unknown species {sp}"}, 400)
                try:
                    bbox = [float(v) for v in q.get("bbox", [""])[0].split(",")]
                except ValueError:
                    bbox = []
                if len(bbox) != 4:
                    return self._send_json(
                        {"error": "bbox=south,west,north,east required"}, 400)
                try:
                    nn = max(21, min(int(q.get("n", ["61"])[0]), 91))
                except ValueError:
                    nn = 61
                deep = q.get("deep", ["0"])[0] in ("1", "true", "yes")
                try:
                    return self._send_json(
                        prospect.prospects(bbox, sp, n=nn, deep=deep))
                except (SourceError, ValueError) as exc:
                    return self._send_json({"error": str(exc)}, 502)
            # /api/bumps, NOT /api/structure -- that name was already taken by
            # the wind-farm marks below, and inserting this above it shadowed
            # the route so the turbines 400'd and vanished from the map. Same
            # fault as /charts/cell/ sitting under startswith("/charts/").
            if url.path in ("/desk", "/desk.html"):
                return self._static("desk.html")
            if url.path == "/api/scrapes":
                from . import scrapelog
                st = scrapelog.status()
                st["line"] = scrapelog.summary_line(st)
                return self._send_json(st)
            if url.path == "/api/history":
                return self._send_json(catchlog.summary())
            if url.path == "/api/hms":
                from . import hms as hmsmod
                sp = q.get("species", [None])[0]
                out = {
                    "permit": hmsmod.PERMIT,
                    "permit_url": hmsmod.PERMIT_URL,
                    "species": [{"key": k, "line": hmsmod.summary_line(k)}
                                for k in hmsmod.RULES],
                }
                if sp and sp in hmsmod.RULES:
                    out["status"] = hmsmod.status(sp)
                return self._send_json(out)
            if url.path == "/api/regs":
                # The rules as they stand, not the claims behind them.
                #
                # This replaced /api/review, which served extract.pending() --
                # every claim an extractor had made, forty-odd of them, with no
                # approve action anywhere because auto-apply had made one
                # pointless. Matt: "I shouldn't be reviewing that stuff. I just
                # want the latest regulations posted, and a link I can click to
                # verify them." A queue of claims is work; a rule with its
                # notice attached is an answer.
                from . import regs as regsmod, species as spmod
                when = date.today()
                rows = []
                for sp in spmod.loggable():
                    if sp.hms:
                        continue           # federal, and hms.py owns them
                    entry = {"key": sp.key, "name": sp.name, "group": sp.group,
                             "modelled": sp.regulated, "modes": []}
                    if not sp.regulated:
                        # Said out loud rather than omitted. A species missing
                        # from this list would read as "no rules", which is the
                        # one thing it must never mean.
                        entry["warning"] = spmod.unregulated_warning(sp.key)
                        rows.append(entry)
                        continue
                    for mode in ("recreational", "commercial"):
                        try:
                            st = regsmod.status(sp.key, when, mode)
                        except Exception:                          # noqa: BLE001
                            continue
                        if not st.get("known"):
                            continue
                        entry["modes"].append({
                            "mode": mode,
                            "line": regsmod.summary_line(sp.key, when, mode),
                            "open": st.get("open"),
                            "season": st.get("season"),
                            "min_inches": st.get("min_inches"),
                            "slot": st.get("slot"),
                            "bag": st.get("bag"),
                            "note": st.get("note"),
                            "stale": st.get("stale"),
                            "checked_on": st.get("checked_on"),
                            "advisory": st.get("advisory"),
                            # The link that replaces the review step.
                            "source": st.get("applied_source") or st.get("source"),
                            "applied": st.get("applied") or [],
                        })
                    try:
                        entry["differences"] = regsmod.differences(sp.key, when)
                    except Exception:                              # noqa: BLE001
                        entry["differences"] = []
                    rows.append(entry)
                try:
                    from . import applied as appliedmod
                    ap = appliedmod.summary()
                except Exception:                                  # noqa: BLE001
                    ap = {}
                # Did the pages change at all? The question Matt asks of a
                # regulation source, answered per page: the notices, which the
                # reconciler plays forward on its own, and the limits table,
                # which is the annual baseline regs.py is typed in from -- a
                # change THERE is the one event that still needs a person.
                sources = {}
                baseline_moved = False
                try:
                    from . import fetch as fetchmod, scrapelog
                    by = {r["source"]: r for r in scrapelog.status()["sources"]}
                    for key, label in (("ridem_amendments", "notices"),
                                       ("ridem_limits", "limits table")):
                        r = by.get(key) or {}
                        sources[key] = {
                            "label": label,
                            "url": fetchmod.SOURCES.get(key, {}).get("url"),
                            "last_success": r.get("last_success"),
                            "stale": r.get("stale", True),
                            "content_first_seen": r.get("content_first_seen"),
                            "content_changed_on": r.get("content_changed_on"),
                            "change_observed": r.get("change_observed", False),
                            "unchanged_days": r.get("unchanged_days"),
                            "changed_today": r.get("changed_today", False),
                            "diff": r.get("diff", ""),
                        }
                    baseline_moved = scrapelog.baseline_moved(
                        by.get("ridem_limits") or {}, regsmod.COMMERCIAL_CHECKED_ON)
                except Exception:                                  # noqa: BLE001
                    pass
                return self._send_json({
                    "as_of": when.isoformat(),
                    "rows": rows,
                    # What the machine applied on its own since the file was
                    # last edited by hand, and which way each change went.
                    "applied_at": ap.get("applied_at"),
                    "applied_count": ap.get("count"),
                    "relaxed": ap.get("relaxed") or [],
                    "sources": sources,
                    "baseline_moved": baseline_moved,
                    "transcribed_on": regsmod.COMMERCIAL_CHECKED_ON.isoformat(),
                })
            if url.path == "/api/reports":
                from . import reports as rep
                try:
                    rows = rep.catch_reports()
                except (OSError, ValueError) as exc:
                    return self._send_json({"error": str(exc)}, 500)
                sp = q.get("species", [None])[0]
                out = {
                    "count": len(rows),
                    "rows": rows[:120],
                    # Species turning up in reports that the model has no
                    # opinion about. This is the list that says what the
                    # forecast is blind to.
                    "unmodelled": rep.unmodelled(rows),
                }
                try:
                    out["disagreements"] = rep.disagreements()
                except Exception:                                  # noqa: BLE001
                    out["disagreements"] = []
                if sp:
                    try:
                        out["weekly_presence"] = rep.weekly_presence(sp, rows)
                    except Exception:                              # noqa: BLE001
                        pass
                return self._send_json(out)
            if url.path == "/api/evaluate":
                # The only endpoint that can tell you the rest of them are
                # worthless. It lived in the CLI, which means it was never
                # looked at from the boat -- or, in practice, at all.
                try:
                    res = evaluate.evaluate()
                except (OSError, ValueError) as exc:
                    return self._send_json({"error": str(exc)}, 500)
                res["report"] = evaluate.report(res)
                return self._send_json(res)
            if url.path == "/api/bumps":
                try:
                    bbox = [float(v) for v in q.get("bbox", [""])[0].split(",")]
                except ValueError:
                    bbox = []
                if len(bbox) != 4:
                    return self._send_json(
                        {"error": "bbox=south,west,north,east required"}, 400)
                try:
                    nn = max(21, min(int(q.get("n", ["61"])[0]), 91))
                except ValueError:
                    nn = 61
                try:
                    return self._send_json(structure.scan_view(bbox, n=nn))
                except (SourceError, ValueError) as exc:
                    return self._send_json({"error": str(exc)}, 502)
            if url.path == "/api/heat":
                species = q.get("species", ["striped_bass"])[0]
                if species not in score.PROFILES:
                    return self._send_json({"error": f"unknown species {species}"}, 400)
                try:
                    bbox = [float(v) for v in q.get("bbox", [""])[0].split(",")]
                except ValueError:
                    bbox = []
                if len(bbox) != 4:
                    return self._send_json(
                        {"error": "bbox=south,west,north,east required"}, 400)
                try:
                    n = int(q.get("n", [str(heat.DEFAULT_N)])[0])
                except ValueError:
                    n = heat.DEFAULT_N
                try:
                    surf = heat.surface(species, bbox, n=n)
                except (SourceError, ValueError) as exc:
                    return self._send_json({"error": str(exc)}, 502)
                surf["spread"] = heat.spread(surf)
                return self._send_json(surf)
            if url.path == "/api/at":
                try:
                    lat = float(q.get("lat", [""])[0])
                    lon = float(q.get("lon", [""])[0])
                except ValueError:
                    return self._send_json({"error": "lat and lon required"}, 400)
                species = q.get("species", ["striped_bass"])[0]
                if species not in score.PROFILES:
                    return self._send_json({"error": f"unknown species {species}"}, 400)
                hours = min(int(q.get("hours", ["48"])[0]), 96)
                try:
                    return self._send_json(point_report(lat, lon, species, hours))
                except SourceError as exc:
                    return self._send_json({"error": str(exc)}, 502)
                except ValueError as exc:
                    return self._send_json({"error": str(exc)}, 400)
            if url.path == "/api/survey":
                try:
                    lat = float(q.get("lat", [""])[0])
                    lon = float(q.get("lon", [""])[0])
                except ValueError:
                    return self._send_json({"error": "lat and lon required"}, 400)
                species = q.get("species", ["striped_bass"])[0]
                if species not in score.PROFILES:
                    return self._send_json({"error": f"unknown species {species}"}, 400)
                when = None
                raw = (q.get("when", [""])[0] or "").strip()
                if raw:
                    try:
                        when = datetime.fromisoformat(raw)
                    except ValueError:
                        return self._send_json({"error": "bad when"}, 400)
                # Default to fast on the water: the satellite layers take tens
                # of seconds and a phone on a boat is on a marginal connection.
                fast = (q.get("fast", ["1"])[0] or "1") not in ("0", "false", "no")
                from . import survey as surveymod
                try:
                    return self._send_json(
                        surveymod.survey(lat, lon, when, species,
                                         include_slow=not fast))
                except ValueError as exc:
                    return self._send_json({"error": str(exc)}, 400)
            if url.path == "/basemap.pmtiles":
                return self._pmtiles()
            if url.path == "/api/basemap":
                # The page needs to know which basemap to build a style for
                # before it draws anything.
                from . import config as _cfg
                c = _cfg.load()
                path = _basemap_path(c)
                return self._send_json({
                    "local": bool(path),
                    "url": "/basemap.pmtiles" if path else None,
                    "bytes": (os.path.getsize(path) if path else None),
                    # The hosted key is public by necessity -- the browser
                    # fetches tiles directly -- but it is only handed out when
                    # there is no local extract to prefer.
                    "hosted_key": (None if path else c.get("protomaps_key")),
                    "attribution": "© <a href=\"https://protomaps.com\">Protomaps</a> "
                                   "© <a href=\"https://openstreetmap.org\">OpenStreetMap</a>",
                })
            if url.path == "/api/species":
                # Two lists, because they answer different questions: what the
                # forecast can rank, and what the log will accept. Collapsing
                # them is what stopped you logging a bonito.
                from . import species as spmod
                return self._send_json({
                    "loggable": [
                        {"key": s.key, "name": s.name, "group": s.group,
                         "scored": s.scored, "regulated": s.regulated,
                         "hms": s.hms,
                         "warning": spmod.unregulated_warning(s.key)}
                        for s in spmod.loggable()],
                    "scored": [s.key for s in spmod.scored()],
                })
            if url.path == "/api/charts":
                return self._send_json({
                    "layers": [{"name": n, "label": charts.LAYERS[n][1],
                                "url": f"/charts/{n}.geojson"}
                               for n in charts.available()]
                    # Modelled bathymetry is not an ENC layer and has no
                    # bundled file -- it exists only as generated cells -- so
                    # it is listed here rather than discovered from the cache.
                    + [{"name": "bathy",
                        "label": "Modelled bottom contours — not for navigation",
                        "url": None, "model": True}]
                })
            if url.path.startswith("/charts/bathy/"):
                # /charts/bathy/{iy}/{ix}.geojson -- modelled contours, not
                # charted soundings. Same grid as the ENC cells so the two
                # line up and share a cache-key shape.
                try:
                    rest = url.path[len("/charts/bathy/"):].replace(".geojson", "")
                    iy, ix = (int(v) for v in rest.split("/"))
                except ValueError:
                    return self._send_json({"error": "bad cell path"}, 400)
                from . import bathy as bathymod
                try:
                    gj = bathymod.cell(iy, ix)
                except Exception as exc:                          # noqa: BLE001
                    return self._send_json({"error": str(exc)}, 502)
                body = json.dumps(gj).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/geo+json")
                self.send_header("Content-Length", str(len(body)))
                # The elevation model does not change; this is worth keeping.
                self.send_header("Cache-Control", "public, max-age=31536000")
                self.end_headers()
                return self.wfile.write(body)
            # Must precede the generic /charts/ route: that one is a
            # prefix match and swallows /charts/cell/... as a layer name.
            if url.path.startswith("/charts/cell/"):
                # /charts/cell/{layer}/{iy}/{ix}.geojson
                try:
                    rest = url.path[len("/charts/cell/"):].replace(".geojson", "")
                    name, iy, ix = rest.split("/")
                    iy, ix = int(iy), int(ix)
                except ValueError:
                    return self._send_json({"error": "bad cell path"}, 400)
                if name not in charts.LAYERS:
                    return self._send_json({"error": "unknown layer"}, 404)
                try:
                    gj = charts.cell(name, iy, ix)
                except Exception as exc:                          # noqa: BLE001
                    return self._send_json({"error": str(exc)}, 502)
                body = json.dumps(gj).encode()
                # A cell is a fixed piece of the world and ENC updates are
                # months apart, so it is worth holding on to.
                self.send_response(200)
                self.send_header("Content-Type", "application/geo+json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "public, max-age=2592000")
                self.end_headers()
                return self.wfile.write(body)
            if url.path.startswith("/charts/"):
                name = url.path[len("/charts/"):].replace(".geojson", "")
                if name not in charts.LAYERS:
                    return self._send_json({"error": "unknown layer"}, 404)
                path = os.path.join(charts.CHART_DIR, f"{name}.geojson")
                if not os.path.isfile(path):
                    return self._send_json(
                        {"error": "not cached — run: python3 -m tiderace charts"}, 404)
                with open(path, "rb") as fh:
                    return self._send(fh.read(), "application/geo+json")
            if url.path == "/api/chartcells":
                # Which grid cells cover this viewport, so the client can ask
                # for them individually and cache each one on its own key.
                try:
                    bbox = tuple(float(v) for v in
                                 q.get("bbox", [""])[0].split(","))
                    if len(bbox) != 4:
                        raise ValueError
                except ValueError:
                    return self._send_json({"error": "bbox=w,s,e,n required"}, 400)
                limit = min(int(q.get("limit", ["12"])[0]), 24)
                cells = charts.cells_for(bbox, limit)
                return self._send_json({
                    "cell_deg": charts.CELL_DEG,
                    "serve_bbox": charts.SERVE_BBOX,
                    "cells": [{"iy": iy, "ix": ix,
                               "bbox": charts.cell_bbox(iy, ix)}
                              for iy, ix in cells],
                })
            if url.path == "/api/tracks":
                from . import track as trackmod
                # Sessions carry their own paths, so the map can draw where you
                # drifted; the raw breadcrumb stays on disk. Catches are matched
                # by time rather than wired in at write time, which makes the
                # link work backwards over trips already logged.
                return self._send_json({"tracks": trackmod.with_catches()[:40]})
            if url.path == "/api/structure":
                # Fixed offshore structure we know about that the ENC harbour
                # band does not carry. Its Offshore_Platform layer has eight
                # features in this box and all eight are up in the bay -- the
                # Block Island turbines are simply not in it, and they are the
                # most obvious landmark in the water Matt fishes for tuna.
                from . import offshore as _off
                feats = [{
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": {"name": name, "kind": "turbine",
                                   "note": "Block Island Wind Farm"},
                } for name, lat, lon in _off.TURBINES]
                return self._send_json({"type": "FeatureCollection",
                                        "features": feats})
            if url.path == "/api/bait":
                rows = baitmod.load()
                now = datetime.now()
                feats = []
                for r in rows:
                    try:
                        age = (now - datetime.fromisoformat(r["when"])).total_seconds() / 86400
                    except (KeyError, ValueError):
                        continue
                    if age > 21:            # older than three weeks is noise
                        continue
                    feats.append({
                        "type": "Feature",
                        "geometry": {"type": "Point",
                                     "coordinates": [r["lon"], r["lat"]]},
                        "properties": {
                            "bait": r["bait"], "abundance": r.get("abundance"),
                            "age_days": round(age, 1),
                            "freshness": round(0.5 ** (age / baitmod.HALF_LIFE_DAYS), 3),
                            "source": r.get("source", "own"),
                            "notes": r.get("notes"),
                        }})
                return self._send_json({"type": "FeatureCollection", "features": feats})
            if url.path == "/api/log":
                return self._send_json({"entries": catchlog.load(),
                                        "summary": catchlog.summary()})
            if url.path.startswith("/static/"):
                return self._static(url.path[len("/static/"):])
            if url.path.startswith("/photos/"):
                return self._photo(url.path[len("/photos/"):])
            self._send_json({"error": "not found"}, 404)
        except Exception as exc:                                  # noqa: BLE001
            traceback.print_exc()
            self._send_json({"error": str(exc)}, 500)

    # ------------------------------------------------------------------- POST
    def do_POST(self):
        url = urlparse(self.path)

        if url.path == "/api/track":
            # A finished track. Stays on this machine: it is gitignored, there
            # is no export, and it is the most sensitive file here -- a saved
            # mark is one place you chose to write down, a track is every place
            # you actually fished, in order, with how long you sat on each.
            try:
                n = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(n) or b"{}")
            except Exception as exc:                              # noqa: BLE001
                return self._send_json({"error": str(exc)}, 400)
            pts = data.get("points")
            if not isinstance(pts, list) or not pts:
                return self._send_json({"error": "no points"}, 400)
            from . import track as trackmod
            try:
                return self._send_json({"ok": True,
                                        "summary": trackmod.record(pts)})
            except Exception as exc:                              # noqa: BLE001
                traceback.print_exc()
                return self._send_json({"error": str(exc)}, 500)

        if url.path == "/api/log/voice":
            # Transcript in, draft fields out. Deliberately does NOT write to
            # the log: the form is filled and a human presses save, because a
            # misheard "no fish" would otherwise put a fish that never existed
            # into the one irreplaceable file in this project.
            try:
                n = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(n) or b"{}")
            except Exception as exc:                              # noqa: BLE001
                return self._send_json({"error": str(exc)}, 400)
            text = (data.get("transcript") or "").strip()
            if not text:
                return self._send_json({"error": "no transcript"}, 400)
            from . import voicelog
            try:
                return self._send_json(
                    voicelog.parse(text, data.get("species")))
            except Exception as exc:                              # noqa: BLE001
                traceback.print_exc()
                return self._send_json(
                    {"error": f"could not read that: {exc}",
                     "transcript": text}, 502)

        if url.path == "/api/log/photo":
            # Base64 photos in, draft sessions out. Like /api/log/voice this
            # deliberately does NOT write: EXIF settles where and when, the
            # model guesses only the species, and the count is left empty for
            # a human because a camera roll cannot honestly supply one.
            #
            # The bytes go to Ollama on this machine and nowhere else. A catch
            # photo carries the coordinate it was taken at, which is the one
            # thing this project has never shared.
            import base64
            import tempfile
            try:
                n = int(self.headers.get("Content-Length", 0))
                data = json.loads(self.rfile.read(n) or b"{}")
            except Exception as exc:                              # noqa: BLE001
                return self._send_json({"error": str(exc)}, 400)
            shots = data.get("photos")
            if not isinstance(shots, list) or not shots:
                return self._send_json({"error": "no photos"}, 400)
            if len(shots) > 60:
                return self._send_json(
                    {"error": f"{len(shots)} photos in one request; "
                              "send them in batches of 60"}, 413)
            from . import photolog
            tmp = tempfile.mkdtemp(prefix="tiderace-photo-")
            paths = []
            try:
                for i, sh in enumerate(shots):
                    blob = sh.get("data") if isinstance(sh, dict) else sh
                    name = (sh.get("name") if isinstance(sh, dict) else None) or f"{i}.jpg"
                    ext = os.path.splitext(name)[1].lower() or ".jpg"
                    # mkstemp rather than open(): it creates the file
                    # atomically with owner-only permissions, which matters
                    # for a photo that carries a coordinate, and it keeps
                    # this out of the non-atomic-write guard in tests.py.
                    fd, fp = tempfile.mkstemp(prefix=f"{i:03d}-", suffix=ext,
                                              dir=tmp)
                    try:
                        os.write(fd, base64.b64decode(blob))
                    finally:
                        os.close(fd)
                    paths.append(fp)
                out = photolog.draft(
                    paths, identify=not data.get("no_identify"))
                # The temp filenames are an implementation detail; give the
                # client back the names it sent.
                names = [(sh.get("name") if isinstance(sh, dict) else None) or f"{i}.jpg"
                         for i, sh in enumerate(shots)]
                by_index = {os.path.basename(fp): names[i]
                            for i, fp in enumerate(paths)}
                for t in out["trips"]:
                    for ph in t["photos"]:
                        ph["file"] = by_index.get(ph["file"], ph["file"])
                for sk in out["skipped"]:
                    sk["file"] = by_index.get(sk["file"], sk["file"])
                    sk.pop("path", None)
                return self._send_json(out)
            except Exception as exc:                              # noqa: BLE001
                traceback.print_exc()
                return self._send_json({"error": f"could not read those: {exc}"}, 502)
            finally:
                for fp in paths:
                    try:
                        os.unlink(fp)
                    except OSError:
                        pass
                try:
                    os.rmdir(tmp)
                except OSError:
                    pass

        if url.path != "/api/log":
            return self._send_json({"error": "not found"}, 404)
        try:
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n) or b"{}")

            # A phone coming back into signal flushes everything it queued on
            # the water in one request, so a long day does not become a long
            # sequence of round trips on a bad connection.
            if isinstance(data, dict) and isinstance(data.get("entries"), list):
                saved, failed = [], []
                for item in data["entries"]:
                    try:
                        saved.append(self._record(item))
                    except Exception as exc:                      # noqa: BLE001
                        failed.append({"client_id": item.get("client_id"),
                                       "error": str(exc)})
                return self._send_json({"ok": True, "saved": saved,
                                        "failed": failed,
                                        "summary": catchlog.summary()})

            # A `catch` list is one session with several species -- the usual
            # shape of a bottom-fishing afternoon. Written as a row each,
            # sharing a trip id, because `evaluate` correlates per species but
            # three rows must not read as three separate outings.
            cat = data.get("catch")
            if isinstance(cat, list) and cat:
                entries = []
                for c in cat:
                    row = dict(data)
                    row.pop("catch", None)
                    row.update({k: v for k, v in c.items() if v not in (None, "")})
                    entries.append(self._entry(row))
                catchlog.record_trip(entries)
            else:
                catchlog.record(self._entry(data))
            return self._send_json({"ok": True, "summary": catchlog.summary()})
        except Exception as exc:                                  # noqa: BLE001
            traceback.print_exc()
            return self._send_json({"error": str(exc)}, 400)

    @staticmethod
    def _entry(data: dict) -> catchlog.Entry:
        """One posted trip, however it was chosen: a named spot, a coordinate,
        or a tap on the chart."""
        lat, lon = data.get("lat"), data.get("lon")
        spot = data.get("spot")
        if not spot and lat is not None and lon is not None:
            spot = f"at:{float(lat):.5f},{float(lon):.5f}"
        if not spot:
            raise ValueError("entry needs a spot or a coordinate")
        # Any species in the registry, not just the six the forecast scores.
        # A bonito is a real fish and the log should hold it; refusing it
        # because the model has no opinion is how the log stayed empty.
        from . import species as spmod
        sp = data.get("species")
        if sp and sp not in spmod.BY_KEY:
            resolved = spmod.resolve(sp)
            if not resolved:
                raise ValueError(f"unknown species {sp!r}")
            sp = resolved
        return catchlog.Entry(
            spot=spot, species=sp,
            count=int(data.get("count", 0)),
            started_at=data.get("started_at") or datetime.now().isoformat(
                timespec="minutes"),
            biggest_in=data.get("biggest_in"),
            method=data.get("method"), bait_observed=data.get("bait_observed"),
            notes=data.get("notes"), source=data.get("source", "manual"),
            lat=float(lat) if lat is not None else None,
            lon=float(lon) if lon is not None else None,
            decided_by=data.get("decided_by", "angler"))

    @staticmethod
    def _photo_blobs(data: dict) -> list[bytes]:
        """The photos posted with a trip, decoded. Base64 strings, or
        {name, data} objects as /api/log/photo takes them."""
        import base64
        shots = data.get("photos") or []
        if not isinstance(shots, list):
            raise ValueError("photos must be a list")
        out = []
        for sh in shots:
            blob = sh.get("data") if isinstance(sh, dict) else sh
            if not isinstance(blob, str):
                raise ValueError("a photo must be base64")
            out.append(base64.b64decode(blob))
        return out

    def _record(self, data: dict) -> str | None:
        """Persist one queued trip. Returns the client id so the phone knows
        which of its queued entries to drop.

        Photos first, then the row, and the photos go if the row does not:
        a duplicate submit is refused by record(), and its photos must not be
        left on disk pointing at nothing."""
        entry = self._entry(data)
        blobs = self._photo_blobs(data)
        if blobs:
            try:
                when = datetime.fromisoformat(entry.started_at)
            except ValueError:
                when = None
            entry.photos = catchlog.store_photos(blobs, when)
        try:
            catchlog.record(entry)
        except BaseException:
            catchlog.discard_photos(entry.photos)
            raise
        return data.get("client_id")

    def _photo(self, rel: str):
        """One saved fish photo, for the page. photo_path refuses anything
        that resolves outside the photo directory."""
        from urllib.parse import unquote
        path = catchlog.photo_path(unquote(rel))
        if not path:
            return self._send_json({"error": "not found"}, 404)
        with open(path, "rb") as fh:
            body = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "private, max-age=86400")
        self.end_headers()
        self.wfile.write(body)

    def _static(self, name: str):
        safe = os.path.normpath(name).lstrip(os.sep)
        path = os.path.join(WEB_DIR, safe)
        if not os.path.abspath(path).startswith(os.path.abspath(WEB_DIR)) \
                or not os.path.isfile(path):
            return self._send_json({"error": "not found"}, 404)
        ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
        with open(path, "rb") as fh:
            body = fh.read()
        # The page builds its map style at construction time and cannot await a
        # fetch to find out which basemap exists, so the answer is substituted
        # here. One token, replaced with a JSON literal -- the alternative was
        # constructing the map with a throwaway style and swapping it after
        # load, which races every layer the map adds on 'load'.
        if safe == "index.html" and b"__TIDERACE_BASEMAP__" in body:
            from . import config as _cfg
            c = _cfg.load()
            local = _basemap_path(c)
            body = body.replace(b"__TIDERACE_BASEMAP__", json.dumps({
                "local": bool(local),
                "url": "/basemap.pmtiles" if local else None,
                "hosted_key": (None if local else c.get("protomaps_key")),
            }).encode())
        self._send(body, ctype)


def tailscale_ip() -> tuple[str, str] | None:
    """This machine's Tailscale address and DNS name, if the tailnet is up.

    Binding here rather than 0.0.0.0 is the difference between "my phone can
    reach it from the boat" and "everyone on the marina wifi can read my catch
    log". A tailnet is authenticated and private; a LAN is neither.
    """
    try:
        out = subprocess.run(["tailscale", "status", "--json"],
                             capture_output=True, text=True, timeout=8)
        if out.returncode != 0:
            return None
        me = json.loads(out.stdout).get("Self", {})
        ips = [i for i in me.get("TailscaleIPs", []) if ":" not in i]
        if not ips:
            return None
        return ips[0], (me.get("DNSName") or "").rstrip(".")
    except Exception:                                             # noqa: BLE001
        return None


def serve(host: str = "127.0.0.1", port: int = 8765) -> int:
    dns = ""
    if host == "tailscale":
        ts = tailscale_ip()
        if not ts:
            print("\n  No tailnet found. Is tailscale running?\n", file=sys.stderr)
            return 1
        host, dns = ts

    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"\n  tiderace  →  http://{host}:{port}")

    if host.startswith("100.") and dns:
        print(f"  on your phone →  http://{dns}:{port}")
        print("\n  Reachable from any device signed into your tailnet, and from")
        print("  nowhere else. Note there is still no login: anyone on the tailnet")
        print("  can read the catch log and your marks.\n")
    elif host not in ("127.0.0.1", "localhost", "::1"):
        print("\n  ! Bound beyond localhost with no authentication. Anyone who can")
        print("  ! reach this machine — the whole wifi, if this is 0.0.0.0 — can read")
        print("  ! your catch log and your private marks.")
        print("  ! Prefer: tiderace serve --tailscale\n")
    print(f"  {len(spots.SPOTS)} spots · {len(score.PROFILES)} species · ctrl-c to stop\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  stopped\n")
    finally:
        srv.server_close()
    return 0
