/* The desk page, in a real browser.
 *
 * `preflight.mjs` covers the map and nothing else, so the desk shipped
 * unlooked-at: on 17 September 2026 its in-force list was rewritten with the
 * whole suite green and not one of the 671 tests could see the page. This is
 * the same bargain as preflight -- slow, real, and about what the page does
 * rather than what the source says.
 *
 * The floor rule from preflight applies here too: every check reports how many
 * candidates it examined and refuses to pass on an empty set. A desk with no
 * rows would otherwise satisfy "no row overflows its card" perfectly.
 */
import { createRequire } from 'node:module';

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

let pass = 0, fail = 0;
const ok = (name, cond, detail = '') => {
  (cond ? pass++ : fail++);
  console.log(`  ${cond ? 'ok  ' : 'FAIL'}  ${name}${detail ? ' — ' + detail : ''}`);
};

/* Contrast of real painted text over what is actually behind it, rather than
 * over the token the stylesheet nominates. Composited, because a translucent
 * colour over a dark panel is not the colour in the source. */
const contrast = (page, sel) => page.evaluate((s) => {
  const px = c => {
    const m = c.match(/[\d.]+/g).map(Number);
    return { r: m[0], g: m[1], b: m[2], a: m.length > 3 ? m[3] : 1 };
  };
  const over = (fg, bg) => ({
    r: fg.r * fg.a + bg.r * (1 - fg.a),
    g: fg.g * fg.a + bg.g * (1 - fg.a),
    b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1 });
  const lum = c => {
    const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92
                                   : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  };
  const bgOf = el => {
    for (let n = el; n; n = n.parentElement) {
      const c = px(getComputedStyle(n).backgroundColor);
      if (c.a > 0) return c;
    }
    return { r: 255, g: 255, b: 255, a: 1 };
  };
  let worst = 99, who = '', seen = 0;
  for (const el of document.querySelectorAll(s)) {
    const t = (el.textContent || '').trim();
    if (!t || el.getBoundingClientRect().width === 0) continue;
    seen++;
    const fg = px(getComputedStyle(el).color);
    const c = over(fg, bgOf(el));
    const L1 = lum(c), L2 = lum(bgOf(el));
    const ratio = (Math.max(L1, L2) + 0.05) / (Math.min(L1, L2) + 0.05);
    if (ratio < worst) { worst = ratio; who = el.className || el.tagName; }
  }
  return { worst: Math.round(worst * 100) / 100, who, seen };
}, sel);

