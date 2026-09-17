"""Portable path handling.

Everything lives relative to the project root so the app can run from a USB
stick, a synced folder, or wherever you drop it — no absolute paths baked in.
Data (the SQLite DB, captured images, the live config) goes in ./data.
"""
from __future__ import annotations

import shutil
from pathlib import Path

# src/paths.py  ->  parents[1] is the project root
ROOT = Path(__file__).resolve().parents[1]
WEB_DIR = ROOT / "web"
DATA_DIR = ROOT / "data"
IMAGES_DIR = DATA_DIR / "images"
DB_PATH = DATA_DIR / "clipboard.db"
CONFIG_PATH = DATA_DIR / "config.json"
DEFAULT_CONFIG_PATH = ROOT / "config.default.json"


def ensure_dirs() -> None:
    """Create the data directories and seed config.json on first run."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists() and DEFAULT_CONFIG_PATH.exists():
        shutil.copyfile(DEFAULT_CONFIG_PATH, CONFIG_PATH)
