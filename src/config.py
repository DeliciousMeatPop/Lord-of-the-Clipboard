"""Load / save the live config (data/config.json), seeded from config.default.json."""
from __future__ import annotations

import json
from typing import Any

from . import paths


def load() -> dict[str, Any]:
    paths.ensure_dirs()
    try:
        with open(paths.CONFIG_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        with open(paths.DEFAULT_CONFIG_PATH, "r", encoding="utf-8") as fh:
            return json.load(fh)


def save(cfg: dict[str, Any]) -> None:
    with open(paths.CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
