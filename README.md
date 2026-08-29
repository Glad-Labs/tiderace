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

## Seasonal timing, from 65 years of measurement

```bash
python3 -m tiderace gso            # weekly climatology + thermal windows
```

The species month tuples used to be guesses, and one of them was provably
wrong. They are now derived from the **URI GSO Fish Trawl Survey** — weekly
water temperature at two fixed stations since 1959, 6,583 observations, parsed
with nothing but the standard library (an `.xlsx` is a zip of XML).

Two things worth knowing about what those files actually contain:

- **Temperature is weekly** — the valuable half. It gives a climatology: the
  water you should expect in any given week, and therefore how far ahead or
  behind normal this year is running.
- **Catch is annual means**, not weekly, so it cannot give seasonal timing
  directly — only long-term abundance trends. There is also no striped bass in
  it, because a bottom otter trawl is the wrong gear for them.

So presence is *derived*: each species has a thermal preference, and 65 years
of weekly temperature says when the bay historically sits inside it. The data
finds tautog's bimodal spring/autumn season on its own, correctly excluding the
summer months a flat month-list had wrong.

**What temperature cannot tell you** is migratory peak. Stripers peak in
May–June and again in September–October because they are *moving through*, not
because midsummer is thermally hostile. Those months stay hand-set, and the
code says so.

The payoff is season shift. A spring running 5°F warm is about **17 days
ahead**, and the whole run moves with it:

```
May, warm    5.3°F warm for the week, spring warm-up ~17 days ahead
late Oct, cold   7.9°F cold for the week, autumn cool-down ~21 days ahead
Feb              1.7°F warm for the week
```

February gets no day estimate on purpose: converting a temperature anomaly into
a timing shift only works where the climatology is actually moving. On the
summer plateau and winter floor the curve is flat, and dividing by that slope
produced a meaningless "35 days" that was purely the clamp.

Data © University of Rhode Island Graduate School of Oceanography. Their
[data use policy](https://web.uri.edu/gso/research/fish-trawl/) asks that URI's
role in collecting it be cited in any use — `tiderace gso` prints the citation.

## Bait

The dominant variable, and the one you cannot compute. Tide and light come out
of an equation; bait does not. So it is an **observation layer that decays in
space and time**, not another physics term.

```bash
python3 -m tiderace bait --spot conimicut --bait "peanut bunker" --abundance loaded
python3 -m tiderace bait --spot whale_rock --bait bunker --abundance none   # also useful
```

Three things this gets right that a `bait: yes/no` flag would not:

- **Relevance is per predator.** A wall of adult bunker is everything to a bass
  and literally nothing to a tautog, which wants crabs. Sightings are scored
  through what the target actually eats.
- **Absence is evidence, but only when observed.** No reports means *unknown*
  and scores neutral. Somebody explicitly reporting "nothing around" is a real
  negative. Conflating those two penalises every spot nobody has visited.
- **It decays.** Half-life of four days, spatial falloff over ~1.2 nm. A
  sighting two miles away and a week old barely registers.

Bait multiplies the whole score (0.75× to 1.35×) rather than nudging one term —
perfect water with nothing to eat in it is still an empty spot.

This is also the highest-value target for the LLM extraction layer: published
reports talk about bait constantly, and turning "bunker still thick off the
point" into a dated, located, structured row is exactly the job language models
are good at.

## Privacy

**Nothing you record leaves this machine.** There is no sharing, no sync, no
account, no telemetry. The only outbound calls are GETs to NOAA and NWS for
tide, current and weather.

- The server binds to `127.0.0.1` and warns loudly if you ever move it.
- `data/catch_log.jsonl`, `data/bait_log.jsonl` and `data/my_spots.json` are
  gitignored — they are the irreplaceable part and should never be pushed by
  accident.
- **Your own marks go in `data/my_spots.json`** (see `my_spots.example.json`).
  The nineteen built-in spots are public landmarks on every chart; your marks
  are not, and `spots.public_only()` is the only set anything shareable should
  ever be built from.
- Weather lookups are the one place a coordinate leaves the machine, so they
  are rounded to ~1 km first. NWS grid cells are ~2.5 km, so nothing is lost
  from the forecast — but your mark does not end up in an access log at 11 m
  precision.

The first thing anyone says when they hear about an app like this is *"don't
give away my good spots."* They are right, and local-first keeps that decision
open forever — whereas shipping sharing closes it permanently.

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
