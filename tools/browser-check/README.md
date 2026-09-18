# Looking at it in a real browser

`python3 tests.py` is stdlib-only, hermetic and about a second, and it stays
that way. This is separate and optional: it drives a real Chromium so the map
actually renders, which is the only way to check anything about markers,
labels or the panel covering them.

    node tools/browser-check/preflight.mjs   # REQUIRED before any UI commit
    node tools/browser-check/desk.mjs        # the desk page, which preflight does not cover
    node tools/browser-check/walkthrough.mjs # drive both pages the way a person does
    node tools/browser-check/check.mjs       # just the panel-overlap check

`preflight` is the one to run. Thirty checks across both viewports and both
themes, each built from something that shipped broken on 2 September 2026 and
was found by Matt rather than by the 503 green tests.

Needs playwright. It resolves `playwright` from node_modules if present, and
otherwise falls back to a sibling checkout — edit `CANDIDATES` in check.mjs if
yours lives elsewhere.

    npm i -D playwright && npx playwright install chromium

`desk.mjs` covers `/desk`, which `preflight` does not touch at all -- the desk
shipped unlooked-at until 17 September 2026, when its in-force list was
rewritten with all 671 unit tests green and not one of them able to see the
page. It found two things in its first run: the note column was `white-space:
nowrap` prose 345 px wide, taking a 375 px phone to 538 px of sideways scroll,
and the check's own precondition (`#confirm .empty`) was satisfied by the
"reading…" placeholder the section ships with, so every count in the first
draft measured an empty page and passed. Wait for `#confirm h2`, which only
exists once the fetch has rendered.

It covered the Confirm tab and nothing else until 18 September 2026 -- the
same gap one level down, and Matt named it: "should probably check all of
them." It now walks all seven. Every tab gets the checks that apply to any
tab (it drew a view rather than the placeholder, nothing spills its card, no
sideways scroll, no uncaught error, AA contrast over what is actually
behind the text), and In force and Fish carry checks of their own.

Four things that pass came out of making it fail on purpose, and they are
the ones to preserve:

* **A heading is not always the last thing to arrive.** `h2` is the right
  readiness signal for six tabs and wrong for Fish, which writes its heading
  and picker and then awaits the first species card -- measured in that
  window it reported "1 heading, 0 cards" and failed. Hence the fourth
  column in `TABS`, an extra selector to wait for.
* **`naturalWidth` is 0 until the image loads.** The 37-card sweep measured
  mid-load and called 15 cards uncredited, which was not just a false
  failure but the *wrong* failure -- a licence problem reported where there
  was a slow image. `did-not-load` and `uncredited` are separate labels now.
* **"Longer than ten characters" could not fail for its stated reason.** The
  credit paragraph also carries the binomial, so blanking the attribution
  left it 40 characters long and green. It is compared against the string
  the API actually produced, and it is the paragraph immediately after the
  image -- the natural-history licence line shares the class and would
  otherwise vouch for an image it has nothing to do with.
* **One broken tab used to kill the run.** An exception escaped before the
  summary line, so a run that had found six real failures printed nothing
  and looked like a crash. Each tab is trapped; a tab that throws fails
  itself and the run still reports.

`walkthrough.mjs` is the other half of `preflight`: preflight checks invariants
that must hold of any build, and the walkthrough opens every screen, presses
every control and switches every mode, watching for a screen that renders
nothing or a console that fills up. It takes a URL and defaults to
`http://localhost:8765`, so pointing it at a server of your own is
`node tools/browser-check/walkthrough.mjs http://localhost:8799`.

One thing it learned the hard way, and it is the `.credit` bullet above for the
third time:

* **The species card puts two different kinds of thing in one class, and
  `querySelector` takes the first.** Both of its Fish checks measured the
  wrong element for it. `the claim names its document` asserted a bracketed
  citation against the first `.tclaim` -- which is the Wikipedia
  natural-history note, rendered above the bands and sharing their class, so
  the check read the encyclopedia disclaimer and never looked at a band. It
  takes the claim of a band marked `cited` now, every one of them, and
  reports the count so a selector matching nothing fails instead of passing
  on an empty set. The photo check had the same shape one class over and the
  fix is the one desk.mjs already uses: the credit is the paragraph
  immediately after the image. Anything looser finds the natural-history
  licence line and vouches for an image it has nothing to do with.

  Its other half was a *stale* expectation rather than a misaimed one: it
  asserted the provider was `iNaturalist`, and the photo order changed to
  Wikipedia's taxobox first on 17 September 2026, so it failed on a correctly
  credited Wikimedia image. What the licence actually requires is somebody, a
  source and a licence -- which is what it asks for now, and which is why the
  test is desk.mjs's regex rather than a second opinion about the same rule.

## Why this exists

The agent's built-in preview pane blocks external hosts. The basemap style
pulls glyphs and sprites from protomaps.github.io, so `map.isStyleLoaded()`
never turns true and `MARKERS` stays empty — and a check for "no labels overlap
the panel" against zero markers passes. That is worse than no check, because it
reads like evidence. It happened twice before this file existed.

Two traps worth keeping:

* **The style takes ~15 s.** `MAP_READY` goes true before it finishes, and
  markers are unprojected until it does.
* **Headless fires no map move**, so every marker keeps its anchor offset —
  all of them at `translate(-9.4px, -9.4px)` in the corner. One
  `panBy([1, 0])` projects them.

And one about the app: on desktop the sheet is a 420px rail at `right:0` while
the map is `100vw - 360px`, so the rail sits mostly over the sidebar and
overlaps the map by a ~60px sliver. A default view finds nothing behind the
panel, which is why `driveMarkerBehindPanel` exists — it puts a real marker
there so the check has something to fail on.
