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
