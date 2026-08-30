/* Tiderace service worker.
 *
 * The bay has no cell signal worth relying on, so the app has to survive
 * losing the server entirely. Two jobs:
 *
 *   1. Keep the shell installed, so opening it on the water shows an app
 *      rather than a dinosaur.
 *   2. Serve the last forecast that was downloaded at the dock.
 *
 * Map tiles are deliberately NOT cached. Covering the bay at usable zoom is
 * hundreds of megabytes, and the map is the one part of this you can lose and
 * still fish: the ranked list, the spot detail and the log form are the parts
 * that matter, and they are all data.
 */
// Bump SHELL whenever the page changes, or the old shell is served for one
// more load after every edit. That is correct offline-first behaviour and it
// is genuinely confusing during development -- a browser check against a
// stale cache proves nothing, which is how a debug probe survived one round
// of "verification" here.
const SHELL = 'tiderace-shell-v4';
const DATA  = 'tiderace-data-v1';

const SHELL_URLS = [
  '/', '/static/manifest.webmanifest',
  '/static/icon-192.png', '/static/icon-512.png',
  'https://unpkg.com/maplibre-gl@5.6.1/dist/maplibre-gl.js',
  'https://unpkg.com/maplibre-gl@5.6.1/dist/maplibre-gl.css'
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
    const keep = [SHELL, DATA];
    for (const k of await caches.keys()) if (!keep.includes(k)) await caches.delete(k);
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET') return;              // POSTs are queued client-side

  // Never cache tiles — see the note at the top.
  if (/tile\.openstreetmap|tiles\.openseamap/.test(url.hostname)) return;

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
