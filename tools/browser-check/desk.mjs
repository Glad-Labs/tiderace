/* The desk page, in a real browser. All seven tabs.
 *
 * `preflight.mjs` covers the map and nothing else, so the desk shipped
 * unlooked-at: on 17 September 2026 its in-force list was rewritten with the
 * whole suite green and not one of the 671 tests could see the page. This is
 * the same bargain as preflight -- slow, real, and about what the page does
 * rather than what the source says.
 *
 * It then covered the Confirm tab and nothing else, which is the same gap one
 * level down. Matt, 18 September 2026: "should probably check all of them."
 * So there is a table of tabs now, every one gets the checks that apply to
 * any tab, and the two that have been rewritten recently -- In force and
 * Fish -- carry checks of their own on top.
 *
 * The floor rule from preflight applies here too: every check reports how many
 * candidates it examined and refuses to pass on an empty set. A desk with no
 * rows would otherwise satisfy "no row overflows its card" perfectly.
 *
 * Readiness is `h2` plus, where a tab needs it, one more thing. Every one of
 * the seven views writes a heading when its fetch lands, and the
 * `<div class="empty">reading…</div>` each section ships with has none -- the
 * first draft of this file accepted `#confirm .empty`, which IS that
 * placeholder, so it returned instantly and every count measured an empty
 * page. But a heading is not always the last thing to arrive: Fish writes its
 * heading and picker, then awaits the first species card, so `h2` alone
 * measured it mid-render at "1 heading, 0 cards" and failed. That failure was
 * the check working; the fix is the fourth column in TABS.
 *
 * A `.empty` INSIDE a rendered view is a different thing and legitimate
 * ("Nothing logged yet"), which is why the checks below never treat one as a
 * failure, only a blank section as one.
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

/* Every class on the desk that carries text. Curated rather than `*` so that
 * `seen` counts elements somebody styled rather than every wrapper in the
 * tree -- but broad enough that adding a row class without adding it here
 * shows up as a drop in the examined count rather than as silence. */
const TEXT = ['h2', 'h3', '.row', '.row .k', '.row .v', '.dim', '.tag', '.rule',
  '.credit', '.tclaim', '.tval', '.tname', '.twt', '.tmark', '.alias',
  '.about p', '.empty', '.names', '.rv', '.md', '.chg', 'summary', 'button'];

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

/* Open a tab and wait for the view rather than the placeholder.
 *
 * `h2` is the signal for six of the seven, and is NOT enough for Fish: that
 * view writes its heading and its picker first and only then awaits the card
 * for the first species, so there is a real window where the heading exists
 * and the card does not. Measuring in that window reported "1 heading, 0
 * cards, 513 chars" and failed -- correctly, and on the check rather than on
 * the page. So a tab may name a second thing to wait for. */
async function openTab(page, id, ready) {
  await page.click(`nav button[data-s="${id}"]`);
  await page.waitForFunction(
    ([i, extra]) => !!document.querySelector(`#${i} h2`)
                    && (!extra || !!document.querySelector(extra)),
    [id, ready || ''], { timeout: 25000 });
}

