"""Auto-update from GitHub Releases.

Flow:
  check()   -> asks the GitHub API for the latest release, compares its version
               to the running one, and reports the win64 zip asset URL.
  stage(url)-> downloads the zip and extracts it into data/update/staged/.
  apply()   -> writes a small updater .bat that waits for this app to exit,
               copies the staged files over the install dir, and relaunches —
               then asks the app to quit. (Needed because Windows won't let us
               overwrite the running .exe in place.)

Only meaningful in a frozen (PyInstaller) build; in a source checkout apply()
refuses so we never clobber your working tree.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path
from typing import Optional

from ._version import __version__
from .paths import DATA_DIR, ROOT

_UA = {"User-Agent": "LordOfTheClipboard-updater"}
_STAGE = DATA_DIR / "update"


def _version_tuple(v: str) -> tuple:
    nums = re.findall(r"\d+", v or "")
    return tuple(int(n) for n in nums[:4]) or (0,)


def is_frozen() -> bool:
    return getattr(sys, "frozen", False)


def check(repo: str) -> dict:
    """Return {ok, current, latest, available, url, notes, error}."""
    result = {"ok": False, "current": __version__, "latest": "", "available": False,
              "url": "", "notes": ""}
    if not repo:
        result["error"] = "No update repo configured."
        return result
    try:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repo}/releases/latest", headers=_UA)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
    except Exception as e:
        result["error"] = str(e)
        return result

    tag = (data.get("tag_name") or "").lstrip("v")
    result["latest"] = tag
    result["notes"] = data.get("body") or ""
    # Prefer a windows zip asset.
    for asset in data.get("assets", []):
        name = (asset.get("name") or "").lower()
        if name.endswith(".zip") and ("win" in name or "windows" in name):
            result["url"] = asset.get("browser_download_url", "")
            break
    if not result["url"] and data.get("assets"):
        result["url"] = data["assets"][0].get("browser_download_url", "")
    result["available"] = bool(tag) and _version_tuple(tag) > _version_tuple(__version__)
    result["ok"] = True
    return result


def stage(url: str) -> dict:
    """Download + extract the update into data/update/staged/."""
    if not url:
        return {"ok": False, "error": "No download URL."}
    try:
        _STAGE.mkdir(parents=True, exist_ok=True)
        zip_path = _STAGE / "update.zip"
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=120) as resp, open(zip_path, "wb") as fh:
            fh.write(resp.read())
        staged = _STAGE / "staged"
        if staged.exists():
            import shutil
            shutil.rmtree(staged, ignore_errors=True)
        staged.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(staged)
        # If the zip wrapped everything in a single top folder, unwrap it.
        entries = list(staged.iterdir())
        if len(entries) == 1 and entries[0].is_dir():
            return {"ok": True, "staged": str(entries[0])}
        return {"ok": True, "staged": str(staged)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def apply(staged_dir: str) -> dict:
    """Swap in the staged build and relaunch. Only in frozen installs."""
    if not is_frozen():
        return {"ok": False, "error": "Updates only apply to packaged (.exe) builds."}
    try:
        install_dir = str(ROOT)
        exe = sys.executable
        pid = os.getpid()
        bat = _STAGE / "apply_update.bat"
        script = f"""@echo off
setlocal
:wait
tasklist /FI "PID eq {pid}" 2>nul | find "{pid}" >nul
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait
)
robocopy "{staged_dir}" "{install_dir}" /E /IS /IT /NFL /NDL /NJH /NJS /NP >nul
rmdir /S /Q "{_STAGE / 'staged'}" 2>nul
del "{_STAGE / 'update.zip'}" 2>nul
start "" "{exe}"
del "%~f0"
"""
        bat.write_text(script, encoding="utf-8")
        # Detached so it survives our exit.
        subprocess.Popen(
            ["cmd", "/c", str(bat)],
            creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            close_fds=True,
        )
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