async function run(base) {
  const chromium = await loadChromium();
  const browser = await chromium.launch({ headless: true });

  // The desk is deliberately dark-only -- it defines no prefers-color-scheme
  // block and no data-theme, unlike the map page with its toggle. The light
  // pass is kept so that stays a decision: if someone adds half a light theme,
  // the check below fails rather than the page quietly going grey on grey.
  for (const [label, viewport, scheme] of [
    ['desktop/dark', { width: 1280, height: 900 }, 'dark'],
    ['phone/dark', { width: 375, height: 812 }, 'dark'],
    ['phone/light', { width: 375, height: 812 }, 'light'],
  ]) {
    const page = await browser.newPage({ viewport, colorScheme: scheme });
    const errs = [];
    page.on('pageerror', e => errs.push(String(e)));
    await page.goto(base + '/desk', { waitUntil: 'domcontentloaded' });
    await page.click('nav button[data-s="confirm"]');
    // Wait for the view, not for the placeholder. The first draft of this
    // accepted `#confirm .empty`, which is the "reading…" div the section
    // ships with -- so it returned instantly and every count below measured
    // an empty page. The heading only exists once the fetch has rendered.
    await page.waitForFunction(
      () => !!document.querySelector('#confirm h2'), null, { timeout: 20000 });

    ok(`${label}: no uncaught page errors`, errs.length === 0, errs[0] || '');

    const rows = await page.$$eval('#confirm .row', n => n.length);
    ok(`${label}: the in-force list drew rows`, rows > 0, `${rows} rows`);

    // The heading is the whole point of the change: it must state what is in
    // force, never a count of things waiting on him.
    const head = (await page.textContent('#confirm h2')).trim();
    ok(`${label}: the heading says in force, not waiting`,
       /in force$/.test(head) && !/waiting/i.test(head), JSON.stringify(head));

    // Every row carries exactly one action, and it is the retraction.
    const btns = await page.$$eval('#confirm .row', ns => {
      let min = 99, max = 0, labels = new Set();
      for (const n of ns) {
        const b = n.querySelectorAll('button');
        min = Math.min(min, b.length); max = Math.max(max, b.length);
        b.forEach(x => labels.add(x.textContent.trim()));
      }
      return { min, max, labels: [...labels], n: ns.length };
    });
    ok(`${label}: one action per row, and it is the retraction`,
       btns.n > 0 && btns.min === 1 && btns.max === 1
       && btns.labels.length === 1 && btns.labels[0] === 'not right',
       `examined ${btns.n}: ${JSON.stringify(btns.labels)}`);

    // The filter row must say how big each standing is, so choosing to look
    // at the season rows is a decision rather than a backlog.
    const picks = await page.$$eval('#confirm .picks button',
      ns => ns.map(n => n.textContent.trim()));
    ok(`${label}: each standing is offered with its size`,
       picks.length === 3 && picks.every(t => /\d+$/.test(t)),
       JSON.stringify(picks));

    // Nothing may spill out of its card on a 375px screen -- the desk is read
    // on the phone and a row that overflows is read nowhere.
    const spill = await page.evaluate(() => {
      const card = document.querySelector('#confirm .card');
      const box = card.getBoundingClientRect();
      let over = 0, seen = 0;
      for (const r of card.querySelectorAll('.row')) {
        seen++;
        const b = r.getBoundingClientRect();
        if (b.right > box.right + 1 || b.left < box.left - 1) over++;
      }
      return { over, seen, doc: document.documentElement.scrollWidth,
               win: window.innerWidth };
    });
    ok(`${label}: no row spills out of the card`,
       spill.seen > 0 && spill.over === 0, `examined ${spill.seen}`);
    ok(`${label}: the page does not scroll sideways`,
       spill.doc <= spill.win + 1, `${spill.doc} in ${spill.win}`);

    await page.screenshot({ path: `/tmp/desk-${label.replace('/', '-')}-live.png` });

    if (scheme === 'light') {
      const ground = await page.evaluate(() =>
        getComputedStyle(document.body).backgroundColor);
      ok(`${label}: the desk stays dark by design`,
         ground === 'rgb(11, 21, 24)', ground);
    }

    const c = await contrast(page, '#confirm .row, #confirm .tag, #confirm .dim, #confirm h2, #confirm .picks button');
    ok(`${label}: text meets AA (4.5:1)`, c.seen > 0 && c.worst >= 4.5,
       `worst ${c.who} at ${c.worst}:1, examined ${c.seen}`);

    // Switching standing must actually change the list, and the counts must
    // not move when it does: they describe everything, the list is one view.
    const before = await page.$$eval('#confirm .row', n => n.length);
    const counts = picks.join('|');
    await page.click('#confirm .picks button[data-state="inert"]');
    await page.waitForFunction(
      n => document.querySelectorAll('#confirm .row').length !== n,
      before, { timeout: 20000 });
    const after = await page.$$eval('#confirm .row', n => n.length);
    const picks2 = await page.$$eval('#confirm .picks button',
      ns => ns.map(n => n.textContent.trim()));
    ok(`${label}: choosing a standing changes the list`, after !== before,
       `${before} → ${after}`);
    ok(`${label}: the counts describe everything, not the view`,
       picks2.join('|') === counts, JSON.stringify(picks2));

    await page.screenshot({ path: `/tmp/desk-${label.replace('/', '-')}-inert.png` });
    await page.close();
  }

  await browser.close();
  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
}

await run(process.argv[2] || 'http://localhost:8765');