/* What every tab owes, whatever it holds. */
async function tabBasics(page, id, name, label, errsBefore, errs) {
  ok(`${label}/${name}: no uncaught page error on this tab`,
     errs.length === errsBefore, errs[errs.length - 1] || '');

  const shape = await page.evaluate((i) => {
    const s = document.querySelector('#' + i);
    return { h2: s.querySelectorAll('h2').length,
             cards: s.querySelectorAll('.card').length,
             text: (s.textContent || '').trim().length,
             placeholder: /^reading…$/.test((s.textContent || '').trim()) };
  }, id);
  // Not "has rows": regs draws .rule and fish draws a picker, so a row count
  // would pass vacuously on two of the seven. A heading, a card and some text
  // is the floor every view actually shares.
  ok(`${label}/${name}: the tab drew a view, not the placeholder`,
     shape.h2 > 0 && shape.cards > 0 && shape.text > 40 && !shape.placeholder,
     `${shape.h2} headings · ${shape.cards} cards · ${shape.text} chars`);

  // Nothing may spill out of its card on a 375px screen -- the desk is read
  // on the phone and a row that overflows is read nowhere.
  const spill = await page.evaluate((i) => {
    let over = 0, seen = 0, worst = '';
    for (const card of document.querySelectorAll('#' + i + ' .card')) {
      const box = card.getBoundingClientRect();
      for (const r of card.children) {
        const b = r.getBoundingClientRect();
        if (b.width === 0) continue;
        seen++;
        if (b.right > box.right + 1 || b.left < box.left - 1) {
          over++; worst = r.className || r.tagName;
        }
      }
    }
    return { over, seen, worst, doc: document.documentElement.scrollWidth,
             win: window.innerWidth };
  }, id);
  ok(`${label}/${name}: nothing spills out of its card`,
     spill.seen > 0 && spill.over === 0,
     `examined ${spill.seen}${spill.worst ? ', worst ' + spill.worst : ''}`);
  ok(`${label}/${name}: the page does not scroll sideways`,
     spill.doc <= spill.win + 1, `${spill.doc} in ${spill.win}`);

  const c = await contrast(page, TEXT.map(t => `#${id} ${t}`).join(', '));
  ok(`${label}/${name}: text meets AA (4.5:1)`, c.seen > 0 && c.worst >= 4.5,
     `worst ${c.who} at ${c.worst}:1, examined ${c.seen}`);
}

/* ------------------------------------------------------------- In force */

