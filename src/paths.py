"""Portable path handling.

Everything lives relative to the project root so the app can run from a USB
stick, a synced folder, or wherever you drop it — no absolute paths baked in.
Data (the SQLite DB, captured images, the live config) goes in ./data.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    # PyInstaller one-dir build: bundled assets live under sys._MEIPASS, while
    # writable data sits next to the .exe so the app stays portable.
    BUNDLE = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    ROOT = Path(sys.executable).resolve().parent
    WEB_DIR = BUNDLE / "web"
    DEFAULT_CONFIG_PATH = BUNDLE / "config.default.json"
else:
    # Source layout: src/paths.py -> parents[1] is the project root.
    ROOT = Path(__file__).resolve().parents[1]
    WEB_DIR = ROOT / "web"
    DEFAULT_CONFIG_PATH = ROOT / "config.default.json"

DATA_DIR = ROOT / "data"
IMAGES_DIR = DATA_DIR / "images"
DB_PATH = DATA_DIR / "clipboard.db"
CONFIG_PATH = DATA_DIR / "config.json"


def ensure_dirs() -> None:
    """Create the data directories and seed config.json on first run."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists() and DEFAULT_CONFIG_PATH.exists():
        shutil.copyfile(DEFAULT_CONFIG_PATH, CONFIG_PATH)
