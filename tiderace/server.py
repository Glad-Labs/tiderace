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
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import bait as baitmod
from . import birds, charts, config as cfgmod, features, point, regs, score, spots
from . import log as catchlog
from .sources import SourceError

WEB_DIR = os.path.join(os.path.dirname(__file__), "web")

_grid_lock = threading.Lock()
_grid: dict[tuple, dict] = {}


def build_grid(species: str, start: datetime, hours: int = 48,
               step_minutes: int = 30) -> dict:
    """Score every spot for this species across the horizon."""
    key = (species, start.isoformat(), hours, step_minutes)
    with _grid_lock:
        if key in _grid:
            return _grid[key]

    times: list[str] = []
    out_spots = []
    targets = list(spots.for_species(species))
    # One eBird query for the whole set rather than one per spot.
    birds.prime([(s.lat, s.lon) for s in targets])
    for spot in targets:
        try:
            rows = features.build(spot, start, hours, step_minutes, species=species)
        except SourceError as exc:
            out_spots.append({
                "key": spot.key, "name": spot.name, "lat": spot.lat, "lon": spot.lon,
                "kind": spot.kind, "notes": spot.notes, "best_stage": spot.best_stage,
                "error": str(exc), "scores": [], "detail": [],
            })
            continue

        results = [score.score(species, r, exposed=r["exposed"],
                               prior=spot.prior(species),
                               best_stage=spot.best_stage) for r in rows]
        if not times:
            times = [r["time"].isoformat() for r in rows]

        out_spots.append({
            "key": spot.key, "name": spot.name, "lat": spot.lat, "lon": spot.lon,
            "kind": spot.kind, "notes": spot.notes, "best_stage": spot.best_stage,
            "prior": spot.prior(species),
            "bottom": charts.bottom_at(spot.lat, spot.lon),
            "scores": [r["score"] for r in results],
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
                "why": score.explain(res),
            } for r, res in zip(rows, results)],
        })

    grid = {
        "species": species,
        "species_name": score.PROFILES[species].name,
        "license_mode": cfgmod.load()["license_mode"],
        "regulations": regs.status(species, start.date(),
                                   cfgmod.load()["license_mode"],
                                   cfgmod.load().get("aggregate_program")),
        "regulations_line": regs.summary_line(
            species, start.date(), cfgmod.load()["license_mode"],
            cfgmod.load().get("aggregate_program")),
        "regulations_differences": regs.differences(species, start.date()),
        "notes": score.PROFILES[species].notes,
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
                    "species": [{"key": k, "name": p.name, "notes": p.notes}
                                for k, p in sorted(score.PROFILES.items())],
                    "spot_count": len(spots.SPOTS),
                    # AGPL s13: users interacting over a network must be
                    # offered the corresponding source.
                    "source_url": __import__("tiderace").SOURCE_URL,
                    "license": "AGPL-3.0-or-later",
                })
            if url.path == "/api/grid":
                species = q.get("species", ["striped_bass"])[0]
                if species not in score.PROFILES:
                    return self._send_json({"error": f"unknown species {species}"}, 400)
                hours = min(int(q.get("hours", ["48"])[0]), 96)
                start = datetime.now().replace(minute=0, second=0, microsecond=0)
                return self._send_json(build_grid(species, start, hours))
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
                rows = trackmod.load()
                # Points are deliberately not returned: the summary and the
                # dwells are what any caller needs, and the full breadcrumb is
                # the part worth not moving around even locally.
                return self._send_json({"tracks": [
                    {k: v for k, v in r.items() if k != "points"}
                    for r in rows[-40:]]})
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
        return catchlog.Entry(
            spot=spot, species=data["species"],
            count=int(data.get("count", 0)),
            started_at=data.get("started_at") or datetime.now().isoformat(
                timespec="minutes"),
            biggest_in=data.get("biggest_in"),
            method=data.get("method"), bait_observed=data.get("bait_observed"),
            notes=data.get("notes"), source=data.get("source", "manual"),
            lat=float(lat) if lat is not None else None,
            lon=float(lon) if lon is not None else None,
            decided_by=data.get("decided_by", "angler"))

    def _record(self, data: dict) -> str | None:
        """Persist one queued trip. Returns the client id so the phone knows
        which of its queued entries to drop."""
        catchlog.record(self._entry(data))
        return data.get("client_id")

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
