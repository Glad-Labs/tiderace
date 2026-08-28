# tiderace

Physics-first fishing forecasts for Narragansett Bay. No API keys, no
dependencies, no accounts — everything below runs on public NOAA and NWS
endpoints using only the Python standard library.

```bash
python3 -m tiderace serve                          # map UI at localhost:8765
python3 -m tiderace evaluate                       # does it beat doing nothing?
python3 tests.py                                   # 16 tests, no network needed
python3 -m tiderace --species striped_bass         # terminal forecast
python3 -m tiderace --species fluke --spot dyer_island
python3 -m tiderace spots
```

## The map

`serve` runs a local web app: the bay with every spot coloured by score, a
48-hour time scrubber, per-spot conditions with a score curve, and a trip
logger that writes straight into the catch log.

It is built on **MapLibre GL JS** (BSD-3), not Mapbox GL JS — which went
proprietary at v2 and requires an access token with usage-based billing.
MapLibre is the community fork of the last BSD-licensed Mapbox GL and is
API-compatible, so switching is a one-line change if you ever want Mapbox's
hosted styles. For an open-source project, building the core on a metered
proprietary SDK would undercut the whole point.

Tiles are keyless too:

| layer | source | licence |
|---|---|---|
| basemap | OpenStreetMap | ODbL, attribution required |
| seamarks — buoys, beacons, lights | OpenSeaMap | ODbL |
| chart features — rocks, wrecks, bottom | NOAA ENC | public domain |

## Chart overlays — the structure that holds fish

```bash
python3 -m tiderace charts        # one-time download, ~770 KB
```

Pulls NOAA Electronic Navigational Chart features for the bay from the
**ENC Direct to GIS** service and caches them as GeoJSON, so the map loads
instantly and works offline.

| layer | features in the bay | why it matters |
|---|---:|---|
| underwater / awash rocks | 3,460 | 2,269 cover and uncover — the classic striper piece |
| wrecks | 102 | 55 carry a charted depth, −4 to 112 ft |
| obstructions | 267 | anything else hard on the bottom |
| seabed type | 958 | tautog want boulder, fluke want sand |
| water turbulence | 5 | charted rips and overfalls |
| weed / kelp | 23 | bait cover |

Two things worth knowing if you extend this:

- **Usage bands matter.** Narragansett Bay detail lives in the `harbour` band.
  Querying `general` returns a silent, very confusing zero.
- **Substrates are compound.** S-57 packs bottom type into strings like
  `"sand,rock"` and `"mud,shells,pebbles"` — 28 distinct combinations in this
  bay. Exact matching drops nearly all of them; test for the hardest substrate
  present instead.

Bottom type is joined to each spot by nearest charted sample and shown in the
detail panel — 17 of 19 spots have one within 0.35 nm. It is **not** in the
score yet. That is the obvious next model improvement: substrate is the missing
half of a structure model, and the charts already know it.

NOAA also publishes raster chart tiles at `tileservice.charts.noaa.gov`, which
would make a better basemap than OSM for US waters. That host was unreachable
when this was built — worth retrying from your own network.

The map is a view onto the data, not a prerequisite for it: if WebGL or the
tile host is unavailable, the ranked list, spot detail and trip logger all
still work.

## What it actually does

For every spot, at 30-minute resolution, it assembles:

| feature | source |
|---|---|
| tidal **current** speed, direction, stage | NOAA CO-OPS current predictions |
| tide height and next high/low | NOAA CO-OPS water level |
| water temperature | NOAA CO-OPS observed |
| wind, air temp, sky, barometric trend | NWS gridpoints (forecast) / station observations (past) |
| sun elevation, light phase | computed (NOAA solar algorithm) |
| moon phase, spring/neap strength | computed |

…then scores it against a per-species response model and reports the best
windows with the reasoning attached.

## The one design decision that matters

**Every spot is bound to its own tidal-current station, not just a tide
station.** Tide height at Newport tells you nearly nothing about whether water
is ripping past Whale Rock. Current does. There are 38 current-prediction
stations inside the bay and the generic national fishing apps use none of
them — they key everything off a single tide-height curve.

## What is honest about the model

The species profiles in `tiderace/score.py` and the `quality` / `best_stage`
priors in `tiderace/spots.py` are **conventional wisdom written down**, not
fitted parameters. They are a starting point that should be measurably wrong
in places.

That is what the catch log is for:

