# CLAUDE.md

## What this is

A fishing forecast for Narragansett Bay, built around **tidal current** rather
than tide height — that is the whole reason it exists, and the thing the
commercial apps get wrong. AGPL-3.0, stdlib-only, runs on Matt's machine and
reaches his phone over the tailnet.

The honest state of the project: **16 data sources in, a handful of logged
trips out.** Every feature added enlarges the part of the model nothing has
falsified. Read `evaluate` before proposing a new signal — it will tell you how
many trips are actually on file, and the answer governs what may be claimed.

The checkout lives at `~/glad-labs-products/tiderace`. It was renamed from
`~/Glad Labs Products/tiderace` on 2 September 2026, and the systemd units
still pointed at the old path — the service stayed "active" while serving 404
to the phone, because a process whose working directory has been deleted keeps
running and cannot read a file. If the app is up but everything 404s, check
`WorkingDirectory` in `~/.config/systemd/user/tiderace*.service` first.

```bash
python3 -m tiderace serve             # the app (systemd user unit, port 8765)
python3 tests.py                      # the suite, no runner needed
node tools/browser-check/preflight.mjs  # LOOK AT IT — required before commit
python3 -m tiderace evaluate          # does the model beat the free baseline?
```

Subcommands: `forecast spots at stations log photos bait config scrape review
regs offshore conditions basemap survey whales reports birds hms history
evaluate gso charts species serve`.

`species <name>` prints the card for one fish -- every band, what each one
rests on, the natural history, and the rules -- and is the fastest way to see
whether a claim is cited or a hand-set prior. `species --photos` fetches a
reference photograph per fish and `species --info` the natural history; both
reach the network, both are slow on purpose, and nothing on a forecast path
calls either. They are the only things in the project that touch iNaturalist
for anything but whales, or Wikipedia at all.

---

## Conventions carried from poindexter

These are the same rules, adapted. Where tiderace deviates it is on purpose and
the reason is recorded below — a deviation without a reason is a bug.

### A check that matched only a comment has not passed

Poindexter's `lib_scan_floor.py` rule, in the form this codebase needs it.
There it was lints that scanned zero files and printed "clean"; here it is
assertions about `index.html` that match the comment explaining the bug rather
than the code fixing it.

This has happened **four times**: `gzip`, `write`, `osm`, and `touch-action` —
the last one inside the very commit that added the rule. Search the page for
`touch-action` to prove `touch-action` is absent and you find the paragraph
saying it must be absent. Green test, broken app.

- Assertions about **code** run against `strip_comments(page)`.
- Assertions about **visible text** may use the raw page.
- `AssertionsCannotPassOnProse` enforces it by walking `tests.py` with `ast`.
- That test carries its own floor: if the walk stops finding assertions, it
  fails rather than passing on an empty set.

Every new test gets **mutation-checked** before it counts: reintroduce the bug,
watch the test fail. A test that has never failed has never been tested.

One trap when the mutation is scripted: Python invalidates a `.pyc` on
`(mtime, size)`, so a same-length edit — `temp=(57,` to `temp=(60,` — landing
inside the same filesystem second is invisible, the subprocess imports the
original module, and the test passes. That reads as a surviving mutation and it
is a false negative. Delete `tiderace/__pycache__` between runs. Also check
*which* assertion caught it: a mutation that produced a `SyntaxError` was
caught by the parser, not by the test, and has proved nothing.

### Prefer slicing to searching

`page.split("marker")[1]` raises when the marker moves. `assertIn(x, page)`
quietly keeps passing. Fixed-character windows (`page[1200:1400]`) broke three
times as the file grew — slice whole functions instead.

### Never commit a red HEAD

Happened three times. Twice from committing one half of a change coupled to
another session's files; once from tests pinning literals rather than intent.
Run the suite before committing, and if a change spans files another session
owns, commit the coupled half with attribution.

### Fail loud, no silent fallbacks

Carried, with one **deliberate exception**: `cache.read_json` treats a corrupt
cache file as absent. A truncated write should cost one refetch, not an
exception on a boat with no signal. Note that its `except BaseException` does
re-raise after cleaning up the temp file — it swallows nothing.

All writes to the data files are atomic (`os.replace` via `cache.write_json`),
because the server and the CLI run concurrently against the same files.

### Zero dependencies in the core

`dependencies = []`, Python ≥3.9. The optional `anthropic` extra is the only
exception, and nothing in the core path may require it. Local LLM work goes
through Ollama.

