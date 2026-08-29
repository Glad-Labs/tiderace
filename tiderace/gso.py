"""URI GSO Narragansett Bay Fish Trawl Survey, 1959-2024.

Sixty-five years of weekly sampling at two fixed stations -- Fox Island in the
mid-bay and Whale Rock at the mouth -- one of the longest continuous marine
time series anywhere.

What the public files actually contain, which is not quite what you would hope:

  * **Temperature** is weekly, surface and bottom, every year since 1959. This
    is the valuable half. It gives a *climatology*: the water temperature you
    should expect in any given week, and therefore how far ahead or behind
    the current season is running.
  * **Catch** is annual means per species, not weekly. So it cannot give
    seasonal timing directly -- it gives long-term abundance trends. There is
    also no striped bass in it, because a bottom otter trawl is the wrong gear
    for them.

So seasonal presence is derived rather than read off: each species has a
thermal preference, and sixty-five years of weekly temperature says when the
bay historically sits inside it. That is a far better basis than the month
tuples it replaces, which were guesses -- and one of which was provably wrong.

Data © University of Rhode Island Graduate School of Oceanography. Their data
use policy asks that URI's role in collecting it be cited in any use.
"""

from __future__ import annotations

import json
import os
import statistics
import zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
GSO_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "gso")
CACHE = os.path.join(GSO_DIR, "climatology.json")

CITATION = ("URI Graduate School of Oceanography Narragansett Bay Fish Trawl "
            "Survey, 1959-2024")
SOURCE = "https://web.uri.edu/gso/research/fish-trawl/"

STATIONS = {"fox_island": 1, "whale_rock": 2}   # sheet index within the workbook
EXCEL_EPOCH = date(1899, 12, 30)


# --------------------------------------------------------------- xlsx reading

def _sheet(path: str, idx: int) -> list[dict]:
    """Minimal xlsx reader. An .xlsx is a zip of XML, so this needs no
    third-party library and keeps the project dependency-free."""
    z = zipfile.ZipFile(path)
    try:
        shared = [(t.text or "") for t in
                  ET.fromstring(z.read("xl/sharedStrings.xml")).findall(".//m:t", NS)]
    except KeyError:
        shared = []

    root = ET.fromstring(z.read(f"xl/worksheets/sheet{idx}.xml"))
    out = []
    for r in root.findall(".//m:row", NS):
        cells: dict[str, str] = {}
        for c in r.findall("m:c", NS):
            ref = c.get("r") or ""
            col = "".join(ch for ch in ref if ch.isalpha())
            v = c.find("m:v", NS)
            if v is None or v.text is None:
                continue
            cells[col] = shared[int(v.text)] if c.get("t") == "s" else v.text
        if cells:
            out.append(cells)
    return out


def _excel_date(serial: str) -> date | None:
    try:
        return EXCEL_EPOCH + timedelta(days=int(float(serial)))
    except (TypeError, ValueError):
        return None


def c_to_f(c: float) -> float:
    return c * 9 / 5 + 32


# ------------------------------------------------------------- climatology

def build_climatology(gso_dir: str | None = None) -> dict:
    """Weekly surface/bottom temperature statistics per station."""
    gso_dir = gso_dir or GSO_DIR
    path = os.path.join(gso_dir, "temp.xlsx")
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"{path} missing — run: python3 -m tiderace gso --download")

    stations: dict[str, dict] = {}
    for name, idx in STATIONS.items():
        by_week: dict[int, list[float]] = {}
        bottom: dict[int, list[float]] = {}
        years: set[int] = set()
        n = 0
        for row in _sheet(path, idx):
            d = _excel_date(row.get("A", ""))
            if d is None:
                continue
            week = min(52, d.isocalendar().week)
            for key, store in (("C", by_week), ("D", bottom)):
                try:
                    v = float(row[key])
                except (KeyError, ValueError):
                    continue
                if -3 < v < 35:                       # drop obvious sensor junk
                    store.setdefault(week, []).append(v)
            years.add(d.year)
            n += 1

        weeks = {}
        for w in range(1, 53):
            surf = by_week.get(w, [])
            bot = bottom.get(w, [])
            if not surf:
                continue
            surf_sorted = sorted(surf)
            weeks[w] = {
                "surface_f": round(c_to_f(statistics.mean(surf)), 2),
                "bottom_f": round(c_to_f(statistics.mean(bot)), 2) if bot else None,
                "p10_f": round(c_to_f(surf_sorted[int(len(surf) * 0.10)]), 2),
                "p90_f": round(c_to_f(surf_sorted[min(len(surf) - 1,
                                                      int(len(surf) * 0.90))]), 2),
                "sd_f": round(statistics.pstdev(surf) * 9 / 5, 2) if len(surf) > 1 else 0.0,
                "n": len(surf),
            }
        stations[name] = {
            "weeks": weeks,
            "observations": n,
            "years": [min(years), max(years)] if years else None,
        }

    return {"stations": stations, "citation": CITATION, "source": SOURCE,
            "built": datetime.now().isoformat(timespec="seconds")}


