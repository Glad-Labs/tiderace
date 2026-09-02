/* Tiderace service worker.
 *
 * The bay has no cell signal worth relying on, so the app has to survive
 * losing the server entirely. Two jobs:
 *
 *   1. Keep the shell installed, so opening it on the water shows an app
 *      rather than a dinosaur.
 *   2. Serve the last forecast that was downloaded at the dock.
 *
 * Map tiles ARE cached now, but only ones you have actually looked at, and
 * that distinction is the whole design rather than a detail.
 *
 * The OSM tile usage policy forbids "any pre-emptive fetching of tiles other
 * than those a user is actively viewing", names offline use specifically, and
 * says violators are blocked without notice. A block would not merely remove
 * offline tiles -- it would take the basemap away entirely, on the water, with
 * no warning. So there is no "download the bay" button, and there should not
 * be one.
 *
 * Caching what you did view is ordinary browser behaviour. In practice that is
 * enough: pan over your marks at the dock and those tiles are there when the
 * signal is not.
 *
 * The old note here claimed the bay was "hundreds of megabytes". Measured, for
 * the water from the upper bay out to the wind farm, z9-13 is 769 tiles, about
 * 14 MB; only z16 reaches 570 MB. The claim was wrong, but the policy makes
 * the size question moot anyway.
 *
 * For genuinely pre-seeded coverage the answer is self-hosted tiles -- see
 * deploy/README.md.
 */
// Bump SHELL whenever the page changes, or the old shell is served for one
// more load after every edit. That is correct offline-first behaviour and it
// is genuinely confusing during development -- a browser check against a
// stale cache proves nothing, which is how a debug probe survived one round
// of "verification" here.
const SHELL = 'tiderace-shell-v45';
const TILES = 'tiderace-tiles-v1';

// About 55 MB of raster tiles: enough for the bay at working zoom plus wherever
// else you wandered, without letting a long session grow without limit on a
// phone that also holds charts and photos.
const TILE_MAX = 3000;
// Past this, one spot's coverage runs to hundreds of megabytes and buys detail
// the basemap does not actually have offshore.
const TILE_MAX_ZOOM = 15;
const DATA  = 'tiderace-data-v1';

const SHELL_URLS = [
  // The desk page too: its four readings are exactly the things you catch up
  // on at the dock or on the mooring, which is where the signal is worst.
  '/', '/desk', '/static/manifest.webmanifest',
  '/static/icon-192.png', '/static/icon-512.png',
  'https://unpkg.com/maplibre-gl@5.6.1/dist/maplibre-gl.js',
  'https://unpkg.com/maplibre-gl@5.6.1/dist/maplibre-gl.css',
  // The basemap is vector now: pmtiles reads the archive, basemaps builds the
  // layer list. Without these two cached the map cannot draw offline even
  // though the tile data is sitting on the disk right there.
  'https://unpkg.com/pmtiles@4.3.0/dist/pmtiles.js',
  'https://unpkg.com/@protomaps/basemaps@5.2.0/dist/basemaps.js'
];