```bash
python3 -m tiderace log --spot whale_rock --species striped_bass \
    --count 0 --at 2026-08-27T05:30 --method bucktail --notes "flat calm, no bait"

python3 -m tiderace history
```

Logging snapshots the **full feature vector** at that time and place — current
speed, stage, water temp, light phase, pressure trend, moon — not just the
result. That is the difference between a diary and a training set. Around 60+
trips, including blanks, the hand-tuned weights can be replaced with fitted
ones.

**Log the blanks.** A model trained only on good days learns that every day is
good.

## Layout

```
tiderace/
  astro.py      sun elevation, moon phase, spring/neap  (pure stdlib)
  sources.py    NOAA CO-OPS + NWS clients, disk-cached
  spots.py      19 bay spots, each bound to verified stations
  features.py   joins sources into an hourly feature vector
  score.py      per-species response curves and the scorer
  log.py        catch log + condition snapshotting
  cli.py        forecast / spots / log / history
```

## Regulations

`tiderace/regs.py` gates every forecast on RI season dates and surfaces slot,
size and bag limits. A forecast that ranks a closed species is not just wrong,
it is telling you to break the law and pressure a fishery that is meant to be
left alone.

These values are **transcribed by hand and not authoritative.** RIDEM amends
them mid-season. `CHECKED_ON` and `STALE_AFTER_DAYS` make staleness visible
rather than silent, and the CLI prints the source on every run. Confirm before
you fish.

## Does it actually work?

```bash
python3 -m tiderace evaluate
```

The bar is not "better than random" — it is **better than the free advice every
angler already gives you**: fish moving water at dawn or dusk. That baseline
needs no app, no NOAA calls and no model, and it is implemented in
`evaluate.baseline()` so the comparison is honest. If tiderace cannot beat it,
tiderace is a decoration on a tide chart.

Two biases make naive evaluation flattering, and both are structural:

- **Selection.** You only log trips you took, and you took them when conditions
  looked good. The model is scored on a sample it helped choose.
- **Feedback.** Once the app recommends a spot you fish it, log it, and the
  model learns that spot is productive *because it sent you there*.

Every log entry carries `decided_by` (`angler` or `app`) so those two can be
compared rather than silently blended. If most of your log is app-chosen,
`evaluate` says so and stops claiming accuracy.

## Verified

Everything below was exercised against live endpoints:

- All 19 spots score across 96 half-hour steps with no source errors.
- Scrubbing 14:00 → 01:00 moves Whale Rock from 35 to 86 — daytime August
  stripers are correctly poor, the midnight ebb correctly good.
- Tautog in August collapses to the high forties, flagged
  `held back by seasonal timing, water temperature`.
- Trip logging round-trips through the web form into the catch log.

The map itself could not be *visually* confirmed in the build environment —
the browser pane would not composite, which pauses `requestAnimationFrame`
and stalls MapLibre's render loop. MapLibre, WebGL and tile fetches were all
confirmed present. Open it in a real browser to see it draw.

## Known gaps

- Species profiles are priors, not measurements (see above).
- `spring_strength` uses a mean-synodic moon approximation — fine for
  spring/neap, not for anything needing minute accuracy.
- Water temperature comes from two bay stations, so a spot inherits the
  nearest one. The upper bay genuinely does run several degrees warmer than
  the mouth, and the model reflects that, but it is not a real field.
- No bait, no chlorophyll, no thermocline. Bait presence is the single
  biggest missing variable and the hardest to get.

## Licence

**AGPL-3.0-or-later.** Chosen deliberately over MIT: the value of this project
accrues in community catch data, and AGPL means anyone who runs a modified
version as a network service has to publish their changes. A permissive licence
would let a commercial app absorb the whole thing and put it back behind the
subscription this exists to avoid.

Practical consequence for contributors: `serve` exposes a source link in the UI
and `source_url` from `/api/meta`, which is how section 13 is satisfied for a
networked app. Keep that working if you fork it — update `SOURCE_URL` in
`tiderace/__init__.py` to point at *your* repository.

## Data sources and attribution

NOAA CO-OPS (tides, currents, water temp) and NWS (weather) are public domain.
The URI GSO Fish Trawl Survey and RIDEM Coastal Trawl Survey are the intended
sources for seasonal-presence priors; the GSO data carry a citation
requirement — see their data use policy before redistributing anything
derived from them.