### No env vars

Settings live in the gitignored `data/config.json`, matching poindexter's
minimize-env-vars rule. API keys (`protomaps_key`, `ebird_key`) live there and
**only** there.

---

## Deliberate deviation: tunables stay in code

Poindexter's rule is that every tunable goes in `app_settings` — "could a
customer tune this? then it is not a literal." **Tiderace does not follow
this**, and the reason matters:

`BIRD_DISCOUNT = 0.55`, `HALF_LIFE_DAYS = 4.0`, `SIGMA_NM = 1.2`,
`CONJUNCTION = 0.30`, `DRIFT_MAX_KT = 2.0` and their neighbours are **not tuned
values. They are unvalidated priors waiting on a catch log.** Exposing them as
settings today would let anyone tune their way to a forecast that looks
excellent and predicts nothing — the exact failure `evaluate` exists to catch.

They become configurable when there are enough logged trips for `evaluate` to
say whether a change helped. Not before. Until then they stay in the code where
changing one is a diff someone has to justify.

This is a decision, not an oversight. Do not "fix" it.

---

## Rules specific to this project

### Never invent a regulatory number

`species.py` has three tiers, and the difference between them is what is being
claimed:

- **loggable** — all 35 species. Costs nothing, claims nothing.
- **scored** — 34 of the 35, on two scorers, each profile declaring which
  tier of claim its bands are. **this water**: the fourteen inshore fish whose
  bands came from this bay's own surveys and the GSO trawl. **regional**:
  bluefin and mako (tagged off Cape Cod and the northeastern US), monkfish
  (a Narragansett Bay figure of its own). **general biology**: the species'
  published biology from wherever it was studied -- cod, pollock, haddock,
  cobia, Spanish mackerel and northern kingfish on the bay scorer, weighting
  only temperature and season because nothing published says what current
  they want here; eleven offshore fish on the pelagic scorer. Matt set the
  rule on 5 September 2026: "don't invent any number from nothing, but we
  are inventing forecasts based on fact." So a band from another ocean's
  literature is allowed, cited to the document and page, and labelled on the
  card; a band from nowhere is not. Adding a species means finding the
  document, not guessing. The card says the tier; the slider strip says
  "unvalidated here" for anything not this water. Two are refused: grey triggerfish, whose one reachable figure is an
  AquaMaps model envelope, and menhaden (15 September 2026), whose one
  published figure is a preference "near 18C" -- a trapezoid needs four
  numbers, and schools are found by eye, not by the bottom structure the
  bay scorer ranks. A model's output is not a measurement and one number
  is not a band.

  The offshore scorer (3 September 2026) keeps the same two tiers apart:
  the bands in `pelagic.py` each name the document and page they came from
  (NOAA's 2017 HMS EFH Amendment 10; SAFMC's 2003 Dolphin Wahoo FMP; Vaudo
  et al. 2016 for mako) and the season months are OBIS records; the weights
  are priors no document can give and every score carries `unvalidated`.
  Bigeye and thresher have no SST band and get none -- reported, not scored,
  like depth inshore. Blue marlin and porbeagle have too few records here
  for a season and carry none. Mahi's and wahoo's weed lines are
  unmeasurable and the score says so -- but surface convergence from the HF
  radar field stands in for where floating things collect, for the fish
  whose literature names floating structure, and only where the radar
  covers (18% of the box, nothing south of 40.67 N, measured 5 September
  2026); outside coverage the term is absent, never zero. Positions are the
  sharpest temperature breaks in the MUR grid, the steepest bottom in the
  DEM grid, and the strongest convergence zones for those fish, one
  candidate per feature; a fish tied to none of them gets fronts and walls
  as sample points, labelled as such. The wall's steepness carries the
  structure term because a candidate found on the wall is 0 nm from it by
  construction.

- **regulated** — only where the rule was actually read out of a RIDEM or DMF
  notice: hand-typed into `regs.py` by a person, or applied from a notice by
  the overlay. Menhaden (15 September 2026) is the case with no table row
  at all -- `commercial_status` is known through the overlay alone, says
  `from_notices_only`, and shows the notice, linked, and nothing else. **Scored no longer implies regulated**, and that is deliberate: 8 of
  the 14 have no transcribed rule, because the only way to keep the old
  invariant would have been to type eight size limits in from memory. What is
  enforced instead is that the app says so out loud — `paintLegal` on the
  phone, and both CLI paths, print "rules not modelled" rather than going
  silent. The two tests that asserted scored ⊆ regulated were rewritten to
  assert that.