def build_trends(gso_dir: str | None = None) -> dict:
    """Long-term abundance per species from the annual catch means.

    Annual resolution only, so this answers 'how much of this is around these
    days compared with history', not 'when does it show up'.
    """
    gso_dir = gso_dir or GSO_DIR
    path = os.path.join(gso_dir, "catch.xlsx")
    if not os.path.exists(path):
        return {}

    out: dict[str, dict] = {}
    for name, idx in STATIONS.items():
        rows = _sheet(path, idx)
        if not rows:
            continue
        header = rows[0]
        cols = {col: label for col, label in header.items() if label != "Year"}
        series: dict[str, list[tuple[int, float]]] = {}
        for r in rows[1:]:
            try:
                year = int(float(r.get("A", "")))
            except (TypeError, ValueError):
                continue
            for col, label in cols.items():
                try:
                    series.setdefault(label, []).append((year, float(r[col])))
                except (KeyError, ValueError):
                    continue

        st: dict[str, dict] = {}
        for label, pts in series.items():
            pts.sort()
            vals = [v for _, v in pts]
            if len(vals) < 20:
                continue
            recent = [v for y, v in pts if y >= max(y for y, _ in pts) - 4]
            if not recent:
                continue
            rmean = statistics.mean(recent)
            below = sum(1 for v in vals if v < rmean)
            st[label] = {
                "recent_mean": round(rmean, 3),
                "long_term_mean": round(statistics.mean(vals), 3),
                "percentile": round(below / len(vals), 2),
                "years": [pts[0][0], pts[-1][0]],
            }
        out[name] = st
    return out


# ------------------------------------------------------------------- caching

def load(rebuild: bool = False) -> dict | None:
    if not rebuild and os.path.exists(CACHE):
        try:
            with open(CACHE) as fh:
                return json.load(fh)
        except (OSError, json.JSONDecodeError):
            pass
    try:
        data = build_climatology()
    except FileNotFoundError:
        return None
    data["trends"] = build_trends()
    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w") as fh:
        json.dump(data, fh, separators=(",", ":"))
    return data


# ------------------------------------------------------------------ queries

def expected_temp_f(when: date, station: str = "fox_island",
                    data: dict | None = None) -> dict | None:
    """What the water usually does in this week of the year."""
    data = data or load()
    if not data:
        return None
    st = data["stations"].get(station)
    if not st:
        return None
    return st["weeks"].get(str(min(52, when.isocalendar().week)))


def anomaly(observed_f: float, when: date, station: str = "fox_island",
            data: dict | None = None) -> dict | None:
    """How far ahead or behind normal the season is running.

    A warm spring pulls the whole run forward by weeks, and this is exactly
    the kind of thing local knowledge encodes and a static month tuple cannot.
    The day estimate comes from how fast the climatology is actually changing
    at this point in the year, so it is small in midsummer when the curve is
    flat and large in spring and autumn when it is steep.
    """
    data = data or load()
    exp = expected_temp_f(when, station, data)
    if not exp:
        return None
    delta = observed_f - exp["surface_f"]

    st = data["stations"][station]["weeks"]
    w = min(52, when.isocalendar().week)
    nxt, prv = st.get(str(min(52, w + 2))), st.get(str(max(1, w - 2)))
    slope = None
    if nxt and prv:
        slope = (nxt["surface_f"] - prv["surface_f"]) / 28.0   # degF per day

    # Converting a temperature anomaly into a timing shift only works where
    # the climatology is actually moving. On the summer plateau and the winter
    # floor the curve is nearly flat, so dividing by that slope produces
    # enormous, meaningless numbers -- a three-degree August anomaly came out
    # as "35 days", which was purely the clamp. Below this threshold, report
    # the temperature difference and no day figure at all.
    MIN_SLOPE = 0.06          # degF per day
    days = None
    if slope is not None and abs(slope) >= MIN_SLOPE:
        days = int(round(delta / slope))
        days = max(-21, min(21, days))

    return {
        "observed_f": round(observed_f, 1),
        "expected_f": exp["surface_f"],
        "delta_f": round(delta, 1),
        "p10_f": exp["p10_f"], "p90_f": exp["p90_f"],
        "unusual": observed_f > exp["p90_f"] or observed_f < exp["p10_f"],
        "season_shift_days": days,
        # Which way the year is moving, so the shift can be described without
        # sounding self-contradictory: "warm water, season late" is correct in
        # autumn (cooling delayed) and reads as nonsense unless you say so.
        "phase": None if slope is None else (
            "warming" if slope > 0 else "cooling"),
        "years": data["stations"][station]["years"],
    }


def thermal_season(species: str, station: str = "fox_island",
                   data: dict | None = None) -> dict[int, float]:
    """Weekly presence 0..1, from the species' temperature curve applied to
    sixty-five years of observed water temperature.

    This replaces hand-written month tuples with something derived from data:
    the bay is inside a tautog's thermal window in these weeks because it
    measurably has been, for six decades.
    """
    from .score import PROFILES, trapezoid
    data = data or load()
    if not data or species not in PROFILES:
        return {}
    weeks = data["stations"].get(station, {}).get("weeks", {})
    prof = PROFILES[species]
    out = {}
    for w in range(1, 53):
        rec = weeks.get(str(w))
        if not rec:
            continue
        out[w] = round(trapezoid(rec["surface_f"], *prof.temp), 3)
    return out


def describe_anomaly(a: dict | None) -> str:
    if not a:
        return ""
    if abs(a["delta_f"]) < 0.8:
        return f"water normal for the week ({a['expected_f']:.0f}°F typical)"

    warm = a["delta_f"] > 0
    bits = [f"{abs(a['delta_f']):.1f}°F {'warm' if warm else 'cold'} for the week"]

    d = a.get("season_shift_days")
    if d:
        transition = "spring warm-up" if a.get("phase") == "warming" else "autumn cool-down"
        bits.append(f"{transition} ~{abs(d)} days {'ahead' if d > 0 else 'behind'}")
    if a["unusual"]:
        bits.append("outside the usual range")
    return ", ".join(bits)
