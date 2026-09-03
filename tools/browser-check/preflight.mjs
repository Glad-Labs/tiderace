/* Look at it before you commit.
 *
 * Every check here exists because something shipped broken on 2 September
 * 2026 and was found by Matt, not by me. 503 tests were green through all of
 * it: they tested what I thought I had built. These test what the page does.
 *
 *   node tools/browser-check/preflight.mjs        # exits non-zero on any fail
 *
 * The failures it is built from, in the order they happened:
 *
 *   windmills gone          a new route shadowed /api/structure, so the layer
 *                           serving the five BIWF turbines 400'd
 *   legal limits invisible  open/closed and the size limit lived only in the
 *                           desktop sidebar, display:none on a phone
 *   desktop layout broken   an unscoped zoom rule stretched the sheet across
 *                           the window and squeezed the map to a strip
 *   contour numbers gone    a global replace put var(--halo) into MapLibre
 *                           paint, which is not CSS, so the layer stopped
 *                           drawing
 *   token defined as itself --panel-a:var(--panel-a) made the top bar
 *                           transparent in the dark theme
 *   crying wolf             the stale-build banner fired on every desktop load
 *
 * None of those is subtle on screen. All of them survived review.
 */
import { chromium, devices } from './playwright.mjs';

const PASS = [], FAIL = [];
const ok = (name, cond, detail = '') =>
  (cond ? PASS : FAIL).push(name + (detail ? ` — ${detail}` : ''));

const ready = p => p.waitForFunction(
  () => typeof MAP_READY !== 'undefined' && MAP_READY
     && typeof map !== 'undefined' && map.isStyleLoaded() && map.loaded(),
  null, { timeout: 90000 });

// Headless fires no map move, so markers keep their anchor offset and never
// get a position. One nudge is enough; without it every geometry check below
// measures 21 markers stacked in the corner and reports success.
const nudge = p => p.evaluate(() => { map.panBy([1, 0], { duration: 0 }); });