async function confirmChecks(page, label, deep) {
  const rows = await page.$$eval('#confirm .row', n => n.length);
  ok(`${label}/In force: the in-force list drew rows`, rows > 0, `${rows} rows`);

  // The heading is the whole point of the change: it must state what is in
  // force, never a count of things waiting on him.
  const head = (await page.textContent('#confirm h2')).trim();
  ok(`${label}/In force: the heading says in force, not waiting`,
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
  ok(`${label}/In force: one action per row, and it is the retraction`,
     btns.n > 0 && btns.min === 1 && btns.max === 1
     && btns.labels.length === 1 && btns.labels[0] === 'not right',
     `examined ${btns.n}: ${JSON.stringify(btns.labels)}`);

  // The filter row must say how big each standing is, so choosing to look
  // at the season rows is a decision rather than a backlog.
  const picks = await page.$$eval('#confirm .picks button',
    ns => ns.map(n => n.textContent.trim()));
  ok(`${label}/In force: each standing is offered with its size`,
     picks.length === 3 && picks.every(t => /\d+$/.test(t)),
     JSON.stringify(picks));

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
  ok(`${label}/In force: choosing a standing changes the list`, after !== before,
     `${before} → ${after}`);
  ok(`${label}/In force: the counts describe everything, not the view`,
     picks2.join('|') === counts, JSON.stringify(picks2));
}

/* ----------------------------------------------------------------- Fish */

/* Open one species card and wait for it, not for a timer -- `open()` replaces
 * #fishcard wholesale, so the old card stays on screen until the fetch lands
 * and a sleep would measure whichever one happened to win.
 *
 * The wait is on a marker planted inside the card, not on the heading
 * changing. Heading-changing was the first version and it deadlocks the
 * moment a fish is reopened: the sweep below walks the whole picker, so the
 * one fish already open would wait 25 seconds for a heading that is already
 * correct and then fail. The marker is a child, so `innerHTML = ...` removes
 * it whether the new card differs or not. */
async function openFish(page, key) {
  await page.evaluate(() => {
    const c = document.querySelector('#fishcard');
    if (c) c.insertAdjacentHTML('afterbegin', '<i data-stale="1"></i>');
  });
  await page.click(`#fish .pick button[data-fish="${key}"]`);
  await page.waitForFunction(() => {
    const c = document.querySelector('#fishcard');
    return c && !c.querySelector('[data-stale]') && c.querySelector('h3');
  }, null, { timeout: 25000 });
  // And then for the photograph to finish, because `naturalWidth` is 0 until
  // it does. Without this the sweep measured 15 of 37 cards mid-load and
  // called them uncredited -- which was not merely a false failure but the
  // WRONG failure, reporting a licence problem where there was a slow image.
  // `complete` goes true on error as well as on success, so a broken image
  // still ends the wait and is then caught by naturalWidth.
  await page.waitForFunction(() => {
    const img = document.querySelector('#fish img.photo');
    return !img || img.complete;
  }, null, { timeout: 20000 });
}

async function fishChecks(page, label, deep) {
  // The picker must offer every loggable fish, checked against the API rather
  // than against a number typed in here -- a hardcoded 37 would go stale the
  // day somebody logs a thirty-eighth and would then be wrong in the
  // reassuring direction.
  const picker = await page.evaluate(async () => {
    const meta = await (await fetch('/api/species')).json();
    const btns = [...document.querySelectorAll('#fish .pick button')];
    const keys = new Set(btns.map(b => b.dataset.fish));
    return { api: meta.loggable.length, shown: btns.length,
             missing: meta.loggable.filter(s => !keys.has(s.key)).map(s => s.key) };
  });
  ok(`${label}/Fish: every loggable fish is in the picker`,
     picker.api > 0 && picker.shown === picker.api && !picker.missing.length,
     `${picker.shown} of ${picker.api}` +
     (picker.missing.length ? ' missing ' + picker.missing.join(',') : ''));

  await openFish(page, 'tautog');

  // A photograph without its credit is somebody's work taken without the
  // licence's one condition.
  //
  // Checked against the string the API actually produced, not against a
  // length. "Longer than ten characters" was the first version and it could
  // not fail for the reason it claimed: the same paragraph also carries the
  // binomial and " — matched by taxon name", so blanking the attribution
  // entirely still left it 40 characters long and green. The credit is also
  // the paragraph immediately after the image, which is the other thing that
  // version did not check -- the natural-history licence line shares the
  // class, so `.credit` matched even with no photograph on the page at all.
  const photo = await page.evaluate(async () => {
    const img = document.querySelector('#fish img.photo');
    const p = img ? img.nextElementSibling : null;
    const d = await (await fetch('/api/dossier?species=tautog')).json();
    const want = ((d.photo || {}).credit || '').trim();
    const got = p && p.classList.contains('credit') ? p.textContent.trim() : '';
    return { img: !!img, w: img ? img.naturalWidth : 0, want, got,
             matches: !!want && got.includes(want) };
  });
  ok(`${label}/Fish: the photograph loaded and carries the credit the API gave`,
     photo.img && photo.w > 0 && photo.matches,
     `${photo.w}px wide · ${JSON.stringify(photo.want.slice(0, 44))}` +
     (photo.matches ? '' : ` NOT IN ${JSON.stringify(photo.got.slice(0, 60))}`));

  // The natural history, with the two things that make it citable. A revision
  // id is permanent; without it the card is quoting an article that may since
  // say something else.
  const about = await page.evaluate(() => {
    const h = [...document.querySelectorAll('#fish h2')]
      .find(x => /what it is/i.test(x.textContent));
    if (!h) return { present: false };
    const card = h.nextElementSibling;
    const secs = [...card.querySelectorAll('details.sec')];
    return {
      present: true,
      leadParas: card.querySelector('.about')
        ? card.querySelector('.about').querySelectorAll('p').length : 0,
      sections: secs.length,
      emptySections: secs.filter(s => !s.querySelectorAll('p').length).length,
      text: card.textContent.length,
      licence: /CC BY-SA/.test(card.textContent),
      revision: !!card.querySelector('a[href*="oldid="]'),
      caveat: /not a rule and not a band/.test(card.textContent),
    };
  });
  ok(`${label}/Fish: the natural history rendered`,
     about.present && about.text > 200 &&
     (about.leadParas > 0 || about.sections > 0),
     `${about.leadParas} lead paragraphs · ${about.sections} sections · ` +
     `${about.text} chars`);
  ok(`${label}/Fish: it carries its licence, its revision and its caveat`,
     about.licence && about.revision && about.caveat,
     `licence ${about.licence} · revision ${about.revision} · ` +
     `caveat ${about.caveat}`);
  ok(`${label}/Fish: no section is an empty disclosure`,
     about.sections === 0 || about.emptySections === 0,
     `${about.emptySections} empty of ${about.sections}`);

  // Cited vs prior is the one distinction the whole page exists to make, and
  // it has to survive without a tap.
  const marks = await page.$$eval('#fish .tmark', ns => {
    const t = ns.map(n => n.textContent.trim());
    return { n: ns.length, cited: t.filter(x => x === 'cited').length,
             prior: t.filter(x => x === 'prior').length };
  });
  ok(`${label}/Fish: cited and prior are both shown without a tap`,
     marks.n > 0 && marks.cited > 0 && marks.prior > 0,
     `${marks.cited} cited · ${marks.prior} prior of ${marks.n}`);

  // And the cited half must name what it is cited TO, on the card, beside the
  // mark. "cited" with the document left behind in score.py is the same empty
  // badge as a blank legal strip: it claims the work was done and shows none
  // of it.
  //
  // Anchored to the disclosure the mark sits in, and compared against the
  // string the API produced. walkthrough.mjs carried a version of this check
  // that read `#fishcard .tclaim` -- the FIRST one on the card -- and looked
  // for a bracket in it. That was a band claim until the Fish tab grew its
  // encyclopedia section above the forecast, and has been reading Wikipedia's
  // "not a rule and not a band" caveat ever since: a red result for a stale
  // reason, which teaches people to ignore red results.
  const cites = await page.evaluate(async () => {
    const d = await (await fetch('/api/dossier?species=tautog')).json();
    const want = {};
    for (const t of ((d.forecast || {}).terms || []))
      if (t.cited) want[t.label] = t.claim;
    const got = {};
    for (const el of document.querySelectorAll('#fish details.term')) {
      const m = el.querySelector('.tmark');
      if (!m || m.textContent.trim() !== 'cited') continue;
      const c = el.querySelector('.tclaim');
      got[el.querySelector('.tname').textContent.trim()] =
        c ? c.textContent.trim() : '';
    }
    const labels = Object.keys(want);
    return { n: labels.length,
             missing: labels.filter(k => !want[k] || !(got[k] || '').includes(want[k])),
             // [EFH-TOG p.5], [BB-TOG] -- the short codes score.py's docstring
             // expands. Three of the seventy cited bands in the file cite in
             // prose instead (measured 18 September 2026), so this asks that
             // THIS card names a document, not that every band everywhere
             // does -- a check that demanded all seventy would be asserting
             // something the data does not claim.
             docs: labels.filter(k => /\[[^\]]+\]/.test(got[k] || '')) };
  });
  ok(`${label}/Fish: a cited band carries the document it is cited to`,
     cites.n > 0 && cites.missing.length === 0 && cites.docs.length > 0,
     `${cites.n} cited · ${cites.docs.length} naming a document` +
     (cites.missing.length ? ` · NOT ON THE CARD: ${cites.missing.join(', ')}` : ''));

  // The legal strip never goes silent. Same rule preflight enforces on the
  // map: "rules not modelled" out loud beats a blank, because a blank reads
  // as "no limit" and that is a fine under a commercial licence.
  const legal = await page.evaluate(async () => {
    const out = [];
    for (const key of ['tautog', 'weakfish', 'bonito']) {
      const d = await (await fetch('/api/dossier?species=' + key)).json();
      const r = d.rules || {};
      out.push({ key, any: !!(r.recreational || r.commercial), warn: !!r.warning });
    }
    return out;
  });
  ok(`${label}/Fish: every fish states its rules or states that it has none`,
     legal.length === 3 && legal.every(x => x.any || x.warn),
     legal.map(x => `${x.key}:${x.any ? 'rule' : x.warn ? 'says-not-modelled' : 'SILENT'}`)
       .join(' '));

  if (!deep) return;

  // Every single card, once, on one viewport. The sweep is what would have
  // caught nine fish with no photograph at all, and it is the only check here
  // that looks at more than the first fish in the list.
  const keys = await page.$$eval('#fish .pick button', ns => ns.map(n => n.dataset.fish));
  const bad = [];
  for (const key of keys) {
    await openFish(page, key);
    const r = await page.evaluate(() => {
      const img = document.querySelector('#fish img.photo');
      // The credit for the PHOTO is the paragraph right after it. Anything
      // looser matches the natural-history licence line, which carries the
      // same class and would vouch for an image it has nothing to do with.
      const p = img ? img.nextElementSibling : null;
      const cred = p && p.classList.contains('credit')
        ? p.textContent.trim() : '';
      const about = [...document.querySelectorAll('#fish h2')]
        .some(x => /what it is/i.test(x.textContent));
      return { img: !!img, w: img ? img.naturalWidth : 0,
               // somebody · where it came from · (the licence). All three, or
               // it is not an attribution.
               credited: /\S.* · (Wikimedia Commons|iNaturalist) \(.+\)/.test(cred),
               saidWhyNot: [...document.querySelectorAll('#fish .credit')]
                 .some(c => /^no photo —/.test(c.textContent.trim())), about };
    });
    // Four distinct faults, named apart. Collapsing "the image did not load"
    // into "the image has no credit" is the same class of mistake as this
    // project's five tuna that spent a week labelled "no confident match"
    // because a socket dropped: a true absence reported as the wrong absence.
    if (r.img && !r.w) bad.push(`${key}:did-not-load`);
    if (r.img && r.w && !r.credited) bad.push(`${key}:uncredited`);
    if (!r.img && !r.saidWhyNot) bad.push(`${key}:silent-blank`);
    if (!r.about) bad.push(`${key}:no-background`);
  }
  ok(`${label}/Fish: every card carries a credited photo and its background`,
     keys.length > 0 && bad.length === 0,
     `examined ${keys.length}${bad.length ? ': ' + bad.join(' ') : ''}`);
}

