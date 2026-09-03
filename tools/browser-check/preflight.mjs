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

    // Every control has to be reachable without scrolling. The bar wrapped to
    // three rows and got sliced by the sheet; making it one scrolling row
    // fixed the slicing and hid nine controls off the right edge instead --
    // 957px of content in a 314px window, with only the brand visible. They
    // live in the chart menu now, and both halves are checked: nothing spills
    // out of the bar, and what was moved is actually in the menu.
    const controls = await p.evaluate(async () => {
      // Pin --ui. It is innerWidth / min(screen.width, screen.height), and
      // Playwright does not emulate `screen`, so the same Pixel 7 profile
      // reported 1.24 in one run and 2.29 in another -- the bar's CSS width is
      // divided by that, so the measurement swung by 140px for reasons that
      // have nothing to do with the layout. On a real phone the ratio is
      // honest; the Desktop-site case it exists for is measured separately
      // below at a real 980px viewport.
      document.documentElement.style.setProperty('--ui', '1');
      await new Promise(r => setTimeout(r, 200));
      const bar = document.getElementById('bar');
      const br = bar.getBoundingClientRect();
      const spill = [...bar.children].filter(c => {
        const r = c.getBoundingClientRect();
        return r.width > 0 && (r.right > br.right + 1 || r.left < br.left - 1);
      }).map(c => c.id || c.className);
      // Get the sheet out of the way first. It is z-index 40 and the menu is
      // 6 inside a bar at 5, so with the sheet up the hit test at the menu's
      // location correctly returns the SHEET -- which says nothing about
      // whether a marker beats the menu, the thing actually under test.
      if (typeof setSheet === 'function') setSheet('shut');
      await new Promise(r => setTimeout(r, 400));
      document.getElementById('layersbtn').click();
      await new Promise(r => setTimeout(r, 500));
      const stowed = ['marks-wrap', 'labels-wrap', 'themebtn', 'desklink', 'offlinebtn']
        .filter(id => document.getElementById(id)?.closest('#layerchrome'));
      // And the menu must not be clipped by the bar it hangs off: overflow on
      // #bar cut an 800px menu down to the bar's own 58px, painting it into
      // nothing and letting markers show through where it should have been.
      const menu = document.getElementById('layers').getBoundingClientRect();
      const one = Object.values(MARKERS)[0];
      let menuWins = null;
      if (one) {
        one.el.style.zIndex = '99';
        map.setCenter(one._lngLat);
        await new Promise(r => setTimeout(r, 400));
        const c = map.getCanvas();
        map.panBy([c.clientWidth / 2 - (menu.left + menu.width / 2),
                   c.clientHeight / 2 - (menu.top + 60)], { duration: 0 });
        await new Promise(r => setTimeout(r, 800));
        const bx = one.el.getBoundingClientRect();
        const hit = document.elementFromPoint(Math.round(bx.left + bx.width / 2),
                                              Math.round(bx.top + bx.height / 2));
        menuWins = !!(hit && hit.closest('#layers'));
      }
      document.getElementById('layersbtn').click();
      return { spill, stowed: stowed.length, menuWins,
               barW: Math.round(bar.scrollWidth),
               barH: Math.round(bar.getBoundingClientRect().height),
               kids: [...bar.children].map(c => c.id || c.className),
               menuOpen: document.getElementById('layers').classList.contains('open'),
               fits: bar.scrollWidth <= bar.clientWidth + 1 };
    });
    ok(`phone/${scheme}: no control spills out of the bar`,
       controls.spill.length === 0 && controls.fits,
       `${controls.barW}px in ${controls.barH}px tall, spilling: ` +
       `${controls.spill.join(', ') || 'none'}`);
    ok(`phone/${scheme}: stowed controls are in the chart menu`,
       controls.stowed === 5, `${controls.stowed} of 5`);
    ok(`phone/${scheme}: the chart menu outranks a marker`,
       controls.menuWins === true, String(controls.menuWins));

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

    // ---- the chart menu is reachable all the way to the bottom ----
    //
    // It came out 888px tall in an 839px viewport with overflow:visible, so
    // bathy, the depth legend and the whole Potential section could not be
    // reached at all. Bounding it was not enough: the first bound reserved
    // the peek sheet but forgot the menu's own 75px top offset, so the menu
    // ended 75px UNDER the sheet -- and the sheet wins, z-index 40 to the
    // bar's 5. The bound after that was a plain px value set from JS, which
    // the zoom on #bar multiplied: 394px asked for, 675px drawn.
    //
    // The check is elementFromPoint, not "is it inside the viewport". The
    // earlier version asked the latter, passed, and the legend was behind the
    // sheet the whole time. Being on screen is not the same as being visible.
    await p.evaluate(() => window.setSheet('full'));
    await p.waitForTimeout(400);
    await p.click('#layersbtn');
    await p.waitForTimeout(700);
    await p.evaluate(() => { const l = document.getElementById('layers');
                             l.scrollTop = l.scrollHeight; });
    await p.waitForTimeout(250);
    const menu = await p.evaluate(() => {
      const l = document.getElementById('layers');
      const lb = l.getBoundingClientRect();
      const sh = document.getElementById('sheet');
      const sb = sh.getBoundingClientRect();
      const covered = [];
      let examined = 0;
      for (const el of l.querySelectorAll('*')) {
        if (el.children.length) continue;               // leaves only
        const r = el.getBoundingClientRect();
        if (r.width < 2 || r.height < 2) continue;
        if (r.top < lb.top + 2 || r.bottom > lb.bottom - 2) continue;
        examined++;
        const hit = document.elementFromPoint(
          Math.round(r.left + Math.min(r.width / 2, 16)),
          Math.round(r.top + r.height / 2));
        if (!hit || !l.contains(hit))
          covered.push(((el.textContent || el.tagName).trim().slice(0, 20))
                       + '←' + (hit ? (hit.id || hit.className || hit.tagName) : 'nothing'));
      }
      // The last row of the last section, whatever it is called today.
      const rows = l.querySelectorAll('label');
      const last = rows[rows.length - 1];
      const lr = last ? last.getBoundingClientRect() : null;
      return { vh: innerHeight, bottom: Math.round(lb.bottom), top: Math.round(lb.top),
               sheetTop: Math.round(sb.top), sheetState: sh.className,
               scrolled: Math.round(l.scrollTop),
               scrollMax: Math.round(l.scrollHeight - l.clientHeight),
               lastReachable: !!(lr && lr.bottom <= lb.bottom + 1 && lr.top >= lb.top - 1),
               examined, covered };
    });
    ok(`phone/${scheme}: the chart menu fits the screen`,
       menu.bottom <= menu.vh + 1, `bottom ${menu.bottom} in ${menu.vh}`);
    ok(`phone/${scheme}: the chart menu clears the sheet`,
       menu.bottom <= menu.sheetTop + 1,
       `menu ends ${menu.bottom}, sheet starts ${menu.sheetTop} (${menu.sheetState})`);
    ok(`phone/${scheme}: opening the menu steps the sheet down`,
       /peek/.test(menu.sheetState), menu.sheetState);
    ok(`phone/${scheme}: the chart menu scrolls to its own end`,
       menu.scrollMax > 0 && menu.scrolled >= menu.scrollMax - 2,
       `${menu.scrolled} of ${menu.scrollMax}`);
    ok(`phone/${scheme}: the last chart row is reachable`, menu.lastReachable);
    // A check that found nothing has not passed: an empty menu covers nothing.
    ok(`phone/${scheme}: nothing in the chart menu is covered`,
       menu.examined >= 8 && menu.covered.length === 0,
       `examined ${menu.examined}` + (menu.covered.length ? `, covered ${menu.covered.join(', ')}` : ''));

    await ctx.close();
  }

  // ---------- the Desktop-site case, which is the one --ui exists for ----
  {
    const ctx = await browser.newContext({
      viewport: { width: 980, height: 1985 }, deviceScaleFactor: 2,
      isMobile: true, hasTouch: true,
      userAgent: devices['Pixel 7'].userAgent,
    });
    const p = await ctx.newPage();
    await p.goto(url, { waitUntil: 'domcontentloaded' });
    await ready(p);
    await p.waitForTimeout(2500);
    const r = await p.evaluate(() => {
      const bar = document.getElementById('bar');
      const ui = getComputedStyle(document.documentElement)
        .getPropertyValue('--ui').trim();
      return { ui, scrollW: bar.scrollWidth, clientW: bar.clientWidth,
               h: Math.round(bar.getBoundingClientRect().height),
               warns: /Desktop site/.test(
                 (document.getElementById('diag') || {}).textContent || '') };
    });
    // Chrome's "Desktop site" reports a 980px viewport on a touch screen and
    // the page compensates by scaling. The bar's content has to fit the
    // divided width, and the app has to say what it noticed.
    ok('desktop-site 980px: the bar still fits',
       r.scrollW <= r.clientW + 1, `${r.scrollW} in ${r.clientW}, ui=${r.ui}`);
    // The compensation itself cannot be exercised here. --ui is
    // innerWidth / min(screen.width, screen.height) and Playwright reports the
    // HOST's screen, so a 980px emulated viewport comes back with ui=1 and no
    // warning. Asserting the warning would be asserting something this
    // environment cannot produce -- exactly the kind of check that gets
    // disabled later. What is checked is the part that does hold: at the width
    // Chrome reports with Desktop site on, the bar's content still fits.
    await ctx.close();
  }

  await browser.close();
}

await run(process.argv[2] || 'http://localhost:8765');

for (const p of PASS) console.log('  ok    ' + p);
for (const f of FAIL) console.log('  FAIL  ' + f);
console.log(`\n${PASS.length} passed, ${FAIL.length} failed`);
process.exit(FAIL.length ? 1 : 0);
