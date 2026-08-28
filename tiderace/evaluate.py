"""Does the model actually beat doing nothing?

Every feature added so far is unfalsifiable until this question has an answer.
A score of 86 at Whale Rock is not a prediction unless something can be wrong.

The bar is not "better than random". The bar is **better than the free advice
every angler already gives you**, which is: fish moving water at dawn or dusk.
That baseline needs no app, no NOAA calls and no model. If tiderace cannot beat
it, tiderace is a decoration on a tide chart.

Two biases make naive evaluation flattering, and both are structural:

  * **Selection.** You only log trips you took, and you took them when
    conditions looked good. The model is scored on a sample it helped choose.
  * **Feedback.** Once the app recommends a spot, you fish there, log there,
    and the model learns that spot is productive because it sent you.

`decided_by` on each log entry is the hook for controlling this: entries where
the app chose the spot are tracked separately from ones where you did, so the
two can be compared instead of silently blended.
"""

from __future__ import annotations

import math
import random
from datetime import datetime

from . import log as catchlog
from . import score

MIN_TRIPS = 40


def baseline(feat: dict) -> float:
    """Moving water, low light. The advice you get for free at any tackle shop."""
    speed = feat.get("current_speed") or 0.0
    moving = max(0.0, min(1.0, speed / 1.2))
    light = {"golden": 1.0, "twilight": 0.85, "night": 0.7, "day": 0.25}.get(
        feat.get("light_phase", "day"), 0.5)
    return round(moving * 0.5 * 100 + light * 0.5 * 100, 1)


def _spearman(xs: list[float], ys: list[float]) -> float | None:
    """Rank correlation. Catch counts are lumpy and zero-inflated, so ranks
    behave far better here than Pearson on raw counts."""
    n = len(xs)
    if n < 3:
        return None

    def rank(v):
        order = sorted(range(n), key=lambda i: v[i])
        r = [0.0] * n
        i = 0
        while i < n:
            j = i
            while j + 1 < n and v[order[j + 1]] == v[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                r[order[k]] = avg
            i = j + 1
        return r

    rx, ry = rank(xs), rank(ys)
    mx, my = sum(rx) / n, sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    dx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    dy = math.sqrt(sum((b - my) ** 2 for b in ry))
    return round(num / (dx * dy), 3) if dx and dy else None


def evaluate(entries: list[dict] | None = None) -> dict:
    entries = entries if entries is not None else catchlog.load()
    usable = [e for e in entries
              if e.get("conditions") and e["conditions"].get("current_speed") is not None]

    out: dict = {
        "logged": len(entries),
        "usable": len(usable),
        "min_trips": MIN_TRIPS,
        "ready": len(usable) >= MIN_TRIPS,
    }
    if not usable:
        out["verdict"] = "No usable trips logged yet — nothing to evaluate."
        return out

    counts = [float(e.get("count") or 0) for e in usable]
    model, base, rand = [], [], []
    rng = random.Random(0)
    for e in usable:
        c = e["conditions"]
        sp = e["species"]
        if sp not in score.PROFILES:
            continue
        model.append(score.score(sp, c, exposed=bool(c.get("exposed")))["score"])
        base.append(baseline(c))
        rand.append(rng.random() * 100)

    out["blank_rate"] = round(sum(1 for c in counts if c == 0) / len(counts), 3)
    out["model_rho"] = _spearman(model, counts)
    out["baseline_rho"] = _spearman(base, counts)
    out["random_rho"] = _spearman(rand, counts)

    # How much of the log came from the app's own recommendation?
    decided = sum(1 for e in usable if e.get("decided_by") == "app")
    out["app_chosen"] = decided
    out["app_chosen_share"] = round(decided / len(usable), 3)

    if not out["ready"]:
        out["verdict"] = (f"{len(usable)} usable trips — need about {MIN_TRIPS} "
                          f"before any of these numbers mean anything.")
    elif out["model_rho"] is None or out["baseline_rho"] is None:
        out["verdict"] = "Not enough variation in outcomes to rank."
    elif out["model_rho"] > out["baseline_rho"] + 0.05:
        out["verdict"] = "Model beats the moving-water-at-dawn baseline."
    elif out["model_rho"] < out["baseline_rho"] - 0.05:
        out["verdict"] = ("Baseline beats the model. The extra features are "
                          "costing accuracy, not adding it.")
    else:
        out["verdict"] = ("Model is indistinguishable from the free baseline. "
                          "It is not yet earning its complexity.")

    if out["app_chosen_share"] > 0.6 and out["ready"]:
        out["warning"] = (f"{out['app_chosen_share']:.0%} of trips were chosen by the "
                          "app itself — this measures agreement, not accuracy.")
    return out


def report(res: dict) -> str:
    L = []
    L.append(f"  {res['logged']} logged · {res['usable']} usable")
    if not res["usable"]:
        L.append(f"\n  {res['verdict']}")
        L.append("\n  Log the blanks too — a model trained only on good days")
        L.append("  learns that every day is good.")
        return "\n".join(L)

    L.append(f"  blank rate: {res['blank_rate']:.0%}")
    L.append("")
    L.append("  rank correlation with catch (higher is better)")
    for k, label in (("model_rho", "tiderace"),
                     ("baseline_rho", "moving water + low light"),
                     ("random_rho", "random")):
        v = res.get(k)
        L.append(f"    {label:<28} {'n/a' if v is None else f'{v:+.3f}'}")
    L.append("")
    L.append(f"  {res['verdict']}")
    if res.get("warning"):
        L.append(f"  ! {res['warning']}")
    return "\n".join(L)
