"""tiderace -- rank fishing windows in Narragansett Bay."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta

from . import cache

from . import bait as baitmod
from . import birds as birdmod
from . import config as cfgmod
from . import features, fetch, gso, regs, score, spots
from . import log as catchlog
from . import species as speciesmod
from .point import windows as _windows
from .sources import SourceError

BAR = "█"


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
    ap.add_argument("--why", action="store_true",
                    help="show what each score is actually made of")
    ap.add_argument("--license", dest="license_mode",
                    choices=("recreational", "commercial"),
                    help="which rules apply (default: from config)")


def run(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="tiderace",
        description="Rank fishing windows in Narragansett Bay from live NOAA data.")
    sub = ap.add_subparsers(dest="cmd")

    fc = sub.add_parser("forecast", help="rank upcoming windows (default)")
    _add_forecast_args(fc)

    sub.add_parser("spots", help="list the positions the forecast scores")

    at = sub.add_parser("at", help="conditions and windows for one coordinate")
    at.add_argument("coord", help="41.4408,-71.4228 · '41 26.448 N 71 25.368 W'")
    at.add_argument("--save", metavar="KEY",
                    help="also add this coordinate to your private marks")
    _add_forecast_args(at)

    st = sub.add_parser("stations", help="NOAA station catalog and resolution")
    st.add_argument("--refresh", action="store_true", help="re-fetch from NOAA")
    st.add_argument("--at", metavar="COORD",
                    help="show how a coordinate resolves, and what was rejected")

    lg = sub.add_parser("log", help="record a trip, snapshotting conditions")
    lg.add_argument("--spot", help="spot key, or a name if you pass --coord")
    lg.add_argument("--coord", help="log against a coordinate instead of a spot key")
    lg.add_argument("--species", required=True, choices=sorted(score.PROFILES))
    lg.add_argument("--count", type=int, required=True,
                    help="fish landed; 0 is a valid and useful entry")
    lg.add_argument("--at", help="ISO datetime the session began (default: now)")
    lg.add_argument("--biggest-in", type=float)
    lg.add_argument("--method")
    lg.add_argument("--bait")
    lg.add_argument("--notes")
    lg.add_argument("--source", default="manual",
                    choices=("manual", "voice", "report", "photo"))

    ph = sub.add_parser("photos",
                        help="rebuild trips from a camera roll (drafts only)")
    ph.add_argument("paths", nargs="+",
                    help="photo files, or directories to walk")
    ph.add_argument("--no-identify", action="store_true",
                    help="EXIF only — skip the vision model, much faster")
    ph.add_argument("--model", help="vision model (default: see `tiderace scrape --check`)")
    ph.add_argument("--json", action="store_true", help="machine-readable drafts")

    bt = sub.add_parser("bait", help="record a bait sighting (or its absence)")
    bt.add_argument("--spot", help="spot key; or give --lat/--lon")
    bt.add_argument("--lat", type=float); bt.add_argument("--lon", type=float)
    bt.add_argument("--bait", required=True, choices=baitmod.BAIT_TYPES)
    bt.add_argument("--abundance", default="decent", choices=sorted(baitmod.ABUNDANCE))
    bt.add_argument("--at", help="ISO datetime (default: now)")
    bt.add_argument("--source", default="own", choices=("own", "report", "voice"))
    bt.add_argument("--confidence", default="high", choices=("high", "medium", "low"))
    bt.add_argument("--notes")

    cf = sub.add_parser("config", help="show or set local settings")
    cf.add_argument("--license", dest="license_mode",
                    choices=("recreational", "commercial"))
    cf.add_argument("--license-holder")
    cf.add_argument("--sub-fishery", dest="sub_fishery",
                    choices=("general_category", "floating_fish_trap"))
    cf.add_argument("--aggregate", dest="aggregate_program",
                    choices=("none", "winter", "summer_fall"),
                    help="Aggregate Program enrolment (permit required)")
    cf.add_argument("--llm", dest="llm_backend",
                    choices=("ollama", "anthropic", "none"))
    cf.add_argument("--llm-model")
    cf.add_argument("--ebird-key", dest="ebird_key",
                    help="free key from https://ebird.org/api/keygen")
    cf.add_argument("--ollama-host")

    sc = sub.add_parser("scrape", help="extract facts from RIDEM and fishing reports")
    sc.add_argument("--source", choices=sorted(fetch.SOURCES), action="append",
                    help="which source (repeatable; default: all)")
    sc.add_argument("--url", help="an arbitrary URL instead of a configured source")
    sc.add_argument("--apply-bait", action="store_true",
                    help="write high-confidence bait sightings straight to the bait log")
    sc.add_argument("--force", action="store_true", help="bypass the page cache")
    sc.add_argument("--check", action="store_true",
                    help="show robots status and backend availability, then exit")
    sc.add_argument("--diff", action="store_true",
                    help="show only where RIDEM disagrees with regs.py")
    sc.add_argument("--use-model", action="store_true",
                    help="also ask the model about notices the rule parser missed")

    rv = sub.add_parser("review", help="review extracted facts awaiting approval")
    rv.add_argument("--kind", choices=("regulation", "bait", "catch_report"))

    rg = sub.add_parser("regs", help="compare recreational and commercial rules")
    rg.add_argument("--species", choices=sorted(score.PROFILES))

    ofs = sub.add_parser("offshore",
                         help="conditions offshore — facts, not a score")
    ofs.add_argument("coord", nargs="?", default="41.1072,-71.4994",
                     help="lat,lon (default: BIWF-3, the middle turbine)")
    ofs.add_argument("--name", help="label for the report")
    ofs.add_argument("--radius", type=float, default=25,
                     help="nm to search occurrence records (default 25)")
    ofs.add_argument("--box", type=float, default=0.25,
                     help="degrees either side for the SST grid")
    ofs.add_argument("--json", action="store_true")

    cd = sub.add_parser("conditions",
                        help="water level anomaly, rivers, marine forecast")
    cd.add_argument("--zone", default="ANZ236",
                    help="NWS marine zone (ANZ236 bay, ANZ237 RI/Block sounds)")
    cd.add_argument("--station", default="8452660", help="CO-OPS water level station")

    bm = sub.add_parser("basemap", help="build the offline vector basemap")
    bm.add_argument("--bbox", default="-71.95,40.95,-71.10,41.80",
                    help="min_lon,min_lat,max_lon,max_lat (default: the bay "
                         "through Block Island to the wind farm)")
    bm.add_argument("--maxzoom", type=int, default=14)
    bm.add_argument("--build", default=None,
                    help="Protomaps daily build date, YYYYMMDD (default: yesterday)")
    bm.add_argument("--out", default=None)

    sv = sub.add_parser("survey", help="every condition at one place and time")
    sv.add_argument("coord", nargs="?", default="41.4408,-71.4228",
                    help="lat,lon (default: Whale Rock)")
    sv.add_argument("--at", dest="sv_when", default=None,
                    help="time, e.g. '2026-08-31 05:00' (default: now)")
    sv.add_argument("--species", dest="sv_species", default="striped_bass",
                    choices=sorted(score.PROFILES))
    sv.add_argument("--fast", action="store_true",
                    help="skip the satellite layers")

    wh = sub.add_parser("whales", help="whale and dolphin activity — bait, bigger")
    wh.add_argument("coord", nargs="?", default="41.3720,-71.6390",
                    help="lat,lon (default: Charlestown Breachway)")
    wh.add_argument("--km", type=float, default=40)
    wh.add_argument("--days", type=int, default=7)

    rp = sub.add_parser("reports", help="what third-party fishing reports say")
    rp.add_argument("--species", dest="rep_species", default=None,
                    choices=sorted(score.PROFILES),
                    help="limit to one species")

    bd = sub.add_parser("birds", help="seabird activity — where bait is being worked")
    bd.add_argument("coord", nargs="?", default="41.3720,-71.6390",
                    help="lat,lon (default: Charlestown Breachway)")
    bd.add_argument("--km", type=int, default=25)
    bd.add_argument("--days", type=int, default=3)
    bd.add_argument("--species", dest="bird_species", default="striped_bass",
                    choices=sorted(score.PROFILES),
                    help="whose diet to read the birds against")

    hm = sub.add_parser("hms", help="federal rules for tuna, marlin, swordfish")
    hm.add_argument("species", nargs="?", help="bluefin, yellowfin, white marlin…")
    hm.add_argument("--length", type=float, help="check a fish against the size classes")

    sub.add_parser("history", help="summarise the catch log")
    sub.add_parser("evaluate", help="does the model beat the free baseline?")

    g = sub.add_parser("gso", help="URI GSO trawl series — 65y temperature climatology")
    g.add_argument("--rebuild", action="store_true", help="re-parse the spreadsheets")
    g.add_argument("--station", default="fox_island",
                   choices=("fox_island", "whale_rock"))

    ch = sub.add_parser("charts", help="download NOAA chart features (rocks, wrecks, bottom)")
    ch.add_argument("--bbox", help="xmin,ymin,xmax,ymax (default: Narragansett Bay)")

    sv = sub.add_parser("serve", help="run the local map UI")
    sv.add_argument("--port", type=int, default=8765)
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--tailscale", action="store_true",
                    help="bind to your tailnet so your phone can reach it")

    _add_forecast_args(ap)          # allow bare `tiderace --species ...`
    ap.add_argument("--list-spots", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args.cmd == "spots":
        return _cmd_spots()
    if args.cmd == "at":
        return _cmd_at(args)
    if args.cmd == "stations":
        return _cmd_stations(args)
    if args.cmd == "log":
        return _cmd_log(args)
    if args.cmd == "history":
        return _cmd_history()
    if args.cmd == "scrape":
        return _cmd_scrape(args)
    if args.cmd == "review":
        return _cmd_review(args)
    if args.cmd == "basemap":
        return _cmd_basemap(args)
    if args.cmd == "survey":
        return _cmd_survey(args)
    if args.cmd == "whales":
        return _cmd_whales(args)
    if args.cmd == "reports":
        return _cmd_reports(args)
    if args.cmd == "birds":
        return _cmd_birds(args)
    if args.cmd == "conditions":
        return _cmd_conditions(args)
    if args.cmd == "hms":
        return _cmd_hms(args)
    if args.cmd == "offshore":
        return _cmd_offshore(args)
    if args.cmd == "config":
        return _cmd_config(args)
    if args.cmd == "photos":
        return _cmd_photos(args)
    if args.cmd == "regs":
        return _cmd_regs(args)
    if args.cmd == "gso":
        return _cmd_gso(args)
    if args.cmd == "bait":
        return _cmd_bait(args)
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
        return serve("tailscale" if args.tailscale else args.host, args.port)

    return _cmd_forecast(args)


def _cmd_spots() -> int:
    # Positions, not names. The KEY column is what `--spot` takes; for the
    # public positions it is the coordinate, and for your own marks it is the
    # handle you gave `--save`, which is why it is printed at all.
    print()
    print(f"  {'POSITION':<22}{'KEY':<26}{'TYPE':<12}{'STAGE':<7}SPECIES")
    print("  " + "─" * 92)
    for s in spots.SPOTS:
        key = s.key if s.private and not s.key.startswith("at:") else ""
        print(f"  {s.label:<22}{key:<26}{s.kind:<12}"
              f"{(s.best_stage or '—'):<7}{', '.join(s.species)}")
    print()
    return 0


def _cmd_log(args) -> int:
    when = datetime.fromisoformat(args.at) if args.at else datetime.now()
    lat = lon = None
    if args.coord:
        try:
            lat, lon = spots.parse_coord(args.coord)
        except ValueError as exc:
            print(f"  {exc}", file=sys.stderr)
            return 2
    elif not args.spot:
        print("  need --spot or --coord", file=sys.stderr)
        return 2

    entry = catchlog.Entry(
        spot=args.spot or f"at:{lat:.5f},{lon:.5f}",
        species=args.species, count=args.count,
        started_at=when.isoformat(timespec="minutes"),
        biggest_in=args.biggest_in, method=args.method,
        bait_observed=args.bait, notes=args.notes, source=args.source,
        lat=lat, lon=lon,
    )
    catchlog.record(entry)
    n = len(entry.conditions)
    where = args.spot or f"{lat:.4f},{lon:.4f}"
    print(f"logged: {args.count} {args.species} at {where} "
          f"({when:%Y-%m-%d %H:%M}) with {n} conditions captured")
    print(f"  under: {entry.license_mode} licence"
          + (f" — {entry.license_holder}" if entry.license_holder else ""))
    if not n:
        print("  ! conditions snapshot failed -- entry saved without features")
    return 0


def _cmd_scrape(args) -> int:
    from . import extract, scrapelog

    if args.check:
        from . import llm
        p = llm.probe()
        print()
        print(f"  backend: {p['configured']} ({p['model']})"
              f"   ollama {'up' if p['ollama'] else 'DOWN'}"
              f"   anthropic sdk {'yes' if p['anthropic_sdk'] else 'no'}")
        if p.get("ollama_models"):
            small = [m for m in p["ollama_models"] if m["gb"] < 12][:6]
            print("  local models under 12 GB: "
                  + ", ".join(f"{m['name']} ({m['gb']}GB)" for m in small))
        print()
        print(f"  {'source':<22}{'kind':<12}{'robots':<9}delay  url")
        print("  " + "─" * 88)
        for r in fetch.check_sources():
            print(f"  {r['key']:<22}{r['kind']:<12}"
                  f"{('allowed' if r['robots_allowed'] else 'BLOCKED'):<9}"
                  f"{r.get('crawl_delay_s', 0):>4.0f}s  {r['url']}")
        print()
        return 0

    if args.diff:
        return _cmd_diff(args)

    targets = []
    if args.url:
        targets = [("custom", args.url, "report")]
    else:
        for key in (args.source or sorted(fetch.SOURCES)):
            src = fetch.SOURCES[key]
            targets.append((key, src["url"], src["kind"]))

    # Accumulated across every regulation source, then applied once. Applying
    # per source overwrote the overlay: ridem_amendments applied six changes
    # and ridem_limits, which had nothing to say, ran second and erased them.
    # Current state is a function of ALL the notices, not the last file written.
    all_changes: list[dict] = []

    print()
    for key, url, kind in targets:
        print(f"  {key}  ({kind})")
        try:
            if kind == "regulation":
                out = extract.extract_regulations(url, force=args.force,
                                                  use_model=args.use_model)
                n = len(out.get("changes", []))
                print(f"    {out['rule_parsed']} parsed by rule, "
                      f"{out['rule_unparsed']} unparsed · {out['queued']} queued "
                      f"({out['backend']})")
                for c in out.get("changes", [])[:6]:
                    x = "✓" if c.get("cross_checked") else " "
                    print(f"      {x} [{c['confidence']:<6}] {c['effective_date']} "
                          f"{c['license_mode']:<12} {c['species']}: {c['value'][:46]}")
                for w in out.get("warnings", [])[:3]:
                    print(f"      ! {w[:100]}")
            else:
                out = extract.extract_report(url, force=args.force,
                                             apply_bait=args.apply_bait)
                nb, nc = len(out.get("bait", [])), len(out.get("catches", []))
                print(f"    {nb} bait sighting(s), {nc} catch report(s)"
                      f" · {out['applied_bait']} bait applied")
                for b in out.get("bait", [])[:6]:
                    m = b.get("matched_spot") or "unmatched"
                    print(f"      [{b['confidence']:<6}] {b['abundance']:<10} "
                          f"{b['bait']:<16} {b['place'][:26]:<26} → {m}")

            for inj in out.get("injection_suspected", []):
                print(f"    ! instruction-shaped text ignored: {inj[:90]}")
            # On a timer nobody reads the output, so the outcome has to end up
            # somewhere the interface can show it going stale.
            if kind == "regulation":
                all_changes.extend(out.get("changes", []))
            scrapelog.record(key, kind, True,
                             "%d queued" % out.get("queued", 0)
                             if kind == "regulation"
                             else "%d bait, %d catch" % (len(out.get("bait", [])),
                                                         len(out.get("catches", []))))
        except extract.ExtractionUnavailable as e:
            print(f"    ! {e}")
            scrapelog.record(key, kind, False, str(e))
        except fetch.FetchError as e:
            print(f"    ! fetch failed: {e}")
            scrapelog.record(key, kind, False, "fetch failed: %s" % e)

    if all_changes:
        try:
            from . import applied, reconcile
            st = reconcile.effective_state(all_changes)
            ap = applied.apply_state(st)
            ch = [r for r in ap["rules"].values() if r.get("changed")]
            print(f"\n  applied {len(ap['rules'])} rule(s) to the overlay"
                  f", {len(ch)} changed")
            for r in ch[:8]:
                way = ("relaxes" if r.get("relaxes") is True
                       else "tightens" if r.get("relaxes") is False
                       else "direction unknown")
                print(f"    {r['species']:<16} {r.get('previous') or '—'}"
                      f" -> {r['value']}  ({way})")
        except Exception as e:                                    # noqa: BLE001
            print(f"\n  ! could not apply: {type(e).__name__}: {e}")
    print()
    print("  Applied to the overlay above. `regs.py` itself is unchanged —\n"
          "  it stays hand-written. Check any applied number against its\n"
          "  notice from the app, or with:")
    print("    python3 -m tiderace review\n")
    return 0


def _cmd_diff(args) -> int:
    """Narrow the whole notices page down to what disagrees with the code."""
    from . import reconcile, ridem
    mode = args.license_mode or cfgmod.load()["license_mode"]
    url = fetch.SOURCES["ridem_amendments"]["url"]

    try:
        doc = fetch.fetch(url, force=args.force)
    except fetch.FetchError as e:
        print(f"\n  could not reach RIDEM: {e}\n", file=sys.stderr)
        return 1

    parsed = ridem.parse_page(doc["text"])
    r = reconcile.compare(parsed["notices"], mode=mode,
                          only_fishery=cfgmod.load().get("sub_fishery"))
    c = r["counts"]

    print()
    print(f"  RIDEM vs regs.py  ·  {mode}  ·  "
          f"{cfgmod.load().get('sub_fishery', '').replace('_', ' ')}  ·  "
          f"as of {r['as_of']}")
    print(f"  {len(parsed['notices'])} notices on the page, "
          f"{parsed['unparsed'] and len(parsed['unparsed']) or 0} unparsed")
    print("  " + "─" * 76)

    actionable = [f for f in r["findings"] if f["severity"] != "ok"]
    if not actionable:
        print("\n  Nothing disagrees. regs.py matches every rule now in force.")
    for f in actionable:
        mark = "!" if f["severity"] == "mismatch" else "?"
        print(f"\n  {mark} [{f['severity']}] {f['species']}")
        print(f"      {f['detail']}")
        print(f"      \"{f['notice']['quote'][:120]}\"")

    if r["upcoming"]:
        print("\n  " + "─" * 76)
        print("  Scheduled changes not yet in force:")
        for n in r["upcoming"]:
            a = n["amount"] or {}
            amt = f"{a.get('value','')} {a.get('unit','')} {n.get('period') or ''}".strip()
            print(f"    {n['effective_date']}  {n['species_key']:<16} {amt}")

    print("\n  " + "─" * 76)
    print(f"  {c['mismatch']} mismatch · {c['ambiguous']} ambiguous · "
          f"{c['unknown']} unmodelled · {c['ok']} agree")
    print(f"  regs.py last checked {r['checked_on']}. Nothing here has been applied —")
    print("  confirm against the page, then edit tiderace/regs.py and bump CHECKED_ON.")
    print(f"  {url}\n")
    return 0 if not actionable else 0


def _cmd_review(args) -> int:
    from . import extract
    rows = extract.pending(args.kind)
    if not rows:
        print("\n  Nothing awaiting review.\n")
        return 0

    print(f"\n  {len(rows)} item(s) awaiting review")
    print("  " + "─" * 74)
    for r in rows:
        kind = r.get("kind", "?")
        print(f"\n  [{kind}] {r.get('species') or r.get('bait', '')}"
              f"  ({r.get('confidence', '?')} confidence)")
        if kind == "regulation":
            print(f"    {r.get('license_mode')} · {r.get('change_type')} · "
                  f"{r.get('value', '')}")
            if r.get("effective_date"):
                print(f"    effective {r['effective_date']}")
        else:
            print(f"    {r.get('abundance', '')} at {r.get('place', '')}"
                  f" → {r.get('matched_spot') or 'unmatched'}")
        print(f"    \"{r.get('quote', '')[:110]}\"")
        print(f"    {r.get('source_url', '')}")

    print("\n  " + "─" * 74)
    print("  Regulations are NOT applied automatically. Check each against the")
    print("  source, then edit tiderace/regs.py by hand and bump CHECKED_ON.")
    print(f"  Queue: {extract.REVIEW_PATH}\n")
    return 0


def _res(m):
    """Footprint of a value, in units a person reads. The whole point of
    showing it is that these differ by four orders of magnitude."""
    if m is None:
        return "zone"
    if m < 1000:
        return f"{m}m"
    km = m / 1000
    return f"{km:.1f}km" if km < 10 else f"{km:.0f}km"


def _cmd_basemap(args) -> int:
    """Cut a local vector basemap out of the Protomaps planet build.

    This is the only route to a basemap that works with no signal at all. The
    OSM raster tiles cannot legally be pre-seeded, so panning at the dock is
    the best they can ever do; a pmtiles extract is one file on your own disk
    that draws anywhere in the box, whether or not you have ever been there.
    """
    import shutil
    import subprocess
    from datetime import date, timedelta

    exe = shutil.which("pmtiles") or os.path.expanduser("~/.local/bin/pmtiles")
    if not os.path.isfile(exe):
        print("pmtiles CLI not found. Install from:")
        print("  https://github.com/protomaps/go-pmtiles/releases")
        print("and put it on PATH or at ~/.local/bin/pmtiles")
        return 1

    # Yesterday, because today's build may not have finished.
    build = args.build or (date.today() - timedelta(days=1)).strftime("%Y%m%d")
    src = f"https://build.protomaps.com/{build}.pmtiles"
    out = args.out or os.path.join(os.path.dirname(__file__), "..",
                                   "data", "pmtiles", "narragansett.pmtiles")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)

    print(f"  source  {src}")
    print(f"  bbox    {args.bbox}")
    print(f"  maxzoom {args.maxzoom}")
    print("  (the extract reads only the tiles in the box, not the planet)\n")
    r = subprocess.run([exe, "extract", src, out,
                        f"--bbox={args.bbox}", f"--maxzoom={args.maxzoom}"])
    if r.returncode != 0:
        print("\nextract failed — if the build date 404s, try an older --build")
        return r.returncode

    size = os.path.getsize(out)
    print(f"\n  wrote {out}  ({size/1e6:.1f} MB)")
    print("  restart the server to pick it up:  systemctl --user restart tiderace")
    return 0


def _cmd_survey(args) -> int:
    from . import survey as S
    lat, lon = spots.parse_coord(args.coord)
    when = None
    if args.sv_when:
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%H:%M"):
            try:
                when = datetime.strptime(args.sv_when, fmt)
                if fmt == "%H:%M":
                    n = datetime.now()
                    when = when.replace(year=n.year, month=n.month, day=n.day)
                break
            except ValueError:
                continue
        if when is None:
            print(f"could not read a time from {args.sv_when!r}")
            return 2

    s = S.survey(lat, lon, when, args.sv_species, include_slow=not args.fast)
    L = s["layers"]
    when_txt = datetime.fromisoformat(s["when"]).strftime("%a %d %b %H:%M")

    print(f"\n{lat:.4f}, {lon:.4f}   {when_txt}   [{s['zone']}]")
    if s.get("binding_confidence"):
        print(f"station binding: {s['binding_confidence']}")
    for w in s.get("binding_warnings", []):
        print(f"  ! {w}")
    print("─" * 74)
    print("Each figure is followed by the size of the patch of ocean it")
    print("actually describes. They are not comparable.\n")

    def row(label, text, res_m):
        print(f"  {label:<20} {text:<38} {_res(res_m):>7}")

    c = (L.get("conditions") or {}).get("value") or {}
    if c:
        print("  THE WATER")
        cur = c.get("current_speed")
        if cur is not None:
            row("current", f"{cur:.2f} kt {c.get('current_dir') or ''}".strip(),
                L["conditions"]["resolution_m"])
        if c.get("water_temp_f"):
            row("water temp", f"{c['water_temp_f']:.1f}°F", RESW := 100)
        if c.get("next_tide"):
            row("next tide", str(c["next_tide"]), 100)
        d = (L.get("depth") or {}).get("value")
        if d:
            row("charted depth", f"{d.get('min_ft')}–{d.get('max_ft')} ft", 1)
        elif not s["charted"]:
            row("charted depth", "no chart data for this area", None)
        b = (L.get("bottom") or {}).get("value")
        if b and b.get("bottom"):
            d = b.get("distance_nm")
            row("bottom", b["bottom"] + (f"   nearest, {d} nm" if d is not None else ""), 5)
        st = (L.get("structure") or {}).get("value") or {}
        if st:
            row("structure", ", ".join(f"{k} {v}" for k, v in st.items()), 5)
        sc = (L.get("surface_current") or {}).get("value")
        if sc:
            # Shear is the interesting number offshore: a big spread across
            # the cell means a front, and fish sit on fronts.
            row("surface drift", f"{sc.get('mean_kt','?')} kt toward "
                                 f"{sc.get('toward_deg','?')}°  (measured)", 6000)
            if sc.get("shear_kt") is not None:
                row("  drift shear", f"{sc['shear_kt']:.2f} kt across the cell "
                                     f"({sc.get('slowest_kt')}–{sc.get('fastest_kt')})", 6000)
        wl = (L.get("water_level_anomaly") or {}).get("value")
        if wl and wl.get("anomaly_ft") is not None:
            row("water level", f"{wl['anomaly_ft']:+.2f} ft vs predicted", 100)
        print()

    w = (L.get("weather") or {}).get("value") or {}
    if c or w:
        print("  THE AIR")
        if c.get("wind_kt") is not None:
            row("wind (forecast)", f"{c['wind_kt']:.0f} kt {c.get('wind_dir') or ''}".strip(), 2500)
        if w.get("wind_kt") is not None:
            row("wind (observed)", f"{w['wind_kt']:.0f} kt   {w.get('observed_at','')[:16]}", 2500)
        if w.get("air_temp_f") is not None:
            row("air temp", f"{w['air_temp_f']:.0f}°F", 2500)
        if c.get("pressure_trend_3h") is not None:
            row("pressure 3h", f"{c['pressure_trend_3h']:+.1f} mb", 2500)
        if c.get("light_phase"):
            row("light", str(c["light_phase"]), None)
        bu = (L.get("buoy") or {}).get("value")
        if bu:
            row("sea state (buoy)", f"{bu.get('wave_m','?')} m @ "
                                    f"{bu.get('dom_period_s','?')}s", 100)
        print()

    tb = (L.get("thermal_breaks") or {}).get("value")
    tu = (L.get("turbine") or {}).get("value")
    if tb or tu:
        print("  OFFSHORE")
        if tu:
            row("nearest turbine", f"{tu[0]} at {tu[1]:.1f} nm", 5)
        if tb:
            row("thermal break", str(tb)[:36], 1000)
        print()

    print("  WHAT ELSE IS HERE")
    bl = (L.get("bait_log") or {}).get("value") or []
    row("bait seen", f"{len(bl)} logged sighting(s) within range", 500)
    bd = (L.get("birds") or {}).get("value") or {}
    row("birds", f"{bd.get('bait_bird_records',0)} bait-bird records", 500)
    wl2 = (L.get("whales") or {}).get("value") or {}
    row("whales", f"{wl2.get('cetacean_records',0)} cetacean records", 500)
    print()

    pr = (L.get("protected") or {}).get("value") or {}
    if pr:
        print("  RULES")
        for line in pr.get("rules", []):
            print(f"    • {line}")
        for a in pr.get("areas", []):
            if not a["active"]:
                print(f"    • In the {a['name']} SMA, out of season ({a['season']}).")
        print()

    mf = (L.get("marine_forecast") or {}).get("value") or {}
    if mf.get("text"):
        print(f"  MARINE FORECAST — {mf.get('name','')}")
        for ln in str(mf["text"]).strip().splitlines()[:4]:
            print(f"    {ln[:70]}")
        print()

    al = (L.get("alerts") or {}).get("value") or []
    if al:
        print("  ACTIVE ALERTS")
        for a in al[:3]:
            print(f"    ! {a}")
        print()

    if s["unavailable"]:
        print("  not available right now:")
        for k, v in s["unavailable"].items():
            print(f"    {k:20} {v[:46]}")
    return 0


def _cmd_whales(args) -> int:
    from . import whales as W
    lat, lon = spots.parse_coord(args.coord)
    try:
        a = W.activity(lat, lon, args.km, args.days)
    except W.WhaleError as e:
        print(f"iNaturalist unavailable: {e}")
        return 1

    print(f"\nCetaceans within {args.km:.0f} km of {lat:.4f},{lon:.4f}, "
          f"last {args.days} days")
    print(f"{a['observations']} observations, {a['cetacean_records']} of "
          f"bait-implying species.\n")
    if not a["by_species"]:
        print("  Nothing on record. That is not evidence of absence — iNaturalist")
        print("  is whoever happened to be out with a phone.")
        return 0

    for sp, n in a["by_species"].items():
        w = W.BAIT_WHALES.get(sp, 0)
        implied = W.WHALE_IMPLIES_BAIT.get(sp) or "—"
        print(f"  {n:>3}x  {sp:32} weight {w:.2f}   implies {implied}")

    print("\n  most recent:")
    for o in a["sightings"][:6]:
        print(f"    {o['when']}  {o['species']:30} {o['lat']:.3f},{o['lon']:.3f}"
              f"  {o['place'][:26]}")

    if a["other_species_ignored"]:
        print(f"\n  seen but not bait-implying: "
              f"{', '.join(a['other_species_ignored'][:6])}")
    print("\n  A whale is a proxy, not a look at the bait. Never written to the")
    print("  bait log, and ranked against birds rather than added to them.")
    print("  Right whales: 500 yards is federal law for any vessel, any size.")
    return 0


def _cmd_reports(args) -> int:
    from . import reports as R
    rows = R.catch_reports()
    if not rows:
        print("No dated catch reports yet. Run: tiderace scrape <report-url>")
        return 0

    outlets = sorted({r["outlet"] for r in rows})
    people = sorted({r["witness"] for r in rows})
    weeks = sorted({r["week"] for r in rows})
    print(f"\n{len(rows)} dated observations across {len(weeks)} week(s): "
          f"{len(people)} distinct observers, published by {len(outlets)} "
          f"outlet(s) ({', '.join(outlets)}).")
    print("A column relays several tackle shops, and two magazines often relay "
          "the same one,\nso witnesses are counted by who saw the fish, not who "
          "printed it.")
    print("Reports corroborate. They never outrank what you saw yourself.\n")

    want = [args.rep_species] if args.rep_species else sorted(score.PROFILES)
    print(f"  {'species':16} {'recent':18} {'witnesses':>9}  where")
    print("  " + "-" * 72)
    for sp in want:
        ev = R.corroborate(sp)
        where = ", ".join(ev["places"][:3]) or "—"
        print(f"  {sp:16} {ev['verdict']:18} {ev['witnesses']:>9}  {where[:34]}")

    un = R.unmodelled()
    if un:
        print("\n  reported, not modelled: "
              + ", ".join(f"{k} ({v})" for k, v in un.items()))

    dis = R.disagreements()
    if dis:
        print("\n  ── the model and the reports disagree ──")
        for d in dis:
            print(f"  {d['species']}: model says absent this week "
                  f"({d['model_presence']:.2f}), {d['witnesses']} independent "
                  f"observer(s) say caught")
            for q in d["quotes"]:
                print(f"      “{q}”")
            print("      Surface thermometers read warmer than the structure these "
                  "fish hold on;\n      this may be a bad band or the wrong water. "
                  "Not auto-corrected.")
    return 0


def _cmd_birds(args) -> int:
    from . import birds
    try:
        lat, lon = (float(x) for x in args.coord.replace(" ", "").split(","))
    except ValueError:
        print(f"could not read a coordinate from {args.coord!r}", file=sys.stderr)
        return 1
    try:
        r = birds.bait_activity(lat, lon, args.km, args.days)
    except birds.NoKey as e:
        print(f"\n  {e}\n", file=sys.stderr)
        return 1
    except Exception as e:                                        # noqa: BLE001
        print(f"\n  eBird request failed: {e}\n", file=sys.stderr)
        return 1

    print()
    print(f"  seabirds within {args.km} km, last {args.days} days")
    print("  " + "─" * 74)
    print(f"  {r['bait_bird_records']} records of bait-following species "
          f"({r['other_species_ignored']} other species ignored)")
    if not r["hotspots"]:
        print("\n  nothing working nearby on the record.\n")
        return 0

    print()
    for s in r["hotspots"]:
        print(f"    {s['weighted']:>7.0f}  {s['birds']:>5} birds  "
              f"{s['place'][:38]:<38} {s['last'][:16]}")
        print(f"             {', '.join(s['species'])[:66]}")

    print()
    print("  by species")
    for name, n in list(r["by_species"].items())[:8]:
        w = birds.BAIT_BIRDS.get(name, 0)
        print(f"    {n:>6}  {name:<28} weight {w:.2f}")

    from . import birds as B
    sig = B.signal_at(lat, lon, args.bird_species, args.km, args.days)
    print()
    print(f"  as a bait proxy for {args.bird_species}")
    if sig["known"]:
        print(f"    signal {sig['signal']:+.2f}   {B.describe(sig)}")
    else:
        print("    nothing relevant to this species")

    print()
    print("  " + "─" * 74)
    print("  Birds are kept OUT of the bait log. Seeing bait is an observation;")
    print("  seeing birds is a guess about bait. They also loaf, rest and pass")
    print("  through. So this never gets written down, and in the forecast a")
    print("  bait sighting you made yourself always outranks it — birds only")
    print("  count where nothing has been seen.\n")
    return 0


def _cmd_conditions(args) -> int:
    """Facts a tide table cannot give you. Nothing here is ranked."""
    from . import conditions as C

    print()
    print("  conditions   —   Narragansett Bay")
    print("  " + "─" * 74)

    al = C.alerts(args.zone)
    if al:
        for a in al:
            print(f"  ! {a['severity'].upper()}  {a['event']} — {a['headline']}")
        print()

    temps = C.water_temperatures()
    if temps:
        lo = min(t["water_f"] for t in temps)
        hi = max(t["water_f"] for t in temps)
        print(f"  water temperature — {hi-lo:.1f}°F spread, head of bay to outside")
        for t in temps:
            bar = "█" * max(0, int((t["water_f"] - lo) * 3))
            print(f"    {t['water_f']:>5.1f}°F  {bar:<22} {t['name']}")
        print()

    a = C.water_level_anomaly(args.station)
    if a:
        d = a["anomaly_ft"]
        word = ("stacked in by wind" if d > 0.25
                else "blown out" if d < -0.25 else "close to prediction")
        print(f"  water level ({a['when']})")
        print(f"    observed {a['observed_ft']:.2f} ft · predicted "
              f"{a['predicted_ft']:.2f} ft · {d:+.2f} ft — {word}")
        print(f"    six-hour mean {a['mean_anomaly_ft']:+.2f} ft")
        print("    every printed depth and current in the bay shifts with this")

    riv = C.rivers()
    if riv:
        total = sum(r["cfs"] for r in riv)
        print()
        print(f"  freshwater into the bay — {total:,.0f} cfs across "
              f"{len(riv)} gauges")
        for r in riv[:5]:
            print(f"    {r['cfs']:>9,.1f} cfs   {r['name']}")
        print("    a spike after rain drops salinity up-bay and moves bait")

    f = C.marine_forecast(args.zone)
    if f:
        print()
        print(f"  {f['name']} — NWS coastal waters, issued {f['issued']}")
        for pd in f["periods"]:
            print(f"    {pd['name']:<11} {pd['text'][:78]}")

    print()
    print("  " + "─" * 74)
    print("  Observed levels and discharge are measurements; the forecast is NWS.")
    print("  None of it is scored.\n")
    return 0


def _cmd_hms(args) -> int:
    """Federal rules for the offshore species the state does not manage."""
    from . import hms

    if not args.species:
        print()
        print("  Atlantic Highly Migratory Species — federal, not state")
        print("  " + "─" * 74)
        for key in hms.RULES:
            print(f"    {key:<22} {hms.summary_line(key)[:60]}")
        print()
        print(f"  {hms.PERMIT}")
        print(f"  {hms.PERMIT_URL}\n")
        return 0

    st = hms.status(args.species)
    print()
    if st.get("managed_elsewhere"):
        print(f"  {args.species} — not an HMS species")
        print(f"  {st['note']}\n")
        return 0
    if not st.get("known"):
        print(f"  no federal HMS rule recorded for {args.species!r}")
        print(f"  known: {', '.join(hms.RULES)}\n")
        return 1

    print(f"  {st['common']}  ({st['scientific']})")
    print("  " + "─" * 74)
    size = (f"{st['min_inches']:.0f}\" {st['measure']}" if st["min_inches"]
            else "no minimum size")
    print(f"  minimum   {size}")
    print(f"  bag       {st['bag']}")
    if st["size_classes"]:
        print("  classes")
        for name, lo, hi in st["size_classes"]:
            rng = f'{lo:.0f}" to under {hi:.0f}"' if hi else f'{lo:.0f}" and over'
            print(f"    {name:<28} {rng}")
    if args.length:
        print()
        print(f"  a {args.length:.0f}\" fish → {hms.classify(args.species, args.length)}")
    if st["note"]:
        print(f"\n  {st['note']}")
    print(f"\n  permit    {st['permit']}")

    print("\n  " + "─" * 74)
    age = st["days_since_checked"]
    print(f"  Transcribed {st['checked_on']} ({age}d ago).")
    if st["volatile"]:
        print("  ⚠ NOAA adjusts this in-season by notice in the Federal Register.")
        print(f"    Landings and status: {st['landings']}")
    print(f"  {st['source']}\n")
    return 0


def _cmd_offshore(args) -> int:
    """Report offshore conditions. Deliberately ranks nothing.

    Seventeen miles out the bay's physics does not apply, and a score built on
    hand-set weights would be worse than useless -- it would be confident. So
    this lays out what is measurable and leaves the decision where it belongs.
    """
    from . import offshore as off

    try:
        lat, lon = (float(x) for x in args.coord.replace(" ", "").split(","))
    except ValueError:
        print(f"could not read a coordinate from {args.coord!r}", file=sys.stderr)
        return 1

    name = args.name or f"{lat:.4f}, {lon:.4f}"
    tname, tdist = off.nearest_turbine(lat, lon)

    print()
    print(f"  {name}   —   offshore conditions")
    print("  " + "─" * 74)
    print(f"  nearest turbine  {tname} · {tdist} nm")

    b = off.buoy()
    if b:
        bits = []
        if b.get("water_c") is not None:
            bits.append(f"water {b['water_c']:.1f}°C / {b['water_c']*9/5+32:.0f}°F")
        if b.get("wave_m") is not None:
            bits.append(f"seas {b['wave_m']:.1f} m @ {b.get('dom_period_s') or '?'} s")
        if b.get("wind_kt"):
            bits.append(f"wind {b['wind_kt']:.0f} kt")
        print(f"  buoy {b['station']}      {' · '.join(bits)}   ({b['when']})")

    sc = off.surface_current(lat, lon)
    if sc and sc.get("measured"):
        print()
        print(f"  surface current — MEASURED by HF radar ({sc['when'][:16]}Z)")
        print(f"    mean {sc['mean_kt']:.2f} kt toward {sc['toward_deg']:03d}°"
              f"   ·  range {sc['slowest_kt']:.2f}–{sc['fastest_kt']:.2f} kt"
              f"   ·  {sc['cells']}/{sc['of']} cells")
        if sc["shear_kt"] >= 0.4:
            print(f"    shear {sc['shear_kt']:.2f} kt across the box — water is"
                  " tearing here, and a shear line")
            print("    is a convergence, which is where anything drifting ends up")
    elif sc:
        print(f"\n  surface current — radar returned nothing this hour"
              f" ({sc['of']} cells, none reporting)")

    try:
        grid = off.sst_grid(lat, lon, args.box)
    except off.OffshoreError as e:
        print(f"\n  ! SST unavailable: {e}\n")
        grid = None

    if grid:
        temps = sorted(p[2] for p in grid["points"])
        c = grid["centre_c"]
        print()
        print(f"  SST ({grid['date']}, MUR 1 km)")
        print(f"    here            {c:.2f}°C / {c*9/5+32:.1f}°F")
        print(f"    across the box  {temps[0]:.2f} – {temps[-1]:.2f}°C"
              f"   ({temps[-1]-temps[0]:.2f}° spread over {len(temps)} cells)")

        brk = off.breaks(grid)
        if brk:
            print()
            print("  steepest temperature breaks — where bait piles up")
            for x in brk:
                d = off.nm(lat, lon, x["lat"], x["lon"])
                brg = _bearing(lat, lon, x["lat"], x["lon"])
                print(f"    {x['grad_c_per_nm']:.3f} °C/nm   {d:5.1f} nm {brg:<3}"
                      f"   {x['lat']:.3f},{x['lon']:.3f}   {x['sst_c']:.2f}°C")

    ch = off.chlorophyll(lat, lon, args.box)
    if ch:
        print()
        print(f"  chlorophyll ({ch['date']})  median {ch['median_mg_m3']} mg/m³"
              f"   range {ch['low']}–{ch['high']}")
        print("    higher is greener and more productive; the clean edge beside it")
        print("    is usually the side you want")

    print()
    print(f"  recorded within {args.radius:.0f} nm  (OBIS, all years)")
    occ = off.occurrences(lat, lon, args.radius)
    if not occ:
        print("    nothing on record here — try a wider --radius")
    for n, d in sorted(occ.items(), key=lambda kv: -kv[1]["records"]):
        months = d["by_month"]
        tot = sum(months.values()) or 1
        this = months.get(datetime.now().month, 0)
        peak = ", ".join(f"{m:02d}" for m, _ in
                         sorted(months.items(), key=lambda kv: -kv[1])[:3])
        print(f"    {n:<14} {d['records']:>6} records   peak {peak}"
              f"   this month {100*this//tot}% of them")
        from . import hms
        line = hms.summary_line(n)
        if line:
            print(f"                   federal: {line[:60]}")

    print()
    print("  " + "─" * 74)
    print("  Nothing above is ranked. Offshore the bay's physics does not apply,")
    print("  and a score built on weights I invented would only be confident.")
    print("  Occurrence records say what has been caught here and when — not")
    print("  what is happening today.\n")
    return 0


def _bearing(lat1, lon1, lat2, lon2) -> str:
    import math
    dy = lat2 - lat1
    dx = (lon2 - lon1) * math.cos(math.radians(lat1))
    deg = (math.degrees(math.atan2(dx, dy)) + 360) % 360
    return ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW",
            "W","WNW","NW","NNW"][int((deg + 11.25) % 360 / 22.5)]


def _cmd_config(args) -> int:
    changes = {}
    if args.license_mode:
        changes["license_mode"] = args.license_mode
    if args.license_holder:
        changes["license_holder"] = args.license_holder
    for attr in ("llm_backend", "llm_model", "ollama_host", "aggregate_program",
                 "sub_fishery", "ebird_key"):
        if getattr(args, attr, None):
            changes[attr] = getattr(args, attr)
    cfg = cfgmod.save(changes) if changes else cfgmod.load()

    print(f"\n  licence mode   {cfg['license_mode']}")
    print(f"  licence holder {cfg['license_holder'] or '—'}")
    print(f"  sub-fishery    {cfg['sub_fishery']}")
    print(f"  aggregate      {cfg['aggregate_program']}")
    if cfg["license_mode"] == "commercial":
        if cfg["aggregate_program"] != "none":
            ap = regs.AGGREGATE[cfg["aggregate_program"]]
            print(f"\n  {ap.name} — permit required annually.")
            print(f"  {ap.note}")
        print(f"\n  Commercial limits change in-season. Current numbers: "
              f"{regs.COMMERCIAL_HOTLINE}")

    from . import llm
    p = llm.probe(cfg)
    print(f"\n  extraction     {cfg['llm_backend']}"
          f"  ({cfg.get('llm_model') or 'default'})")
    if cfg["llm_backend"] == "ollama":
        print(f"  ollama         {'reachable' if p['ollama'] else 'NOT REACHABLE'}"
              f"{'' if p.get('model_present', True) else '  — model not pulled'}")
    print(f"\n  stored in {cfgmod.CONFIG_PATH}\n")
    return 0


def _cmd_photos(args) -> int:
    import os
    from . import llm, photolog

    paths = []
    for p in args.paths:
        if os.path.isdir(p):
            for root, _, files in os.walk(p):
                paths.extend(os.path.join(root, f) for f in files)
        else:
            paths.append(p)

    backend = None
    if not args.no_identify:
        backend = llm.Ollama(args.model or llm.DEFAULT_VISION_MODEL, timeout=600)
        if not backend.available():
            print(f"\n  No Ollama at {backend.host}. Either start it, or run "
                  f"with --no-identify\n  to read just the coordinates and times.\n")
            return 1

    out = photolog.draft(paths, backend=backend,
                         identify=not args.no_identify)

    if args.json:
        print(json.dumps(out, indent=2))
        return 0

    trips = out["trips"]
    print(f"\n  {out['photos_read']} photos read · {len(trips)} "
          f"session{'' if len(trips) == 1 else 's'} reconstructed")
    print("  " + "─" * 74)
    for i, t in enumerate(trips, 1):
        when = t["started_at"].replace("T", " ")
        span = f" · {t['span_minutes']} min on the water" if t["span_minutes"] else ""
        print(f"\n  [{i}] {when}{span}")
        print(f"      {t['spot'] or 'no position'}"
              + (f"   {t['lat']:.4f}, {t['lon']:.4f}" if t["lat"] is not None else ""))
        for c in t["catch"]:
            if c["species"]:
                print(f"      {c['species']} — seen in {c['photos_showing']} "
                      f"photo{'' if c['photos_showing'] == 1 else 's'}")
        if out["identified"] and not t["fish_in_any_photo"]:
            print("      no fish in any frame — this is what a blank looks like, "
                  "and it counts")
        if t["notes"]:
            print(f"      {t['notes'][:70]}")
        for w in t["warnings"]:
            print(f"      ! {w}")

    if out["skipped"]:
        print(f"\n  Skipped {len(out['skipped'])}:")
        for sk in out["skipped"][:8]:
            print(f"      {sk['file']} — {sk['why']}")

    print("\n  " + "─" * 74)
    print("  Nothing has been logged. **No count was filled in on purpose** — you")
    print("  photograph the good one, not all of them, so a count read off a")
    print("  camera roll flatters every day it touches. Log each session with")
    print("  the real number:\n")
    for i, t in enumerate(trips[:3], 1):
        sp = next((c["species"] for c in t["catch"] if c["species"]), "SPECIES")
        if not t["spot"]:
            print(f"    # [{i}] {t['started_at']} had no GPS in any frame — "
                  f"add --spot or --coord yourself")
            continue
        loc = (f"--coord {t['lat']:.5f},{t['lon']:.5f}"
               if t["spot"].startswith("at:") else f"--spot {t['spot']}")
        print(f"    tiderace log {loc} --species {sp} --count N \\")
        print(f"        --at {t['started_at']} --source photo")
    print()
    return 0


def _cmd_regs(args) -> int:
    targets = [args.species] if args.species else sorted(score.PROFILES)
    today = datetime.now().date()
    print(f"\n  Rhode Island · {today:%A %d %b %Y}")
    print("  " + "─" * 74)
    for sp in targets:
        rec = regs.status(sp, today)
        com = regs.status(sp, today, "commercial")
        if not rec.get("known"):
            # Was `continue`, which was correct only while every scored
            # species also had a rule. Eight of the fourteen now do not, and
            # skipping them silently would print a six-fish table that reads
            # as the complete set -- the same failure the web view's
            # paintLegal() already guards against with "RULES NOT MODELLED".
            # Absence of a rule means nobody checked, not that there is none.
            print(f"\n  {score.PROFILES[sp].name}")
            print(f"    {speciesmod.unregulated_warning(sp)}")
            continue
        print(f"\n  {score.PROFILES[sp].name}")
        print(f"    recreational  {'OPEN  ' if rec['open'] else 'CLOSED'}  "
              f"{regs.summary_line(sp, today)}")
        print(f"    commercial    {'OPEN  ' if com['open'] else 'CLOSED'}  "
              f"{regs.summary_line(sp, today, 'commercial')}")
        for d in regs.differences(sp, today):
            print(f"      ! {d}")
        if com.get("note"):
            print(f"      {com['note']}")
    print("\n  " + "─" * 74)
    print(f"  Recreational transcribed {regs.CHECKED_ON}; "
          f"commercial {regs.COMMERCIAL_CHECKED_ON}.")
    print(f"  Commercial possession limits and closures change in-season —")
    print(f"  confirm current numbers on {regs.COMMERCIAL_HOTLINE} before landing fish.\n")
    return 0


def _cmd_gso(args) -> int:
    data = gso.load(rebuild=args.rebuild)
    if not data:
        print("\n  GSO spreadsheets not found in data/gso/.")
        print("  Download catch.xlsx and temp.xlsx from:")
        print(f"  {gso.SOURCE}\n")
        return 1

    st = data["stations"][args.station]
    print(f"\n  {args.station.replace('_', ' ').title()}  ·  "
          f"{st['years'][0]}–{st['years'][1]}  ·  {st['observations']:,} weekly observations")
    print("  " + "─" * 62)
    print(f"  {'week':>5}  {'typical':>8}  {'p10':>6}  {'p90':>6}   thermal window")

    curves = {sp: gso.thermal_season(sp, args.station) for sp in score.PROFILES}
    for w in range(1, 53, 2):
        rec = st["weeks"].get(str(w))
        if not rec:
            continue
        openish = [score.PROFILES[sp].name.split()[0].lower()
                   for sp, c in curves.items() if c.get(w, 0) >= 0.5]
        print(f"  {w:>5}  {rec['surface_f']:>7.1f}°  {rec['p10_f']:>5.1f}  "
              f"{rec['p90_f']:>5.1f}   {', '.join(openish) or '—'}")

    print("  " + "─" * 62)
    print(f"  {gso.CITATION}")
    print(f"  {gso.SOURCE}\n")
    return 0


def _cmd_bait(args) -> int:
    if args.spot:
        sp = spots.get(args.spot)
        lat, lon = sp.lat, sp.lon
    elif args.lat is not None and args.lon is not None:
        lat, lon = args.lat, args.lon
    else:
        print("need --spot, or both --lat and --lon", file=sys.stderr)
        return 1

    when = datetime.fromisoformat(args.at) if args.at else datetime.now()
    baitmod.record(baitmod.Sighting(
        bait=args.bait, lat=lat, lon=lon,
        when=when.isoformat(timespec="minutes"),
        abundance=args.abundance, spot=args.spot, source=args.source,
        confidence=args.confidence, notes=args.notes))

    verb = "no" if args.abundance == "none" else args.abundance
    print(f"logged: {verb} {args.bait} at "
          f"{args.spot or f'{lat:.4f},{lon:.4f}'} ({when:%Y-%m-%d %H:%M})")

    # Which spots does this sighting actually move, and for which target?
    moved = []
    for sp in spots.SPOTS:
        best = max(
            ((baitmod.bait_at(sp.lat, sp.lon, when, t)["signal"], t) for t in sp.species),
            key=lambda x: abs(x[0]), default=(0.0, None))
        if abs(best[0]) > 0.05:
            moved.append((sp.name, best[1], best[0]))
    moved.sort(key=lambda x: -abs(x[2]))

    if moved:
        print("  now influencing:")
        for name, target, sig in moved[:5]:
            print(f"    {name:<26} {target:<16} {sig:+.2f}  "
                  f"x{baitmod.modifier(sig):.2f}")
    else:
        print("  no spots close enough for this to matter")
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

    # One eBird query for the whole run rather than one per spot.
    birdmod.prime([(s.lat, s.lon) for s in targets])
    for spot in targets:
        try:
            rows = features.build(spot, start, args.hours, species=args.species)
        except SourceError as exc:
            failures.append(f"{spot.label}: {exc}")
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
            "spot": w["spot"].key, "lat": w["spot"].lat, "lon": w["spot"].lon,
            "start": w["start"].isoformat(), "end": w["end"].isoformat(),
            "score": w["best"]["score"],
            "explain": score.explain(w["best"]),
            "conditions": {k: v for k, v in w["best_row"].items()
                           if k != "time" and not isinstance(v, datetime)},
        } for w in top], indent=2, default=str))
        return 0

    _cfg = cfgmod.load()
    mode = args.license_mode or _cfg["license_mode"]
    program = _cfg.get("aggregate_program", "none")
    reg = regs.status(args.species, start.date(), mode, program)
    print()
    print(f"  {profile.name.upper()}  —  Narragansett Bay")
    if reg.get("known"):
        flag = "OPEN" if reg["open"] else "CLOSED"
        tag = "COMMERCIAL" if mode == "commercial" else "recreational"
        print(f"  [{tag}]  {flag} · "
              f"{regs.summary_line(args.species, start.date(), mode, program)}")
        agg = reg.get("aggregate") or {}
        if agg.get("applies"):
            state = "open" if agg["open"] else "closed for the season"
            print(f"           {agg['program']} ({state}) — permit required")
        for d in (regs.differences(args.species, start.date())
                  if mode == "commercial" else []):
            print(f"           differs from recreational — {d}")
    else:
        # A forecast with no legal line under it reads as "no limits". It
        # means nobody transcribed them. The forecast is still worth printing
        # -- knowing when the fish will be there is a separate question from
        # whether you may keep one -- but it does not go out unlabelled.
        print(f"  [RULES NOT MODELLED]  {speciesmod.unregulated_warning(args.species)}")
    print(f"  {start:%a %d %b %H:%M} → {start + timedelta(hours=args.hours):%a %d %b %H:%M}"
          f"   ({len(targets)} spots)")
    print("  " + "─" * 74)

    if reg.get("known") and not reg["open"]:
        print(f"\n  Not open under this licence: {reg['season']}.")
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
        print(f"\n  {b['score']:>5.1f}  {_bar(b['score'])}  {w['spot'].label}")
        print(f"         {span}   peak {row['time']:%H:%M}")

        cur = f"{row['current_speed']:.2f} kt {row['current_dir'] or ''}".strip()
        wind = (f"{row['wind_kt']:.0f} kt {row['wind_dir']}"
                if row["wind_kt"] is not None else "n/a")
        temp = f"{row['water_temp_f']:.1f}°F" if row["water_temp_f"] else "n/a"
        print(f"         current {cur:<18} water {temp:<9} wind {wind}")
        print(f"         {row['light_phase']:<9} moon {row['moon_phase'].lower()}"
              f" ({row['moon_illum']*100:.0f}%)   {row['next_tide'] or ''}")
        if row.get("bait_note"):
            print(f"         bait: {row['bait_note']}")
        print(f"         → {score.explain(b)}")
        if getattr(args, "why", False):
            from . import provenance as prov
            br = prov.breakdown(b, row)
            ag = prov.agreement(row)
            print(f"         made of: "
                  + ", ".join(f"{n} {t}" for t, n in br["counts"].items()))
            for tier in prov.TIER_ORDER:
                for item in br["tiers"].get(tier, []):
                    amt = ("" if item["amount"] is None
                           else f"{item['amount']:+.3f}  ")
                    print(f"           {tier:<11} {amt}{item['what']}")
            print(f"         {len(br['independent_origins'])} independent origins: "
                  + ", ".join(br["independent_origins"]))
            if ag["count"]:
                w = "; ".join(f"{txt} ({tier})" for txt, tier in ag["witnesses"])
                mark = "corroborated" if ag["corroborated"] else "single witness"
                print(f"         bait — {mark}: {w}")

    print()
    print("  " + "─" * 74)
    print(f"  {profile.notes}")
    if reg.get("known"):
        age = reg["days_since_checked"]
        print(f"\n  Rules transcribed {reg['checked_on']} ({age}d ago).")
        if reg.get("advisory"):
            # Commercial limits move on days of notice, so this never softens.
            print("  ⚠ COMMERCIAL limits and closures change in-season. RIDEM treats")
            print("    keeping current as the licence holder's responsibility.")
            print(f"    Confirm on {reg['hotline']} before landing fish.")
        elif reg["stale"]:
            print("  ⚠ VERIFY — transcribed regs may be out of date")
        print(f"  {reg['source']}")
    if failures:
        print("\n  data gaps:")
        for f in failures:
            print(f"    ! {f}")
    print()
    return 0


def _cmd_stations(args) -> int:
    from . import stations
    if args.refresh:
        print("\n  fetching NOAA station catalog…")
        cat = stations.refresh()
        print(f"  {len(cat['current'])} current-prediction stations, "
              f"{len(cat['tide'])} water-level stations")
        print(f"  cached at {stations.CATALOG_PATH}\n")
        if not args.at:
            return 0

    if not args.at:
        cat = stations.catalog()
        print(f"\n  {len(cat['current'])} current-prediction stations, "
              f"{len(cat['tide'])} water-level stations")
        print(f"  fetched {cat.get('fetched_at', 'unknown')}")
        print("\n  tiderace stations --at 41.4408,-71.4228   to resolve a point\n")
        return 0

    try:
        lat, lon = spots.parse_coord(args.at)
        res = stations.resolve(lat, lon)
    except (ValueError, stations.StationError) as exc:
        print(f"  {exc}", file=sys.stderr)
        return 1

    print(f"\n  {lat:.5f}, {lon:.5f}   confidence: {res['confidence']}")
    print("  " + "─" * 74)
    # `resolve` documents returning None for any of these and says so in its
    # warnings; subscripting them anyway turned a prepared message into a
    # traceback.
    c, t, tp = res["current"], res["tide"], res.get("temp")
    row = "  {:<9} {:<9} {:<42}{:>5} nm"
    for label, st in (("current", c), ("tide", t), ("temp", tp)):
        if st:
            print(row.format(label, st["id"], st["name"][:40], st["distance_nm"]))
        elif label != "temp":
            print(f"  {label:<9} none found")

    if res["current_rejected"]:
        print("\n  rejected — path crosses land:")
        for r in res["current_rejected"]:
            print(f"    {r['id']:<9} {r['name'][:40]:<42}{r['distance_nm']:>5} nm"
                  f"  ({r['land_span_nm']} nm of land)")
    if res["current_alternates"]:
        print("\n  other clear water:")
        for r in res["current_alternates"]:
            print(f"    {r['id']:<9} {r['name'][:40]:<42}{r['distance_nm']:>5} nm")
    for w in res["warnings"]:
        print(f"\n  ! {w}")
    print()
    return 0


def _depth_range(d: dict | None) -> str | None:
    """A charted depth area as text, tolerating a half-open range.

    S-57 depth areas carry DRVAL1 and DRVAL2 independently, and plenty of them
    have only one: the deepest area in a cell has no lower bound charted, and
    a drying area has no upper one. Formatting the missing end raised
    TypeError, which took out the whole `at` report over a cosmetic detail.
    """
    if not d:
        return None
    lo, hi = d.get("min_ft"), d.get("max_ft")
    if lo is not None and hi is not None:
        return f"{lo:.0f}\u2013{hi:.0f} ft"
    if lo is not None:
        return f"{lo:.0f}+ ft"
    if hi is not None:
        return f"less than {hi:.0f} ft"
    return None


def _cmd_at(args) -> int:
    """Everything the forecast knows about one coordinate.

    The report leads with which station the current came from and how far away
    it is, because that is the number most likely to be wrong and the one a
    generic app would never show you.
    """
    from . import charts, point, stations

    try:
        lat, lon = spots.parse_coord(args.coord)
    except ValueError as exc:
        print(f"  {exc}", file=sys.stderr)
        return 2

    start = (datetime.fromisoformat(args.start) if args.start else None)
    try:
        rep = point.report(lat, lon, species=args.species, start=start,
                           hours=args.hours, threshold=args.threshold,
                           top=args.top)
    except (ValueError, stations.StationError) as exc:
        print(f"  {exc}", file=sys.stderr)
        return 1
    except SourceError as exc:
        print(f"  no data for {lat},{lon}: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({k: v for k, v in rep.items()
                          if k not in ("rows", "results")},
                         indent=2, default=str))
        return 0

    st, place, now = rep["stations"], rep["place"], rep["now"]
    print()
    print(f"  {rep['label']}   —   {rep['species_name']}")
    print("  " + "─" * 74)

    c, t, tp = st["current"], st["tide"], st["temp"]
    print(f"  current from  {c['name'][:44]:<46}{c['distance_nm']:>5} nm")
    print(f"  tide from     {t['name'][:44]:<46}{t['distance_nm']:>5} nm")
    if tp and tp["id"] != t["id"]:
        print(f"  water temp    {tp['name'][:44]:<46}{tp['distance_nm']:>5} nm")
    print(f"  binding confidence: {st['confidence']}")
    for w in st["warnings"]:
        print(f"    ! {w}")

    bits = []
    d, b = place["depth"], place["bottom"]
    rng = _depth_range(d)
    if rng:
        bits.append(f"charted {rng}")
    if b:
        bits.append(f"bottom {b['bottom']} ({b['distance_nm']} nm)")
    bits += [f"{n} {layer}" for layer, n in place["structure"].items()]
    if bits:
        print(f"\n  the place:  {' · '.join(bits)}")
    elif not place.get("charted", True):
        # Outside the cached bay there is no chart to be empty, and reporting
        # "nothing within 500 yds" would read as clear water over a reef.
        print("\n  the place:  no chart data for this area")
    else:
        from . import charts as _ch
        print("\n  the place:  nothing charted within 500 yds"
              + ("" if _ch.available() else " — run: tiderace charts"))

    cur = f"{now['current_speed']:.2f} kt {now['current_dir'] or ''}".strip()
    wind = (f"{now['wind_kt']:.0f} kt {now['wind_dir']}"
            if now["wind_kt"] is not None else "n/a")
    temp = f"{now['water_temp_f']:.1f}°F" if now["water_temp_f"] else "n/a"
    when = datetime.fromisoformat(now["time"])
    print(f"\n  right now   {now['score']:>5.1f}  {_bar(now['score'])}")
    print(f"    {when:%a %d %b %H:%M}   current {cur:<16} water {temp:<9} wind {wind}")
    print(f"    {now['light_phase']:<9} moon {now['moon_phase'].lower()}"
          f" ({now['moon_illum']*100:.0f}%)   {now['next_tide'] or ''}")
    print(f"    → {now['explain']}")

    horizon = datetime.fromisoformat(rep["start"]) + timedelta(hours=rep["hours"])
    print(f"\n  windows to {horizon:%a %d %b %H:%M}")
    if not rep["windows"]:
        print(f"    nothing clears {args.threshold:.0f}.")
    for w in rep["windows"]:
        a, z = datetime.fromisoformat(w["start"]), datetime.fromisoformat(w["end"])
        span = f"{a:%a %H:%M} (narrow)" if a == z else f"{a:%a %H:%M}–{z:%H:%M}"
        print(f"\n    {w['score']:>5.1f}  {_bar(w['score'])}  {span}")
        print(f"           {w['current_speed']:.2f} kt {w['current_dir'] or ''}"
              f"   {w['light_phase']}   → {w['explain']}")

    # The spot-quality term is a default here, and saying so matters: on a
    # curated spot that modifier carries local knowledge, and on a coordinate
    # nobody has fished it carries nothing.
    print("\n  " + "─" * 74)
    if rep["prior_is_default"]:
        print(f"  No history at this mark — scored with the default spot prior "
              f"({rep['prior']:.2f}) and no")
        print("  preferred tide stage. Log trips here and both become yours.")

    if args.save:
        spot, _ = spots.at_coord(lat, lon)
        path = _save_mark(args.save, spot, st)
        print(f"\n  saved as {args.save!r} in {path}")
        print("  (gitignored, never transmitted)")
    print()
    return 0


def _save_mark(key: str, spot, res: dict) -> str:
    """Append a resolved coordinate to the private marks file."""
    path = spots.PRIVATE_PATH
    existing = []
    if os.path.exists(path):
        try:
            with open(path) as fh:
                raw = json.load(fh)
            existing = raw if isinstance(raw, list) else raw.get("spots", [])
        except (OSError, json.JSONDecodeError):
            existing = []
    existing = [e for e in existing if e.get("key") != key]
    existing.append({
        "key": key,
        "lat": spot.lat, "lon": spot.lon,
        "current_station": spot.current_station,
        "tide_station": spot.tide_station,
        "temp_station": spot.temp_station,
        "kind": "mark",
        "notes": spot.notes,
        "species": list(spot.species),
    })
    # Your own marks. A torn write here loses a spot you found, which
    # is the one kind of data in this project that cannot be refetched.
    cache.write_json(path, existing)
    return path


if __name__ == "__main__":
    raise SystemExit(run())
