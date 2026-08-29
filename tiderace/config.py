"""Local settings. Gitignored, because whose licence you fish under is nobody
else's business."""

from __future__ import annotations

import json
import os

CONFIG_PATH = os.environ.get(
    "TIDERACE_CONFIG",
    os.path.join(os.path.dirname(__file__), "..", "data", "config.json"))

DEFAULTS = {
    # "recreational" | "commercial". Never inferred -- an app that silently
    # applied commercial limits to a recreational trip would be handing you a
    # citation, so this is explicit and always shown in output.
    "license_mode": "recreational",
    # Whose licence a commercial trip is fished under. Recorded rather than
    # assumed: RI commercial licences are issued to a named individual, so the
    # log should say which one a trip belongs to.
    "license_holder": None,
}


def load(path: str | None = None) -> dict:
    path = path or CONFIG_PATH
    cfg = dict(DEFAULTS)
    if os.path.exists(path):
        try:
            with open(path) as fh:
                cfg.update({k: v for k, v in json.load(fh).items() if k in DEFAULTS})
        except (OSError, json.JSONDecodeError):
            pass
    if cfg["license_mode"] not in ("recreational", "commercial"):
        cfg["license_mode"] = "recreational"
    return cfg


def save(cfg: dict, path: str | None = None) -> dict:
    path = path or CONFIG_PATH
    current = load(path)
    current.update({k: v for k, v in cfg.items() if k in DEFAULTS})
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(current, fh, indent=2)
    return current
