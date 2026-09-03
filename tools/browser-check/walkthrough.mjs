/* Drive the app the way a person does, and report what broke.
 *
 * preflight.mjs checks invariants -- things that must be true of any build.
 * This is the other half: open every screen, press every control, switch every
 * mode, and watch for a screen that renders nothing or a console that fills up.
 * Between them they cover what a careful look would.
 */
import { chromium, devices } from './playwright.mjs';

const R = [];
const step = (name, ok, detail = '') => R.push({ name, ok, detail });

const ready = p => p.waitForFunction(
  () => typeof MAP_READY !== 'undefined' && MAP_READY
     && typeof map !== 'undefined' && map.isStyleLoaded() && map.loaded(),
  null, { timeout: 90000 });

async function walk(url) {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ ...devices['Pixel 7'] });
  const page = await ctx.newPage();
  const errors = [], failedReqs = [];
  page.on('pageerror', e => errors.push(String(e).slice(0, 120)));
  page.on('console', m => { if (m.type() === 'error'
    && !/favicon|sw\.js|service worker|unknown error occurred/i.test(m.text()))
    errors.push('console: ' + m.text().slice(0, 110)); });
  page.on('requestfailed', r => {
    if (!/protomaps|openseamap|unpkg|tile/.test(r.url()))
      failedReqs.push(r.url().slice(0, 80));
  });
  page.on('response', r => {
    if (r.url().includes('/api/') && r.status() >= 400)
      failedReqs.push(`${r.status()} ${r.url().split('?')[0].slice(-40)}`);
  });

  await page.goto(url, { waitUntil: 'domcontentloaded' });
  await ready(page);
  await page.evaluate(() => map.panBy([1, 0], { duration: 0 }));
  step('map loads with markers', true,
       `${await page.evaluate(() => Object.keys(MARKERS).length)} markers`);

  // --- open a coordinate, then every tab in the sheet -------------------
  await page.evaluate(() => window.showConditions(41.4344, -71.3975, 'walkthrough'));
  await page.waitForTimeout(9000);
  for (const view of ['now', 'log', 'spots', 'trips']) {
    await page.click(`#tabs button[data-view=${view}]`);
    await page.waitForTimeout(view === 'trips' ? 4000 : 1600);
    const body = await page.evaluate(() =>
      (document.getElementById('sheetbody').textContent || '').trim());
    // A threshold alone is why this passed on "No forecast loaded yet." for
    // as long as that tab has existed: 23 characters cleared >20. The tab has
    // to show what it is for, not merely be non-empty.
    const wants = {now: /current|water|tide/i, log: /fish|trip|save/i,
                   spots: /kt|—|not scored/, trips: /trip|REC|ramp/i}[view];
    step(`sheet tab: ${view}`, body.length > 20 && wants.test(body)
         && !/No forecast loaded yet/i.test(body), `${body.length} chars`);
  }

  // --- the log form, which is the thing with wet hands ------------------
  await page.click('#tabs button[data-view=log]');
  await page.waitForTimeout(1600);
  const log = await page.evaluate(() => ({
    form: !!document.getElementById('slogform'),
    mic: !!document.getElementById('slogmic'),
    cam: !!document.getElementById('slogcam'),
    species: (document.getElementById('slogsp') || {}).options?.length || 0,
    count: !!document.querySelector('#slogform [name=count]'),
    save: !!document.getElementById('slogsave'),
  }));
  step('log form is complete', log.form && log.mic && log.cam && log.count
       && log.save && log.species >= 35, JSON.stringify(log));

  // --- species: scored, scored-but-unruled, and unscored ----------------
  for (const [sp, want] of [['striped_bass', 'scored+ruled'],
                            ['weakfish', 'scored, no rule'],
                            ['bonito', 'scored, curated spots'],
                            ['bluefin', 'not scored']]) {
    await page.selectOption('#species', sp).catch(() => {});
    await page.waitForTimeout(8000);
    const g = await page.evaluate(() => ({
      species: GRID && GRID.species, modelled: GRID && GRID.modelled,
      spots: GRID ? GRID.spots.length : 0,
      legal: (document.getElementById('slegal').textContent || '').trim().slice(0, 40),
      rank: (document.getElementById('rank') || {}).textContent?.trim().slice(0, 40) || '',
    }));
    step(`species: ${sp} (${want})`, g.species === sp && g.spots > 0
         && g.legal.length > 0, JSON.stringify(g));
  }

  // --- the time slider must move the panel, not just the map ------------
  await page.click('#tabs button[data-view=now]');
  await page.waitForTimeout(1500);
  const readRows = () => page.evaluate(() => {
    const out = {};
    document.querySelectorAll('#sheetbody .srow').forEach(r => {
      const v = r.querySelector('.v').cloneNode(true);
      const mark = !!v.querySelector('.nowonly');
      v.querySelectorAll('.nowonly').forEach(n => n.remove());
      out[r.querySelector('.k').textContent.trim()] =
        { v: v.textContent.trim().replace(/\s+/g, ' '), now: mark };
    });
    return out;
  });
  const t0 = await readRows();
  // A control read at the SAME slider position, so ambient drift can be told
  // from slider-caused change. Water level is "observed minus predicted at
  // now", and `now` advances between two fetches -- without this the check
  // failed intermittently and blamed the app for the clock.
  await page.evaluate(() => refreshSurveyAtTime && refreshSurveyAtTime());
  await page.waitForTimeout(4500);
  const ctrl = await readRows();
  const drifts = new Set(Object.keys(t0).filter(k => !ctrl[k] || t0[k].v !== ctrl[k].v));

  await page.evaluate(() => { const t = document.getElementById('time');
    t.value = String(Math.min(+t.max, 48)); t.dispatchEvent(new Event('input')); });
  await page.waitForTimeout(4500);
  const t1 = await readRows();
  const forecastMoved = ['current', 'wind', 'next tide']
    .filter(k => t0[k] && t1[k] && t0[k].v !== t1[k].v && !drifts.has(k));
  const obsBroke = Object.keys(t1).filter(k => t1[k].now)
    .filter(k => t0[k] && t0[k].v !== t1[k].v && !drifts.has(k));
  const obsHeld = obsBroke.length === 0;
  step('slider moves the forecast rows', forecastMoved.length >= 2,
       `moved: ${forecastMoved.join(', ') || 'none'}`);
  step('slider leaves observations alone, marked now', obsHeld
       && Object.values(t1).some(r => r.now),
       `${Object.values(t1).filter(r => r.now).length} marked` +
       (drifts.size ? `, ${drifts.size} drifting at rest` : '') +
       (obsBroke.length ? `, MOVED: ${obsBroke.join(', ')}` : ''));
  await page.evaluate(() => { const t = document.getElementById('time');
    t.value = '0'; t.dispatchEvent(new Event('input')); });
  await page.waitForTimeout(4000);

  // --- the potential surface and the scan -------------------------------
  await page.selectOption('#species', 'fluke');
  await page.waitForTimeout(8000);
  await page.evaluate(() => map.jumpTo({ center: [-71.4225, 41.435], zoom: 14 }));
  await page.waitForTimeout(1500);
  await page.click('#scanbtn');
  await page.waitForTimeout(30000);
  const scan = await page.evaluate(() => ({
    markers: SCAN_MARKERS.length,
    btn: document.getElementById('scanbtn').textContent.trim(),
    first: SCAN_MARKERS[0]?.getElement().title.split('\n')[0] || null,
  }));
  step('scan ranks coordinates', scan.markers > 0 || /zoom|nothing/i.test(scan.btn),
       JSON.stringify(scan));

  const heat = await page.evaluate(async () => {
    const cb = document.querySelector('#layersbtn');
    if (cb) cb.click();
    await new Promise(r => setTimeout(r, 400));
    const t = document.getElementById('heaton');
    if (!t) return { toggle: false };
    t.checked = true; await t.onchange();
    return { toggle: true };
  });
  await page.waitForTimeout(45000);
  step('potential surface draws', await page.evaluate(() =>
       !!map.getLayer('heat') && map.getLayoutProperty('heat', 'visibility') === 'visible'),
       JSON.stringify(heat));

  // --- theme round trip --------------------------------------------------
  const themes = [];
  for (const t of ['light', 'dark', 'light']) {
    await page.evaluate(x => applyTheme(x), t);
    await page.waitForTimeout(7000);
    themes.push(await page.evaluate(() => ({
      t: document.documentElement.dataset.theme,
      markers: Object.keys(MARKERS).length,
      charts: map.getStyle().layers.filter(l => l.id.startsWith('c-')).length,
      heat: !!map.getLayer('heat'),
    })));
  }
  step('theme round trip keeps every layer',
       themes.every(x => x.markers === themes[0].markers && x.charts > 0),
       JSON.stringify(themes.map(x => `${x.t}:${x.markers}m/${x.charts}c/heat=${x.heat}`)));

  await page.screenshot({ path: 'walkthrough-map.png' });

  // --- the desk, and all five of its tabs --------------------------------
  await page.goto(url.replace(/\/$/, '') + '/desk', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);
  for (const s of ['history', 'reports', 'review', 'hms', 'sources']) {
    await page.click(`nav button[data-s=${s}]`);
    await page.waitForTimeout(2200);
    const txt = await page.evaluate(id =>
      (document.getElementById(id).textContent || '').trim(), s);
    step(`desk tab: ${s}`, txt.length > 40 && !/could not load/i.test(txt),
         `${txt.length} chars`);
  }
  await page.screenshot({ path: 'walkthrough-desk.png' });

  step('no uncaught page errors', errors.length === 0, errors.slice(0, 3).join(' | '));
  step('no failed app requests', failedReqs.length === 0, failedReqs.slice(0, 3).join(' | '));

  await browser.close();
}

await walk(process.argv[2] || 'http://localhost:8765');
for (const r of R) console.log(`  ${r.ok ? 'ok  ' : 'FAIL'}  ${r.name}${r.detail ? ' — ' + r.detail : ''}`);
const bad = R.filter(r => !r.ok).length;
console.log(`\n${R.length - bad} passed, ${bad} failed`);
process.exit(bad ? 1 : 0);
