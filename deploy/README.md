# Running tiderace as a service

The app is only useful if it is up when you are on the water, and a hand-started
server dies with the terminal that launched it. This is a systemd **user**
service, so it needs no root.

```bash
cp deploy/tiderace.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now tiderace
```

Two things that are easy to miss:

**Lingering.** A user service normally stops when you log out and does not come
back until you log in again — so after a reboot the app would be down until
someone sat at the machine. Fix it once:

```bash
loginctl enable-linger $USER
```

**The port is load-bearing.** `tailscale serve` proxies to `127.0.0.1:8765`.
Changing `--port` in the unit without changing the serve config takes the app
off the tailnet with no error anywhere — the proxy just has nothing to talk to.

```bash
tailscale serve status          # expect: / proxy http://127.0.0.1:8765
```

Logs: `journalctl --user -u tiderace -f`

## Map tiles offline

Tiles you have actually looked at are cached by the service worker (about
55 MB, capped, zoom 15 and below). Pan over your marks at the dock and they are
there when the signal is not.

There is deliberately **no "download the bay" button**. The OSM tile usage
policy forbids "any pre-emptive fetching of tiles other than those a user is
actively viewing", names offline use specifically, and blocks violators without
notice — which would take the basemap away entirely, on the water, rather than
just removing offline coverage.

Measured, for the water from the upper bay out to the wind farm
(40.95–41.80 N, 71.95–71.10 W):

| zoom | tiles | raster | good for |
|-----:|------:|-------:|----------|
| 11 | 48 | 0.8 MB | passage-level |
| 12 | 154 | 2.7 MB | navigating between spots |
| 13 | 546 | 9.6 MB | working a spot |
| 14 | 2,080 | 37 MB | detail |
| 15 | 8,216 | 144 MB | fine detail |
| 16 | 32,448 | 570 MB | maximum |

So z9–13 is only ~14 MB. Size was never the real obstacle; the policy is.

### If you want true pre-seeded coverage

Self-host, which the policy explicitly points to. The least-effort route is
[Protomaps](https://protomaps.com) — one `.pmtiles` file for a bounding box,
served as a static file from this same machine, no tile server to run:

```bash
# a Rhode Island extract, roughly 100-200 MB for full zoom
pmtiles extract https://build.protomaps.com/20260101.pmtiles ri.pmtiles \
  --bbox=-71.95,40.95,-71.10,41.80
```

Then point the map at it with `pmtiles://` and the protomaps-leaflet or
maplibre plugin, and drop the OSM raster source. That is a real change to the
map's style block, not a config switch, so it is worth doing deliberately — but
it is the only route to a basemap that works everywhere offshore, not just
where you happened to pan.
