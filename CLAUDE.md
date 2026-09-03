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
evaluate gso charts serve`.

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
- **scored** — the 6 in `score.PROFILES`, temperature bands grounded in cited
  literature. Adding a seventh means doing that research, not guessing.
- **regulated** — only where the rule was actually read out of a RIDEM or DMF
  notice.

A wrong size limit is not a bad forecast, it is a fine — and under Matt's
father's commercial licence it is worse than a fine. When the app says a rule
is not modelled, that is a fact about the app, not permission to keep the fish.
A test asserts `species.py` carries no size/season/bag numbers. **A search
result is not a source.** Regulations work belongs in the sibling `fishreg`
repo, which plays amendment streams forward to compute current state.

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

`data/tracks.jsonl` is the most sensitive file here by a distance — not "spots
you saved" but every spot you actually fished, in order, with how long you sat
on each. It, the catch log, the bait log, `my_spots.json` and `config.json` are
all gitignored, and nothing transmits them anywhere but his own machine over
the tailnet.

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