Two paths carry rules into the app, and the difference is who read them.
The in-season RIDEM notices are parsed by template (`ridem.py`), played
forward (`reconcile.py`) and applied as an overlay beside `regs.py`
(`applied.py`) with the notice and the sentence attached — that is mirroring
a source, and it runs unattended. The annual limits table is what `regs.py`
is typed in from by a person, and nothing automates that. What the app does
instead is fingerprint both pages daily (`scrapelog.record(content=...)`) and
say on the desk whether either changed; **a limits-table change after
`COMMERCIAL_CHECKED_ON` is the signal to re-transcribe `regs.py`**, and it is
the only regulation event that still needs a human. A number the *model*
read (`parser="model"`, from `--use-model`) never reaches the overlay.

The overlay keys a rule by species, mode, change, sub-fishery **and
Aggregate Program**, and `commercial_status` picks the possession limit for
the programme in `config.json` (`aggregate_program: none` is general
category). Without that, RIDEM's one-breath "400 lb/day, or 2,800 lb/week
for Aggregate Program participants" put the weekly number on a
general-category strip (15 September 2026).

**Reports and bait are applied on arrival and confirmed after.** Matt, 15
September 2026: "I don't have time to go chasing them all. I'd rather just
confirm them after they're applied." A placed, high- or medium-confidence
bait sighting from a report goes into the bait log the moment it is read
(the timer runs `scrape --apply-bait`), a catch report counts as a witness
the moment it is read, and `extract.reconcile_queue` brings the queue up to
that rule after every scrape. The desk's Confirm tab and `tiderace review
--confirm/--retract ID` are the review: a retraction takes the sighting back
out of the log and the report off the witness list. Regulations never queue;
the overlay applies them itself. The one thing this does not do is guess a
place: a sighting with no coordinate stays pending and unused.

A wrong size limit is not a bad forecast, it is a fine — and under Matt's
father's commercial licence it is worse than a fine. When the app says a rule
is not modelled, that is a fact about the app, not permission to keep the fish.
A test asserts `species.py` carries no size/season/bag numbers. **A search
result is not a source.** Regulations work belongs in the sibling `fishreg`
repo, which plays amendment streams forward to compute current state.

### A binomial is the only key; a common name is not

Every one of the 37 species now carries a scientific name from a document
(`species.SCIENTIFIC`, plus two that read through to `hms.py`), and every
lookup -- iNaturalist for a photograph, Wikipedia for natural history -- goes
through it. There is no common-name fallback anywhere, and there must not be
one: on 17 September 2026 the alias lists this project already had resolved
"False Albacore" to an Indo-Pacific kawakawa, "grey trout" to a lake trout,
"sea mullet" to a mullet, and "Weakfish" to a genus. Four plausible wrong
animals, from names Matt actually says. The fifteen missing names came from
NOAA's MRIP species-code table, each with its ITIS TSN, cross-checked against
WoRMS -- which flagged two the 2008 table had superseded and where the
project's own values were already right.

### Wikipedia is background, never a band and never a rule

`wiki.py` reads natural history -- what the fish looks like, where it lives,
what it eats, when it spawns. The licence for reading a tertiary source at all
is that **nothing computes on it**: no scorer, no prospector and no regulation
path imports it, and a test asserts that. The day something does, the licence
is gone.

Sections about fishing are refused by a default-deny allowlist, because the
striped bass article carries one headed "Current fishing regulations" and a
size limit nobody read out of a RIDEM notice has no business on the same card
as the legal strip. A second net drops any surviving paragraph that reads like
a rule. Both refusals are counted and shown; a filtered source that does not
admit it was filtered is the more misleading of the two.

### A reference photograph answers "what does this look like"

Wikipedia's taxobox image first, iNaturalist second. Matt, 17 September 2026:
"the tautog fish image looks incorrect" -- then, "maybe the tautog image is
correct, just different than what I'm used to seeing." Both true. It was a
real *Tautoga onitis* and a pale juvenile in the weed, which is not the fish
anyone recognises. iNaturalist's `default_photo` is the observation people
liked best; a taxobox image is the one an editor chose to show what the
species looks like. Different questions, and only the second is ours. Getting
that order right filled all nine of the gaps as well.

### Three kinds of no, not two

A lookup that could not be carried out is a fact about the network. Until
17 September 2026 `fishpic` recorded it as `resolved: False`, which the card
reads out as "no confident match for this fish" -- five species carried that
verdict and three of them resolve on the first try. "Nobody looked", "looked
and could not be sure" and "tried to look and could not reach the server" are
three different facts and the card says which. The same trap caught a fourth
time the same day: gating the card on sections alone made scup, whose article
is all lead and no section, report "not fetched yet" after being fetched.

### There is no list of spots

Since 3 September 2026 the app holds no curated positions. Matt: "the goal is
for the system to come up with a list of coordinates that would be the best
spots to try based on species and conditions." `prospect.candidates_for`
does that: a bathymetric position index over the charted soundings finds
structure bay-wide (radius 400 m, because that is the measured sounding
spacing -- at 200 m the neighbour floor leaves only rocks awash), gates it
for the fish (fishable depth, the published depth band, below the bridges
for bonito and albies), binds each candidate to its stations, and the grid
scores them over 48 hours. `spots.py` keeps the Spot type, the coordinate
parser, `at_coord`, and your marks. A test asserts no Spot literal returns
at module level and that the landmark names stay out of the file.

Two things this means for future work: a new species needs no spot listing,
only its profile (and a depth band if one is published); and the nineteen
hand-verified station bindings live on in `tests.py` as a table, since the
resolver still has to reproduce them.

What it cost, so nobody rediscovers it: a landmark named in a voice or text
report no longer resolves to a coordinate (`extract._match_spot` matches only
your own marks); the sighting is kept with its place text and reviewed.

### Provenance is not decoration

Every datum in `survey.py` carries `{value, source, resolution_m, note, when}`.
Resolutions span 1 m (a sounding) to 6000 m (HF radar) — four orders of
magnitude. A layout that renders them identically is claiming they are equally
precise, which is a lie the numbers cannot defend.

Rank evidence, never average it. Independent witnesses corroborate; two
readings from one origin do not.

### Bathymetry is modelled, and says so

Matt: "I'm not using this for navigation so defaulting to models is fine."
The labelling stays anyway — this is AGPL and someone else may run it.
Every generated contour carries `model: true`.

### Privacy is the product

His father's words: **"don't give away my good spots."** There is no sharing
feature and there should not be one.

`data/tracks.jsonl` was the most sensitive file here by a distance — not
"spots you saved" but every spot you actually fished, in order, with how long
you sat on each. The recorder that wrote it (REC) was removed on 5 September
2026 — Matt: "honestly probably don't need the trip tracking in the app at
all, just logged catches" — because a web page cannot keep reading GPS with
the phone locked, so it recorded the ramp and the dock and little between.
The file stays where it is, gitignored, and nothing reads it now. It, the
catch log, the bait log, `my_spots.json`, `data/photos/` and `config.json`
are all gitignored, and nothing transmits them anywhere but his own machine
over the tailnet.

Before any `git add -A`: check. 142 iNaturalist cache files (16 MB) went in
that way once, and 3.8 MB of blobs are still in pushed history.

### Never kill the server blindly

`pkill -f "tiderace serve"` took the app off the tailnet mid-session, and a
later pkill pattern nearly matched the agent's own command. Find the PID with
`ss -tlnp` and kill that. It runs as a systemd user unit with lingering
enabled, so it survives logout.

### Never write to the real logs

Test data landed in Matt's actual `catch_log.jsonl` three times, and a test
track in `tracks.jsonl` once. Tests use temp paths. The catch log is the
scarcest thing in the project and the only irreplaceable one.

---

## Look at it before you commit

**Any change that touches the UI runs `node tools/browser-check/preflight.mjs`
before it is committed, and the run is reported.** Not after Matt finds it. This
is a standing instruction from him, given on 2 September 2026, and it exists
because of what that day looked like:

Nine self-inflicted regressions shipped and were found by him, not by me — the
wind-farm marks knocked off the map by a shadowed route, open/closed invisible
on the phone for several commits, the desktop layout stretched to a strip, the
contour numbers erased by a global replace reaching into MapLibre paint, a CSS
token defined as itself, the stale-build banner crying wolf on every desktop
load. Every one was obvious on screen and none was subtle in the diff.

**The whole suite was green through all of it.** That is the point, and it is not an
argument against the suite: a unit test checks what I thought I built, and
every one of those bugs lived in the gap between that and what the page did.
Roughly eight of the tests written that day could not fail at all — matching a
comment instead of code, `"sheetLeft + 4"` inside `"sheetLeft + 400"`, a
condition surviving `if (false)`.

The preflight covers what actually broke: both viewports, both themes,
uncaught page errors, the wind-farm route, sheet geometry, CSS vars leaking
into MapLibre paint, tokens that resolve to nothing, labels drawn on the panel
or on each other, the legal strip's presence and share of the sheet, the top
bar clipping, the species picker, false staleness warnings, and WCAG AA
contrast composited over what is actually behind the text.

It is `tools/`, not `tests.py`: the suite stays stdlib-only, hermetic and about
a second, and this needs a real browser and about ninety. See that directory's
README for why the built-in preview pane cannot do it — it blocks the hosts the
basemap style needs, so the map never loads, `MARKERS` stays empty, and a check
for "no labels overlap the panel" passes against nothing. That happened twice
before the harness existed.

Two habits that go with it, both learned the same day:

- **A check that found nothing has not passed.** Every geometry check reports
  how many candidates it examined, and sets its own precondition. The
  panel-overlap check drives a marker behind the panel on purpose, because the
  desktop rail overlaps the map by a ~60 px sliver and a default view finds
  nothing to fail on. It failed loudly twice while being written, which is the
  behaviour to preserve.
- **Measure the thing before changing it.** "Clunky" was 2,590 px in an 812 px
  viewport. "Labels clipping" was a sheet covering the whole window. "I can't
  pull it down" was a drag handle 269 px above the top of the screen. In each
  case the first guess was wrong and the measurement was one command away.

---

## Front end (`tiderace/web/index.html`)

One file, no build step, no framework. Service worker version in `sw.js` must
be bumped on every change or phones keep the old shell.

- **Mobile layout switches on `pointer:coarse`, not width.** Chrome's "Desktop
  site" reports a 980px viewport on a phone; a width breakpoint gets it wrong.
  The app detects and reports this rather than compensating silently.
- **The sheet has three states** — `full` / `peek` / `shut` — owned by one
  `setSheet()`. Callers previously set the classes by hand and the pair was not
  always complete, so it could hold `up` and `peek` at once and stylesheet
  source order decided the outcome. A test forbids touching those classes
  anywhere else.
- **`touch-action` belongs on the drag handle, never the sheet.** It intersects
  up the ancestor chain, so `none` on `#sheet` also stops `#sheetbody` — the
  region holding every reading — from scrolling under a finger.
