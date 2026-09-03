# Scheduled scrapes

Two timers. RIDEM daily, because a size limit changing under a commercial
licence is the one thing here that costs money to miss. The report outlets
weekly, because On The Water and most of the others publish weekly and reading
them daily is six requests a day to get the same page back.

    cp systemd/*.service systemd/*.timer ~/.config/systemd/user/
    # WorkingDirectory is %h/glad-labs-products/tiderace; edit it if the checkout lives elsewhere
    systemctl --user daemon-reload
    systemctl --user enable --now tiderace-regs.timer tiderace-reports.timer
    loginctl enable-linger "$USER"   # so they run when you are not logged in

Both are `Persistent=true`, so a run missed because the machine was off happens
when it comes back rather than being skipped in silence, and both carry a
`RandomizedDelaySec` because these are somebody's public web servers and there
is no reason to look like a clock.

**Neither writes anything to the rules or the bait log.** Extracted changes go
to the review queue and wait for a human; `/desk` is where you read them.

Check freshness at `/desk` → Sources, or:

    curl -s localhost:8765/api/scrapes

A source that has never run is shown overdue rather than left blank. The first
scheduled run proved why: both units exited 0 while `hooked_ri` failed inside
the run, and a timer reporting success over a source producing nothing is the
failure mode this whole arrangement exists to make visible.