/* ---------------------------------------------------------------- tabs */

const TABS = [
  ['history', 'Log'],
  ['reports', 'Reports'],
  ['confirm', 'In force', confirmChecks],
  ['regs', 'Regs'],
  ['hms', 'HMS'],
  // The fourth column is an extra thing to wait for, where a heading arrives
  // before the content does. Only Fish needs one so far.
  ['fish', 'Fish', fishChecks, '#fishcard .card'],
  ['sources', 'Sources'],
];

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

    // The nav must offer every tab this file knows about. Without it, a
    // renamed or dropped tab would make every check below silently skip --
    // "all seven" passing on four is the failure this whole file exists to
    // stop one level up.
    const nav = await page.$$eval('nav button', ns => ns.map(n => n.dataset.s));
    const absent = TABS.map(t => t[0]).filter(id => !nav.includes(id));
    ok(`${label}: every tab this file checks is on the nav`,
       nav.length === TABS.length && absent.length === 0,
       `${nav.length} tabs${absent.length ? ', missing ' + absent.join(',') : ''}`);

    for (const [id, name, checks, ready] of TABS) {
      const before = errs.length;
      // One broken tab fails that tab, not the run. The first version let the
      // exception out: a tab whose checks threw killed the process before the
      // summary line, so a run that had found six real failures printed
      // nothing at all and exited looking like a crash rather than a result.
      // A harness that can vanish is a harness you cannot trust a green from.
      try {
        await openTab(page, id, ready);
        await tabBasics(page, id, name, label, before, errs);
        if (checks) await checks(page, label, label === 'desktop/dark');
        await page.screenshot({
          path: `/tmp/desk-${label.replace('/', '-')}-${id}.png` });
      } catch (e) {
        ok(`${label}/${name}: the checks for this tab ran to the end`, false,
           String(e).split('\n')[0].slice(0, 160));
      }
    }

    if (scheme === 'light') {
      const ground = await page.evaluate(() =>
        getComputedStyle(document.body).backgroundColor);
      ok(`${label}: the desk stays dark by design`,
         ground === 'rgb(11, 21, 24)', ground);
    }

    await page.close();
  }

  await browser.close();
  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
}

await run(process.argv[2] || 'http://localhost:8765');
