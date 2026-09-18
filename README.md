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
- **Favorites & categories**, fuzzy search, and per-site / per-app / per-day /
  per-**type** filters in the sidebar.
- **Auto-tagging by content type.** Clips are labelled url / email / color /
  phone / code / json / number / path so you can filter to just the URLs, etc.
- **Snippets with placeholders.** Save reusable text like `Hi {name}, …`; on
  paste it prompts to fill each blank. Right-click any clip → *Save as snippet*.
- **More transforms.** Beyond case/trim: strip URL tracking params, join lines,
  remove line numbers, pretty-print JSON, base64 encode/decode — from the
  right-click *Transform & paste ▸* menu.
- **System tray icon** — open, jump to favorites, pause capture, or quit.
- **Privacy.** Optional at-rest encryption of clip text, auto-expiry of
  secret-looking clips (API keys, card numbers), and never-store regex rules.
- **Import from ClipAngel** and **sync favorites/snippets** through a shared
  folder (Dropbox/OneDrive) — Settings has both.
- **Beep on capture** (optional).
- **Merge/stack paste** — Ctrl+click clips to stack them, then paste all at once
  joined by newline / space / comma (Enter pastes the stack).
- **F1–F9 pin bar** — your top favorites sit in a bar; F1–F9 paste them instantly.
- **In-place editor** — right-click ▸ *Edit text* to change any clip's body.
- **Auto-update** — checks GitHub Releases on startup and offers a one-click
  update that downloads the newest build and swaps it in (packaged builds only).
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
  detect.py              content-type tagging + secret detection
  crypto.py              optional at-rest encryption of clip text
  templates.py           snippet token resolution ({date}, {telegram}, …)
  updater.py             auto-update from GitHub Releases
  hotkeys.py             global, rebindable hotkeys
  tray.py                system tray icon
  importers.py           import history from ClipAngel
  sync.py                favorites/snippets sync via a shared folder
  api.py                 Python↔JS bridge
web/
  index.html style.css app.js    the UI
```

## Building a portable .exe (GitHub Action)

A manual workflow (**Actions ▸ Build Windows exe ▸ Run workflow**) builds a
one-dir PyInstaller bundle:

1. Pick the **branch/tag** to build from in the "Use workflow from" dropdown
   (that's the code that gets built), or set the optional `ref` input.
2. Type the **version** — it's baked into `src/_version.py` (shown in the window
   title / About) and into the `.exe` file properties.
3. Optionally tick **make_release** to publish a GitHub Release with the zip.

The result is uploaded as a build artifact: `LordOfTheClipboard-<version>-win64.zip`.
Unzip anywhere and run `LordOfTheClipboard.exe` — no Python needed, and its
`data/` folder is created next to the exe so it stays portable.

To build locally instead:

```bat
pip install -r requirements.txt pyinstaller
python packaging\make_version_file.py 0.1.0
pyinstaller --noconfirm --onedir --windowed --name LordOfTheClipboard ^
  --add-data "web;web" --add-data "config.default.json;." ^
  --collect-all pywebview --collect-submodules pynput ^
  --version-file packaging\file_version_info.txt run_app.py
```

## Snippet template tokens

Inside a snippet (New snippet ＋, or right-click ▸ Save as snippet):

- `{name}` — a fill-in blank you're prompted for
- `{date}` `{time}` `{datetime}` `{clipboard}` — auto-filled
- `{telegram}` / `{app:telegram}` / `{site:steamdb.info}` — pull a past clip
  from that app/site (a picker lists older ones); add `:N` to grab the Nth
  newest directly, e.g. `{telegram:2}` or `{site:steamdb.info:3}`

## Numeric quick-pick

Every visible clip is numbered `1..N`. Hold **Ctrl+Shift** and type a clip's
number — matches highlight, and it fires the instant the digits can only be one
clip. Hold **Ctrl+Shift+Alt** to paste it as plain text. Since numbering follows
whatever's on screen, filter the sidebar first (e.g. click *telegram*) to number
just those clips. Defaults to copy; switch to paste in Settings.

## Notes / limits

- Browser-site detection reads the address bar via Windows UI Automation; it's
  best-effort and falls back to the window title if a browser doesn't expose it.
- File clips currently restore as their text paths; full drag-drop (CF_HDROP)
  restore is a planned refinement.
