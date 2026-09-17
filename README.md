# Lord of the Clipboard

A pretty, fast clipboard manager for Windows — inspired by [ClipAngel](https://github.com/AlexanderPro/ClipAngel)'s
excellent behaviour, minus the dated looks. Python backend, web-tech UI (via
[pywebview](https://pywebview.flowlib.org/) + WebView2), fully portable.

## Highlights

- **History of everything you copy** — text, images, and file lists.
- **See where each clip came from.** Every clip records its source app, and for
  browsers it captures the **site** (e.g. `steamdb.info`, `web.telegram.org`) so
  you can filter days-old clips by where you got them.
- **First copied *and* last used.** Clips remember when they were first copied
  and the last time you pasted them. In the **By day** view the same clip shows
  up under both days — its origin day and the day you last used it. Using a clip
  bumps it to the top without erasing where it came from.
- **Paste as ▸** — right-click any clip and paste it as **Plain / Markdown /
  BBCode / rentry**. Rich formatting from the source (bold, links, lists…) is
  captured and converted on the fly; no need to know the original format.
- **Favorites & categories**, fuzzy search, and per-site / per-app / per-day
  filters in the sidebar.
- **Hotkeys** (rebindable in Settings): `Alt+V` opens the window, `Alt+B` jumps
  straight to favorites. `Enter`/double-click pastes into the app you came from,
  `1`–`9` quick-pick, `Esc` hides.
- **Portable.** All paths are relative; history lives in `./data`, so it runs
  from a USB stick or synced folder with no absolute paths baked in.

## Requirements

- Windows 10/11 (uses the built-in Edge **WebView2** runtime — already present on
  current Windows; otherwise install the free WebView2 runtime from Microsoft).
- Python 3.9+.

## Run it

Double-click **`run.bat`**. On first launch it creates a local `.venv`, installs
the dependencies from `requirements.txt`, then starts the app in the background.
The window stays hidden until you press the hotkey.

Manual/dev run:

```bat
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m src.app
```

## Layout

```
run.bat                  launcher (creates venv, installs deps, starts app)
config.default.json      default settings (copied to data/config.json on first run)
src/
  app.py                 entry point — wires config, storage, monitor, hotkeys, window
  paths.py               portable/relative paths
  config.py              load/save live config
  storage.py             SQLite history + favorites (two timestamps per clip)
  source_app.py          source app + browser-site (URL/domain) detection
  clipboard_monitor.py   background watcher (text/image/files + HTML)
  paster.py              clipboard read/write + paste-into-last-app + text transforms
  markup.py              HTML→Markdown/BBCode + Markdown↔BBCode conversion
  hotkeys.py             global, rebindable hotkeys
  api.py                 Python↔JS bridge
web/
  index.html style.css app.js    the UI
```

## Notes / limits

- Browser-site detection reads the address bar via Windows UI Automation; it's
  best-effort and falls back to the window title if a browser doesn't expose it.
- File clips currently restore as their text paths; full drag-drop (CF_HDROP)
  restore is a planned refinement.