async function run(url) {
  const browser = await chromium.launch({ headless: true });

  // ---------- desktop ----------
  {
    const p = await browser.newPage({ viewport: { width: 1600, height: 900 } });
    const errs = [];
    p.on('pageerror', e => errs.push(String(e).slice(0, 140)));
    await p.goto(url, { waitUntil: 'domcontentloaded' });
    await ready(p);
    await nudge(p);
    await p.waitForTimeout(1500);

    ok('desktop: no uncaught page errors', errs.length === 0, errs[0] || '');

    // Fill the rail. Every geometry check below is about what the panel
    // covers, and an empty panel covers almost nothing.
    await p.evaluate(() => window.showConditions(41.4344, -71.3975, 'preflight'));
    await p.waitForTimeout(9000);

    const layout = await p.evaluate(() => {
      const sh = document.getElementById('sheet').getBoundingClientRect();
      const mp = document.getElementById('map').getBoundingClientRect();
      return { sheetW: Math.round(sh.width), sheetL: Math.round(sh.left),
               mapH: Math.round(mp.height), vh: innerHeight, vw: innerWidth };
    });
    ok('desktop: sheet is a right rail, not full width',
       layout.sheetW < 600 && layout.sheetL > layout.vw / 2,
       `${layout.sheetW}px at x=${layout.sheetL}`);
    ok('desktop: map fills the window',
       layout.mapH > layout.vh * 0.9, `${layout.mapH}px of ${layout.vh}`);

    // The turbines. A shadowed route took these off the map for a commit.
    const structure = await p.evaluate(async () => {
      const r = await fetch('/api/structure');
      const d = await r.json();
      return { status: r.status, features: (d.features || []).length,
               layer: !!map.getLayer('structure') };
    });
    ok('wind farm marks are served and drawn',
       structure.status === 200 && structure.features > 0 && structure.layer,
       `${structure.features} features, layer=${structure.layer}`);

    for (const theme of ['light', 'dark']) {
      await p.evaluate(t => { if (document.documentElement.dataset.theme !== t) applyTheme(t); }, theme);
      // Wait for the condition, not the clock. A theme swap is a setStyle and
      // everything is re-added on styledata, so a fixed sleep is a race: this
      // reported "no markers" intermittently and it was the harness losing,
      // not the app dropping them. isStyleLoaded stays false for a while after
      // the swap while sprites reload, so markers are the thing to wait on.
      await p.waitForFunction(
        () => typeof MARKERS !== 'undefined' && Object.keys(MARKERS).length > 0
              && typeof MAP_READY !== 'undefined' && MAP_READY,
        null, { timeout: 30000 }).catch(() => {});
      await p.waitForTimeout(1200);

      // MapLibre cannot parse a CSS var. Five of these shipped and took the
      // contour numbers off the chart.
      const style = await p.evaluate(() => {
        const bad = [];
        for (const l of map.getStyle().layers)
          for (const [k, v] of Object.entries(l.paint || {}))
            if (typeof v === 'string' && v.includes('var(')) bad.push(`${l.id}.${k}`);
        const c = map.getStyle().layers.find(l => l.id === 'c-contours-lbl');
        return { bad, contour: !!c,
                 contourVisible: c ? map.getLayoutProperty('c-contours-lbl', 'visibility') : null };
      });
      ok(`${theme}: no CSS var in a MapLibre paint value`,
         style.bad.length === 0, style.bad.join(', '));
      ok(`${theme}: contour labels present and visible`,
         style.contour && style.contourVisible !== 'none');

      // A token defined as itself resolves to nothing and paints transparent.
      const tokens = await p.evaluate(() => {
        const cs = getComputedStyle(document.documentElement);
        const out = {};
        for (const n of ['--ground', '--panel', '--ink', '--hair', '--panel-a',
                         '--halo', '--mk-ink', '--chart-ink', '--crit', '--good'])
          out[n] = cs.getPropertyValue(n).trim();
        return out;
      });
      const empty = Object.entries(tokens).filter(([, v]) => !v || v.includes('var('));
      ok(`${theme}: every theme token resolves to a colour`,
         empty.length === 0, empty.map(([k]) => k).join(', '));

      // Labels must not sit on the panel. Drive one behind it, because the
      // rail overlaps the map by a ~60px sliver and a default view finds
      // nothing to fail on.
      const driven = await p.evaluate(async () => {
        // Open it first. A collapsed rail sits at the bottom of the window,
        // so nothing can be behind it and the check reports "not behind"
        // rather than testing anything -- which is how it failed the first
        // time it ran, correctly and loudly.
        const sh = document.getElementById('sheet').getBoundingClientRect();
        // The rail must be tall enough to have something behind it, and its
        // height comes from its content -- an empty one is a couple of
        // hundred pixels at the bottom of the window, and a target picked at
        // a fixed y lands above it. Both of those made this report "not
        // behind" instead of testing anything.
        if (sh.height < 300) return { setupFailed: true, height: Math.round(sh.height) };
        const one = Object.values(MARKERS)[0];
        if (!one) return null;
        map.setCenter(one._lngLat);
        await new Promise(r => setTimeout(r, 300));
        const c = map.getCanvas();
        const targetY = sh.top + Math.min(240, sh.height * 0.4);
        map.panBy([c.clientWidth / 2 - (sh.left + 30), c.clientHeight / 2 - targetY],
                  { duration: 0 });
        await new Promise(r => setTimeout(r, 900));
        const b = one.el.getBoundingClientRect();
        const lbl = one.el.querySelector('.lbl');
        return { behind: b.right > sh.left + 4 && b.bottom > sh.top + 4,
                 marker: getComputedStyle(one.el).visibility !== 'hidden',
                 label: lbl ? getComputedStyle(lbl).visibility !== 'hidden' : false };
      });
      ok(`${theme}: a marker behind the panel is hidden`,
         driven && !driven.setupFailed && driven.behind
           && !driven.marker && !driven.label,
         driven ? JSON.stringify(driven) : 'no markers');

      // Z-ORDER, tested with the clamp deliberately switched off. This is a
      // stronger claim than "the clamp hides them": paint() gives every marker
      // a z-index from its score, 0-100, and with #map at `auto` those numbers
      // competed in the root context against the sheet at 40, the bar at 5 and
      // any popup at `auto`. A spot scoring 81 painted over all three, and the
      // clamp was papering over the one surface it knew about. Isolating #map
      // contains the range; this proves it still holds when nothing hides
      // anything.
      const stack = await p.evaluate(async () => {
        const saved = window.clampLabels;
        window.clampLabels = () => {};
        Object.values(MARKERS).forEach(m => {
          m.el.style.visibility = 'visible';
          const l = m.el.querySelector('.lbl'); if (l) l.style.visibility = 'visible';
        });
        const sh = document.getElementById('sheet').getBoundingClientRect();
        const one = Object.values(MARKERS)[0];
        if (!one || sh.height < 300) { window.clampLabels = saved; return null; }
        map.setCenter(one._lngLat);
        await new Promise(r => setTimeout(r, 400));
        const c = map.getCanvas();
        map.panBy([c.clientWidth / 2 - (sh.left + 40),
                   c.clientHeight / 2 - (sh.top + 200)], { duration: 0 });
        await new Promise(r => setTimeout(r, 900));
        const box = one.el.getBoundingClientRect();
        const hit = document.elementFromPoint(Math.round(box.left + box.width / 2),
                                              Math.round(box.top + box.height / 2));
        const bar = document.getElementById('bar').getBoundingClientRect();
        const hb = document.elementFromPoint(Math.round(bar.left + 40),
                                             Math.round(bar.top + 20));
        // A popup must beat a marker too -- that is what "labels over the
        // chart modal" was.
        new maplibregl.Popup({closeButton: false})
          .setLngLat(one._lngLat).setHTML('z-test').addTo(map);
        await new Promise(r => setTimeout(r, 500));
        const pop = document.querySelector('.maplibregl-popup');
        const popZ = pop ? +getComputedStyle(pop).zIndex || 0 : -1;
        const mkZ = +one.el.style.zIndex || 0;
        window.clampLabels = saved;
        return { sheetWins: !!(hit && hit.closest('#sheet')),
                 barWins: !!(hb && hb.closest('#bar')),
                 popupOverMarker: popZ > mkZ, popZ, mkZ };
      });
      ok(`${theme}: chrome outranks a marker even unclamped`,
         stack && stack.sheetWins && stack.barWins && stack.popupOverMarker,
         stack ? JSON.stringify(stack) : 'setup failed');

      // No two names drawn on top of each other, and none in the time bar.
      const overlap = await p.evaluate(() => {
        const box = e => { const r = e.getBoundingClientRect();
          return { l: r.left, t: r.top, r: r.right, b: r.bottom }; };
        const shown = [];
        for (const m of Object.values(MARKERS)) {
          const l = m.el.querySelector('.lbl');
          if (!l) continue;
          if (getComputedStyle(m.el).visibility === 'hidden') continue;
          if (getComputedStyle(l).visibility === 'hidden') continue;
          shown.push(box(l));
        }
        let pairs = 0;
        for (let i = 0; i < shown.length; i++)
          for (let j = i + 1; j < shown.length; j++) {
            const a = shown[i], b = shown[j];
            if (a.r > b.l && a.l < b.r && a.b > b.t && a.t < b.b) pairs++;
          }
        const tb = box(document.getElementById('timebar'));
        const under = shown.filter(s => s.r > tb.l && s.l < tb.r && s.b > tb.t && s.t < tb.b);
        return { shown: shown.length, pairs, under: under.length };
      });
      ok(`${theme}: no two spot labels overlap`, overlap.pairs === 0,
         `${overlap.pairs} pairs of ${overlap.shown} labels`);
      ok(`${theme}: no label drawn into the time bar`, overlap.under === 0);
    }
    await p.close();
  }

  // ---------- phone ----------
  for (const scheme of ['light', 'dark']) {
    const ctx = await browser.newContext({ ...devices['Pixel 7'], colorScheme: scheme });
    const p = await ctx.newPage();
    const errs = [];
    p.on('pageerror', e => errs.push(String(e).slice(0, 140)));
    await p.goto(url, { waitUntil: 'domcontentloaded' });
    await ready(p);
    await nudge(p);
    await p.evaluate(t => { if (document.documentElement.dataset.theme !== t) applyTheme(t); }, scheme);
    await p.waitForTimeout(6000);
    await p.evaluate(() => window.showConditions(41.4344, -71.3975, 'preflight'));
    await p.waitForTimeout(9000);

    ok(`phone/${scheme}: no uncaught page errors`, errs.length === 0, errs[0] || '');

    // Whether the season is open, on the screen actually in his hand. This
    // lived only in the desktop sidebar for several commits.
    const legal = await p.evaluate(() => {
      const el = document.getElementById('slegal');
      const head = el && el.querySelector('.lg');
      const sel = document.getElementById('species');
      const sh = document.getElementById('sheet').getBoundingClientRect();
      const bar = document.getElementById('bar').getBoundingClientRect();
      const s = sel.getBoundingClientRect();
      return { text: head ? head.textContent.trim().replace(/\s+/g, ' ') : null,
               visible: !!(el && el.offsetHeight > 0),
               shareOfSheet: el ? el.offsetHeight / sh.height : 0,
               barRows: Math.round(bar.height),
               pickerWhole: s.bottom <= sh.top + 2 && s.top >= -1,
               options: sel.options.length };
    });
    ok(`phone/${scheme}: legal status is on screen`,
       legal.visible && /OPEN|CLOSED|NOT MODELLED/.test(legal.text || ''),
       legal.text || 'missing');
    ok(`phone/${scheme}: it does not eat the sheet`,
       legal.shareOfSheet < 0.3, `${Math.round(legal.shareOfSheet * 100)}%`);
    ok(`phone/${scheme}: top bar is one row and unclipped`,
       legal.barRows < 90 && legal.pickerWhole, `${legal.barRows}px`);
    ok(`phone/${scheme}: every loggable fish is in the picker`,
       legal.options >= 35, `${legal.options} options`);

    // The build banner is the one thing whose job is to say when not to trust
    // the app. It fired on every desktop load for a while.
    const diag = await p.evaluate(() =>
      (document.getElementById('diag') || {}).textContent || '');
    ok(`phone/${scheme}: no false stale-build warning`,
       !/old cached build/.test(diag));

    // A scored species with no transcribed rule must SAY so. Eight of the
    // fourteen profiles are in that position since 2 Sep 2026, and the field
    // that used to carry it keyed off "is there a forecast" -- which stopped
    // meaning "is there a rule" the moment scored stopped implying regulated.
    const unruled = await p.evaluate(async () => {
      const sel = document.getElementById('species');
      sel.value = 'weakfish';
      sel.dispatchEvent(new Event('change'));
      await new Promise(r => setTimeout(r, 9000));
      const el = document.getElementById('slegal');
      return { text: (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 60),
               known: !!(GRID.regulations || {}).known };
    });
    ok(`phone/${scheme}: a scored fish with no rule says so`,
       !unruled.known && /NOT MODELLED/i.test(unruled.text),
       unruled.text || 'blank');

    // Contrast, composited over what is actually behind it.
    const worst = await p.evaluate(() => {
      const parse = c => { const n = (c.match(/[\d.]+/g) || []).map(Number);
        return { r: n[0] || 0, g: n[1] || 0, b: n[2] || 0, a: n.length > 3 ? n[3] : 1 }; };
      const over = (f, b) => ({ r: f.r * f.a + b.r * (1 - f.a),
                                g: f.g * f.a + b.g * (1 - f.a),
                                b: f.b * f.a + b.b * (1 - f.a), a: 1 });
      const lum = c => { const [r, g, b] = [c.r, c.g, c.b].map(v => {
          v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
        return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
      const bgOf = el => { const st = []; let n = el;
        while (n) { const c = parse(getComputedStyle(n).backgroundColor);
          if (c.a > 0) st.push(c); if (c.a === 1) break; n = n.parentElement; }
        let o = { r: 255, g: 255, b: 255, a: 1 };
        for (let i = st.length - 1; i >= 0; i--) o = over(st[i], o);
        return o; };
      let worst = { ratio: 99, sel: null };
      for (const sel of ['#slegal .lg b', '#tabs button.on', '.srow .k', '.srow .v',
                         '#sheetgrip .gcue', '#species']) {
        const el = document.querySelector(sel); if (!el) continue;
        const f = parse(getComputedStyle(el).color), b = bgOf(el);
        const L1 = lum(f), L2 = lum(b);
        const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
        if (ratio < worst.ratio) worst = { ratio: +ratio.toFixed(2), sel };
      }
      return worst;
    });
    ok(`phone/${scheme}: text meets AA (4.5:1)`, worst.ratio >= 4.5,
       `worst ${worst.sel} at ${worst.ratio}:1`);

    await ctx.close();
  }

  await browser.close();
}

await run(process.argv[2] || 'http://localhost:8765');

for (const p of PASS) console.log('  ok    ' + p);
for (const f of FAIL) console.log('  FAIL  ' + f);
console.log(`\n${PASS.length} passed, ${FAIL.length} failed`);
process.exit(FAIL.length ? 1 : 0);
