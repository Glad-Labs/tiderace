"""tiderace -- rank fishing windows in Narragansett Bay."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta

from . import features, regs, score, spots
from . import log as catchlog
from .sources import SourceError

BAR = "█"


def _windows(rows: list[dict], results: list[dict], threshold: float,
             max_hours: float = 3.0) -> list[dict]:
    """Find local score peaks and return a tight window around each.

    An earlier version merged every consecutive above-threshold sample, which
    produced "19:00-06:30" -- technically true and completely useless. A
    window you can act on is the shoulder of a peak, not the whole night, so
    each peak is trimmed to where the score is still within 12% of it and
    capped at `max_hours`.
    """
    scores = [r["score"] for r in results]
    n = len(scores)
    if n < 3:
        return []

    step = (rows[1]["time"] - rows[0]["time"]).total_seconds() / 60
    half_span = int((max_hours * 60 / step) / 2)

    peaks = []
    for i in range(1, n - 1):
        if scores[i] < threshold:
            continue
        lo = max(0, i - half_span)
        hi = min(n, i + half_span + 1)
        if scores[i] >= max(scores[lo:hi]) - 1e-9:
            peaks.append(i)

    # Collapse peaks that sit on the same hump.
    merged = []
    for i in peaks:
        if merged and (i - merged[-1]) * step <= max_hours * 60:
            if scores[i] > scores[merged[-1]]:
                merged[-1] = i
        else:
            merged.append(i)

    out = []
    for i in merged:
        floor = scores[i] * 0.88
        a = b = i
        while a > 0 and scores[a - 1] >= floor and (i - a) * step < max_hours * 30:
            a -= 1
        while b < n - 1 and scores[b + 1] >= floor and (b - i) * step < max_hours * 30:
            b += 1
        out.append({"start": rows[a]["time"], "end": rows[b]["time"],
                    "best": results[i], "best_row": rows[i], "rows": b - a + 1})
    return out


def _bar(v: float, width: int = 20) -> str:
    n = int(round(v / 100 * width))
    return BAR * n + "·" * (width - n)


def _add_forecast_args(ap):
    ap.add_argument("--species", default="striped_bass",
                    choices=sorted(score.PROFILES), help="target species")
    ap.add_argument("--spot", action="append",
                    help="spot key (repeatable). default: all spots for the species")
    ap.add_argument("--hours", type=int, default=48, help="forecast horizon")
    ap.add_argument("--start", help="YYYY-MM-DD[THH:MM] (default: now)")
    ap.add_argument("--top", type=int, default=8, help="windows to show")
    ap.add_argument("--threshold", type=float, default=45.0,
                    help="minimum score to count as a window")
    ap.add_argument("--json", action="store_true", help="machine-readable output")


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="tiderace",
        description="Rank fishing windows in Narragansett Bay from live NOAA data.")
    sub = ap.add_subparsers(dest="cmd")

    fc = sub.add_parser("forecast", help="rank upcoming windows (default)")
    _add_forecast_args(fc)

    sub.add_parser("spots", help="list known spots")

    lg = sub.add_parser("log", help="record a trip, snapshotting conditions")
    lg.add_argument("--spot", required=True)
    lg.add_argument("--species", required=True, choices=sorted(score.PROFILES))
    lg.add_argument("--count", type=int, required=True,
                    help="fish landed; 0 is a valid and useful entry")
    lg.add_argument("--at", help="ISO datetime the session began (default: now)")
    lg.add_argument("--biggest-in", type=float)
    lg.add_argument("--method")
    lg.add_argument("--bait")
    lg.add_argument("--notes")
    lg.add_argument("--source", default="manual", choices=("manual", "voice", "report"))

    sub.add_parser("history", help="summarise the catch log")
    sub.add_parser("evaluate", help="does the model beat the free baseline?")

    ch = sub.add_parser("charts", help="download NOAA chart features (rocks, wrecks, bottom)")
    ch.add_argument("--bbox", help="xmin,ymin,xmax,ymax (default: Narragansett Bay)")

    sv = sub.add_parser("serve", help="run the local map UI")
    sv.add_argument("--port", type=int, default=8765)
    sv.add_argument("--host", default="127.0.0.1")

    _add_forecast_args(ap)          # allow bare `tiderace --species ...`
    ap.add_argument("--list-spots", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args.cmd == "spots":
        return _cmd_spots()
    if args.cmd == "log":
        return _cmd_log(args)
    if args.cmd == "history":
        return _cmd_history()
    if args.cmd == "evaluate":
        from . import evaluate as ev
        print()
        print(ev.report(ev.evaluate()))
        print()
        return 0
    if args.cmd == "charts":
        from . import charts
        bbox = tuple(float(x) for x in args.bbox.split(",")) if args.bbox else charts.BAY_BBOX
        print(f"\n  NOAA ENC harbour band  {bbox}\n")
        charts.cache_all(bbox)
        print()
        return 0
    if args.cmd == "serve":
        from .server import serve
        return serve(args.host, args.port)

    return _cmd_forecast(args)


def _cmd_spots() -> int:
    print()
    print(f"  {'KEY':<22}{'NAME':<30}{'TYPE':<12}{'STAGE':<7}SPECIES")
    print("  " + "─" * 92)
    for s in spots.SPOTS:
        print(f"  {s.key:<22}{s.name:<30}{s.kind:<12}"
              f"{(s.best_stage or '—'):<7}{', '.join(s.species)}")
    print()
    return 0


def _cmd_log(args) -> int:
    when = datetime.fromisoformat(args.at) if args.at else datetime.now()
    entry = catchlog.Entry(
        spot=args.spot, species=args.species, count=args.count,
        started_at=when.isoformat(timespec="minutes"),
        biggest_in=args.biggest_in, method=args.method,
        bait_observed=args.bait, notes=args.notes, source=args.source,
    )
    catchlog.record(entry)
    n = len(entry.conditions)
    print(f"logged: {args.count} {args.species} at {args.spot} "
          f"({when:%Y-%m-%d %H:%M}) with {n} conditions captured")
    if not n:
        print("  ! conditions snapshot failed -- entry saved without features")
    return 0


def _cmd_history() -> int:
    s = catchlog.summary()
    if not s["trips"]:
        print("\n  No trips logged yet. Every blank you record is a training example.\n")
        return 0
    print(f"\n  {s['trips']} trips · {s['fish']} fish · {s['blanks']} blanks")
    for sp, b in sorted(s["by_species"].items()):
        print(f"    {sp:<18} {b['trips']:>3} trips  {b['fish']:>4} fish  "
              f"{b['blanks']:>3} blanks")
    need = max(0, 60 - s["trips"])
    print(f"\n  {'ready to fit weights' if s['ready_to_fit'] else f'{need} more trips before fitting is worth it'}\n")
    return 0


def _cmd_forecast(args) -> int:
    if getattr(args, "list_spots", False):
        return _cmd_spots()

    start = (datetime.fromisoformat(args.start) if args.start
             else datetime.now().replace(minute=0, second=0, microsecond=0))

    targets = ([spots.get(k) for k in args.spot] if args.spot
               else spots.for_species(args.species))
    if not targets:
        print(f"no spots carry {args.species}", file=sys.stderr)
        return 1

    profile = score.PROFILES[args.species]
    all_windows = []
    failures = []

    for spot in targets:
        try:
            rows = features.build(spot, start, args.hours)
        except SourceError as exc:
            failures.append(f"{spot.name}: {exc}")
            continue
        results = [score.score(args.species, r, exposed=r["exposed"],
                               prior=spot.prior(args.species),
                               best_stage=spot.best_stage) for r in rows]
        for w in _windows(rows, results, args.threshold):
            w["spot"] = spot
            all_windows.append(w)

    all_windows.sort(key=lambda w: w["best"]["score"], reverse=True)
    top = all_windows[: args.top]

    if args.json:
        print(json.dumps([{
            "spot": w["spot"].key, "spot_name": w["spot"].name,
            "start": w["start"].isoformat(), "end": w["end"].isoformat(),
            "score": w["best"]["score"],
            "explain": score.explain(w["best"]),
            "conditions": {k: v for k, v in w["best_row"].items()
                           if k != "time" and not isinstance(v, datetime)},
        } for w in top], indent=2, default=str))
        return 0

    reg = regs.status(args.species, start.date())
    print()
    print(f"  {profile.name.upper()}  —  Narragansett Bay")
    if reg.get("known"):
        flag = "OPEN" if reg["open"] else "SEASON CLOSED"
        print(f"  {flag} · {regs.summary_line(args.species, start.date())}")
    print(f"  {start:%a %d %b %H:%M} → {start + timedelta(hours=args.hours):%a %d %b %H:%M}"
          f"   ({len(targets)} spots)")
    print("  " + "─" * 74)

    if reg.get("known") and not reg["open"]:
        print(f"\n  This species is {reg['season']}.")
        print("  Windows below are for planning only — do not target a closed species.")

    if not top:
        print(f"\n  Nothing clears {args.threshold:.0f} in this window.")
        print(f"  {profile.notes}\n")
        return 0

    for w in top:
        b, row = w["best"], w["best_row"]
        if w["start"] == w["end"]:
            span = f"{w['start']:%a %H:%M} (narrow)"
        else:
            span = f"{w['start']:%a %H:%M}–{w['end']:%H:%M}"
        print(f"\n  {b['score']:>5.1f}  {_bar(b['score'])}  {w['spot'].name}")
        print(f"         {span}   peak {row['time']:%H:%M}")

        cur = f"{row['current_speed']:.2f} kt {row['current_dir'] or ''}".strip()
        wind = (f"{row['wind_kt']:.0f} kt {row['wind_dir']}"
                if row["wind_kt"] is not None else "n/a")
        temp = f"{row['water_temp_f']:.1f}°F" if row["water_temp_f"] else "n/a"
        print(f"         current {cur:<18} water {temp:<9} wind {wind}")
        print(f"         {row['light_phase']:<9} moon {row['moon_phase'].lower()}"
              f" ({row['moon_illum']*100:.0f}%)   {row['next_tide'] or ''}")
        print(f"         → {score.explain(b)}")

    print()
    print("  " + "─" * 74)
    print(f"  {profile.notes}")
    if reg.get("known"):
        age = reg["days_since_checked"]
        warn = "  ⚠ VERIFY — transcribed regs may be out of date" if reg["stale"] else ""
        print(f"\n  Regs transcribed {reg['checked_on']} ({age}d ago).{warn}")
        print(f"  Always confirm at {reg['source']}")
    if failures:
        print("\n  data gaps:")
        for f in failures:
            print(f"    ! {f}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