- **Boot runs last.** Calling anything that closes over a `let`, or a `const`
  arrow, from above its declaration hits the temporal dead zone and takes the
  *whole script* down — which is how `showConditions` once stopped existing and
  tapping the map did nothing. Two separate bugs of this shape so far.
- **Dots are coloured relative to the field, not to the 0-100 scale.**
  `colour(s)` is absolute and on a slow day painted thirty positions the same
  muted teal (measured 9 September 2026: 27.7 to 68.7 spanned two nearly
  identical colours at 15-20 px). `qualityColour(quality(s, fieldAt(TI)))`
  runs the accent down to slate across the best-to-worst of the positions at
  the slider time; the top one is 30 px with a halo and the top eight carry
  the digit they have in the ranked list. The number on the card stays
  absolute. A tap within 22 px of a position on a touch screen selects it
  before the chart-feature query runs (`nearestSpot`); the dot itself only
  took taps out to ~10 px, and a miss reported the water under the finger.
- **Coordinate labels yield to the chrome.** `clampLabels` hides a label
  that would draw into the top bar, the sheet, the time bar or the HERE
  disc, and keeps at most five on the phone plus the selected one. Anything
  new that floats over the map goes on that list, or the labels will run
  under it (HERE did, 11 September 2026).
- Verify on a real touch viewport, not by reading the CSS. Measure the thing
  Matt complains about before changing it; "clunky" turned out to be 2,590 px
  of content in an 812 px viewport, which is a structural fact, not a taste.

---

## Working style

- Matt fishes this water commercially under his father's licence. He is on a
  boat with a rod in his hand — CLI is not available to him there.
- Autonomous work, no "what's next".
- No subagent delegation (billed separately from the Max subscription).
- Report faithfully. If tests fail, say so with the output; if something was
  skipped, say that.
