/* A real browser, because the agent's built-in preview pane cannot run this app.
 *
 * The pane blocks external hosts, and the basemap style pulls glyphs and
 * sprites from protomaps.github.io, so `map.isStyleLoaded()` never turns true
 * and MARKERS stays empty. Every "no labels overlap the panel" check run in
 * there was measuring an empty set and reporting success -- which is worse
 * than not checking, because it reads like evidence.
 *
 * Two things this file exists to remember:
 *
 *   The style takes ~15 s to settle. Waiting on MAP_READY is not enough; it
 *   goes true before the style finishes and markers are still unprojected.
 *
 *   Headless never fires a map move on its own, so markers keep their anchor
 *   offset -- every one of them at translate(-9.4px, -9.4px), stacked in the
 *   corner -- until something nudges the map. One panBy([1,0]) fixes it.
 *
 * Optional and not part of `python3 tests.py`, which stays stdlib-only,
 * hermetic and about a second. This needs playwright; see the README.
 */
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

const CANDIDATES = [
  'playwright',
  '/home/mattm/glad-labs-website/node_modules/playwright/index.mjs',
];

async function loadChromium() {
  const require = createRequire(import.meta.url);
  for (const spec of CANDIDATES) {
    try { return (await import(spec)).chromium; } catch (_) {}
    try { return require(spec).chromium; } catch (_) {}
  }
  throw new Error('playwright not found — see tools/browser-check/README.md');
}

export async function open(url = 'http://localhost:8765',
                           { width = 1600, height = 900 } = {}) {
  const chromium = await loadChromium();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width, height } });
  await page.goto(url, { waitUntil: 'domcontentloaded' });
  await page.waitForFunction(
    () => typeof MAP_READY !== 'undefined' && MAP_READY
       && typeof map !== 'undefined' && map.isStyleLoaded() && map.loaded(),
    null, { timeout: 90000 });
  await page.evaluate(() => { map.panBy([1, 0], { duration: 0 }); });
  await page.waitForTimeout(1200);
  return { browser, page };
}

/* Markers the sheet covers, and whether any of them is still drawn.
 * `coveredByPanel` is the floor: a run that found nothing behind the panel
 * proved nothing, exactly like the empty-MARKERS runs it replaced. */
export const labelsUnderPanel = page => page.evaluate(() => {
  const sh = document.getElementById('sheet').getBoundingClientRect();
  let covered = 0; const showing = [];
  for (const m of Object.values(MARKERS || {})) {
    const el = m.el; if (!el) continue;
    const box = el.getBoundingClientRect();
    if (box.width === 0) continue;
    if (!(box.bottom > sh.top + 4 && box.right > sh.left + 4
          && box.top < sh.bottom && box.left < sh.right)) continue;
    covered++;
    const lbl = el.querySelector('.lbl');
    const vis = getComputedStyle(el).visibility !== 'hidden';
    const lblVis = lbl && getComputedStyle(lbl).visibility !== 'hidden';
    if (vis || lblVis)
      showing.push({ name: (lbl ? lbl.textContent : '').trim().slice(0, 24),
                     marker: vis, label: !!lblVis });
  }
  return { panel: [Math.round(sh.left), Math.round(sh.top),
                   Math.round(sh.width), Math.round(sh.height)],
           coveredByPanel: covered, stillShowing: showing };
});

/* Put a real marker behind the panel on purpose, so the check above has
 * something to find. Without this the desktop rail sits almost entirely over
 * the sidebar and overlaps the map by a ~60px sliver, so a default view can
 * come back clean while proving nothing. */
export const driveMarkerBehindPanel = page => page.evaluate(async () => {
  const sh = document.getElementById('sheet').getBoundingClientRect();
  const one = Object.values(MARKERS)[0];
  if (!one) return null;
  map.setCenter(one._lngLat);
  await new Promise(r => setTimeout(r, 300));
  const c = map.getCanvas();
  map.panBy([c.clientWidth / 2 - (sh.left + 30), c.clientHeight / 2 - 400],
            { duration: 0 });
  await new Promise(r => setTimeout(r, 800));
  const box = one.el.getBoundingClientRect();
  const lbl = one.el.querySelector('.lbl');
  return { name: lbl ? lbl.textContent.trim() : null,
           at: [Math.round(box.left), Math.round(box.top)],
           behindPanel: box.right > sh.left + 4 && box.bottom > sh.top + 4,
           markerVisible: getComputedStyle(one.el).visibility !== 'hidden',
           labelVisible: lbl ? getComputedStyle(lbl).visibility !== 'hidden' : null };
});

// pathToFileURL, not a template string: this checkout lives under
// "Glad Labs Products", import.meta.url percent-encodes the spaces, and
// the naive comparison silently never matched -- the script exited 0
// having run nothing, which is the same false pass this whole file is
// here to stop.
if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  const { browser, page } = await open(process.argv[2]);
  await page.evaluate(() => window.showConditions(41.4344, -71.3975, 'check'));
  await page.waitForTimeout(8000);
  const idle = await labelsUnderPanel(page);
  const driven = await driveMarkerBehindPanel(page);
  console.log(JSON.stringify({ idle, driven }, null, 1));
  await page.screenshot({ path: 'browser-check.png' });
  await browser.close();
  const bad = idle.stillShowing.length
    || (driven && driven.behindPanel && (driven.markerVisible || driven.labelVisible));
  process.exit(bad ? 1 : 0);
}
