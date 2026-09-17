# Looking at it in a real browser

`python3 tests.py` is stdlib-only, hermetic and about a second, and it stays
that way. This is separate and optional: it drives a real Chromium so the map
actually renders, which is the only way to check anything about markers,
labels or the panel covering them.

    node tools/browser-check/preflight.mjs   # REQUIRED before any UI commit
    node tools/browser-check/desk.mjs        # the desk page, which preflight does not cover
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