self.addEventListener('install', e => {
  e.waitUntil((async () => {
    const c = await caches.open(SHELL);
    // Cross-origin assets can only be stored opaquely, and one failure must
    // not abort the whole install.
    await Promise.allSettled(SHELL_URLS.map(u =>
      fetch(u, u.startsWith('http') ? {mode: 'no-cors'} : undefined)
        .then(r => c.put(u, r))));
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', e => {
  e.waitUntil((async () => {
    const keep = [SHELL, DATA, TILES];
    for (const k of await caches.keys()) if (!keep.includes(k)) await caches.delete(k);
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return;              // POSTs are queued client-side

  // The basemap archive is ours, served from this origin, and read by range
  // requests. Range responses cannot usefully live in the Cache API -- a
  // cached 206 answers exactly one byte range -- so it is left to the HTTP
  // cache, which does understand ranges and is told to hold it for a week.
  if (url.pathname === '/basemap.pmtiles') return;

  // Tiles: keep the ones actually viewed, never fetch ahead. The note at the
  // top explains why that difference matters more than the size does.
  if (/tile\.openstreetmap|tiles\.openseamap/.test(url.hostname)) {
    e.respondWith(tile(e.request, url));
    return;
  }

  const isData = url.pathname.startsWith('/api/') || url.pathname.startsWith('/charts/');

  e.respondWith((async () => {
    if (isData) {
      // Network first: a fresh forecast beats a stale one whenever the server
      // is reachable. Falling back to cache is what makes the boat work.
      try {
        const r = await fetch(e.request);
        if (r.ok) (await caches.open(DATA)).put(e.request, r.clone());
        return r;
      } catch (_) {
        const hit = await caches.match(e.request);
        if (hit) {
          const h = new Headers(hit.headers);
          h.set('X-Tiderace-Offline', '1');
          return new Response(await hit.blob(), {status: 200, headers: h});
        }
        return new Response(JSON.stringify({error: 'offline, and nothing saved for this'}),
                            {status: 503, headers: {'Content-Type': 'application/json'}});
      }
    }
    // Shell: cache first, refresh in the background.
    const hit = await caches.match(e.request);
    if (hit) { e.waitUntil(fetch(e.request).then(r =>
      r.ok && caches.open(SHELL).then(c => c.put(e.request, r))).catch(()=>{})); return hit; }
    try { return await fetch(e.request); }
    catch (_) { return (await caches.match('/')) ||
                       new Response('offline', {status: 503}); }
  })());
});

// The page asks for a bundle to be pulled down before leaving the dock.
self.addEventListener('message', e => {
  // The page asks which build is actually serving it. Answered from the worker
  // itself, so a stale worker reports its own old version rather than the one
  // the server would like it to be.
  if (e.data?.type === 'version') {
    e.source?.postMessage({type: 'version', shell: SHELL});
    return;
  }
  if (e.data?.type !== 'prefetch') return;
  e.waitUntil((async () => {
    const c = await caches.open(DATA);
    const results = await Promise.allSettled(
      (e.data.urls || []).map(u => fetch(u).then(r => r.ok && c.put(u, r))));
    const ok = results.filter(r => r.status === 'fulfilled' && r.value !== false).length;
    for (const client of await self.clients.matchAll())
      client.postMessage({type: 'prefetched', ok, total: (e.data.urls || []).length});
  })());
});

/* ---- tiles ------------------------------------------------------------
 * Cache-first: a tile that has not changed in months is not worth a round trip
 * on a marginal cell connection, and the point is that the map still draws
 * when there is no connection at all.
 *
 * Nothing here ever requests a tile the map did not ask for. The map asks for
 * what is on screen; we keep a copy. That is exactly the line the usage policy
 * draws, and it is worth not blurring -- pre-seeding risks the basemap being
 * cut off entirely, which costs far more than offline tiles gain.
 */
function tileZoom(pathname) {
  const m = pathname.match(/\/(\d{1,2})\/\d+\/\d+/);   // .../{z}/{x}/{y}.png
  return m ? +m[1] : null;
}

async function tile(request, url) {
  const c = await caches.open(TILES);
  const hit = await c.match(request);
  if (hit) {
    // Refresh behind the draw so a stale tile is eventually replaced, but
    // never block on it.
    if (navigator.onLine) {
      fetch(request).then(r => r.ok && c.put(request, r.clone())).catch(() => {});
    }
    return hit;
  }
  try {
    const r = await fetch(request);
    const z = tileZoom(url.pathname);
    // Opaque cross-origin responses have status 0 and still cache usefully.
    if ((r.ok || r.type === 'opaque') && z !== null && z <= TILE_MAX_ZOOM) {
      c.put(request, r.clone());
      trimTiles();
    }
    return r;
  } catch (_) {
    // Offline with nothing stored for this square. A transparent pixel beats a
    // broken-image icon: chart overlays, depth and your marks still draw on
    // top, and a blank basemap is honest about what is missing.
    return new Response(
      Uint8Array.from(atob(
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII='
      ), ch => ch.charCodeAt(0)),
      {status: 200, headers: {'Content-Type': 'image/png'}});
  }
}

// Oldest-first eviction. The Cache API preserves insertion order for keys(),
// so this is a real FIFO without keeping timestamps; good enough for tiles,
// where evicting the wrong one costs exactly one refetch.
let trimming = false;
async function trimTiles() {
  if (trimming) return;
  trimming = true;
  try {
    const c = await caches.open(TILES);
    const keys = await c.keys();
    if (keys.length <= TILE_MAX) return;
    for (const k of keys.slice(0, keys.length - TILE_MAX)) await c.delete(k);
  } finally {
    trimming = false;
  }
}
