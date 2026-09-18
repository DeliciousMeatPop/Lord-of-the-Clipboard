/* Lord of the Clipboard — frontend logic (vanilla JS, talks to Python via pywebview) */
(() => {
  "use strict";

  const $  = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  let api = null;

  const state = {
    mode: "all",                 // 'all' | 'fav' | 'days' | 'snippets'
    filters: { query: "", domain: "", source_app: "", day: "", content_type: "" },
    clips: [],                   // flat list currently shown (with day-group flattening index)
    sel: 0,
    config: null,
    transforms: [],              // available paste transforms
  };

  const TRANSFORM_LABELS = {
    trim: "Trim whitespace", upper: "UPPERCASE", lower: "lowercase", title: "Title Case",
    sentence: "Sentence case", single_line: "Single line", join_lines: "Join lines",
    collapse_blanks: "Collapse blank lines", strip_tracking: "Strip URL tracking",
    remove_line_numbers: "Remove line numbers", json_pretty: "Pretty JSON",
    base64_encode: "Base64 encode", base64_decode: "Base64 decode", plain: "Plain",
  };

  /* ---------------------------------------------------------------- helpers */
  const esc = (s) => (s || "").replace(/[&<>"]/g, c => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function timeLabel(epoch) {
    if (!epoch) return "";
    const d = new Date(epoch * 1000), now = new Date();
    const sameDay = d.toDateString() === now.toDateString();
    const hhmm = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    return sameDay ? hhmm : d.toLocaleDateString([], { month: "short", day: "numeric" }) + " " + hhmm;
  }
  function dayLabel(iso) {
    const today = new Date().toISOString().slice(0, 10);
    const yest  = new Date(Date.now() - 864e5).toISOString().slice(0, 10);
    if (iso === today) return "Today";
    if (iso === yest)  return "Yesterday";
    return new Date(iso + "T00:00:00").toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" });
  }

  /* ---------------------------------------------------------------- render */
  async function refresh() {
    if (!api) return;
    const opts = { ...state.filters };
    if (state.mode === "fav") opts.favorites_only = true;
    if (state.mode === "snippets") opts.snippets_only = true;

    $("#list").innerHTML = "";
    if (state.mode === "days") {
      const groups = await api.list_by_day(opts);
      renderDays(groups);
    } else {
      const clips = await api.list_clips(opts);
      renderFlat(clips);
    }
    renderActiveFilters();
    if (state.sel >= state.clips.length) state.sel = Math.max(0, state.clips.length - 1);
    highlight();
  }

  function renderFlat(clips) {
    state.clips = clips;
    const list = $("#list");
    if (!clips.length) { list.innerHTML = `<div class="empty">Nothing here yet — copy something.</div>`; return; }
    clips.forEach((c, i) => list.appendChild(clipCard(c, i)));
  }

  function renderDays(groups) {
    state.clips = [];
    const list = $("#list");
    if (!groups.length) { list.innerHTML = `<div class="empty">Nothing here yet — copy something.</div>`; return; }
    let idx = 0;
    for (const g of groups) {
      const wrap = document.createElement("div");
      wrap.className = "day-group";
      wrap.innerHTML = `<div class="day-head">${esc(dayLabel(g.day))}</div>`;
      list.appendChild(wrap);
      for (const c of g.clips) {
        state.clips.push(c);
        wrap.appendChild(clipCard(c, idx++, c._reason));
      }
    }
  }

  function clipCard(c, i, reason) {
    const el = document.createElement("div");
    el.className = "clip";
    el.dataset.i = i;

    let bodyHtml;
    if (c.type === "image") {
      bodyHtml = `<img class="thumb" data-img="${c.id}" alt="image clip" />`;
    } else {
      bodyHtml = `<div class="text">${esc(c.preview || c.content || "")}</div>`;
    }

    const badges = [];
    if (c.is_snippet && c.name) badges.push(`<span class="badge app"><span class="dot"></span>✎ ${esc(c.name)}</span>`);
    if (c.source_domain) badges.push(`<span class="badge site"><span class="dot"></span>${esc(c.source_domain)}</span>`);
    else if (c.source_app) badges.push(`<span class="badge app"><span class="dot"></span>${esc(c.source_app)}</span>`);
    if (c.content_type && c.content_type !== "text" && !c.is_snippet)
      badges.push(`<span class="badge type">${esc(c.content_type)}</span>`);
    if (c.type !== "text") badges.push(`<span class="badge type">${c.type}</span>`);
    if (c.encrypted) badges.push(`<span class="badge type" title="stored encrypted">🔒</span>`);
    if (c.html) badges.push(`<span class="badge type" title="rich formatting captured">rich</span>`);
    if (reason === "used") badges.push(`<span class="badge reason-used">↑ used here</span>`);

    const times = [];
    times.push(`<span class="time">copied ${timeLabel(c.created_at)}</span>`);
    if (c.last_used_at) times.push(`<span class="time">used ${timeLabel(c.last_used_at)}</span>`);

    el.innerHTML = `
      <div class="idx">${i < 9 ? i + 1 : ""}</div>
      <div class="body">
        ${bodyHtml}
        <div class="meta">${badges.join("")}</div>
      </div>
      <div class="side">
        <button class="star ${c.favorite ? "on" : ""}" data-star="${c.id}" title="Favorite">★</button>
        ${times.join("")}
      </div>`;

    if (c.type === "image") {
      api.image_data_url(c.id).then(url => { const im = el.querySelector("img"); if (im && url) im.src = url; });
    }

    el.addEventListener("click", () => { state.sel = i; highlight(); });
    el.addEventListener("dblclick", () => paste(c.id));
    el.querySelector(".star").addEventListener("click", async (e) => {
      e.stopPropagation();
      await api.toggle_favorite(c.id);
      refresh();
    });
    el.addEventListener("contextmenu", (e) => { e.preventDefault(); state.sel = i; highlight(); openContextMenu(e, c); });
    return el;
  }

  function highlight() {
    $$(".clip").forEach(el => el.classList.toggle("sel", +el.dataset.i === state.sel));
    const cur = $(`.clip[data-i="${state.sel}"]`);
    if (cur) cur.scrollIntoView({ block: "nearest" });
  }

  function renderActiveFilters() {
    const f = state.filters, chips = [];
    if (f.day)          chips.push(`day: ${dayLabel(f.day)}`);
    if (f.content_type) chips.push(`type: ${f.content_type}`);
    if (f.domain)       chips.push(`site: ${f.domain}`);
    if (f.source_app)   chips.push(`app: ${f.source_app}`);
    if (f.query)        chips.push(`“${f.query}”`);
    $("#active-filters").innerHTML = chips.map(c => `<span class="chip">${esc(c)}</span>`).join("")
      + (chips.length ? ` <a href="#" id="clear-filters" style="color:var(--accent)">clear</a>` : "");
    const cl = $("#clear-filters");
    if (cl) cl.addEventListener("click", (e) => { e.preventDefault(); state.filters = { query: state.filters.query, domain: "", source_app: "", day: "", content_type: "" }; $("#search").value = state.filters.query; refresh(); loadSidebar(); });
  }

  /* ---------------------------------------------------------------- sidebar */
  async function loadSidebar() {
    if (!api) return;
    const [src, days, types] = await Promise.all([api.sources(), api.days(), api.content_types()]);
    fillSideList($("#day-filter"), days.map(d => ({ name: d, label: dayLabel(d) })), "day");
    fillSideList($("#type-filter"), types, "content_type");
    fillSideList($("#domain-filter"), src.domains, "domain");
    fillSideList($("#app-filter"), src.apps, "source_app");
  }
  function fillSideList(ul, items, key) {
    ul.innerHTML = "";
    items.slice(0, 40).forEach(it => {
      const li = document.createElement("li");
      const active = state.filters[key] === it.name;
      if (active) li.classList.add("active");
      li.innerHTML = `<span>${esc(it.label || it.name)}</span>` + (it.n != null ? `<span class="count">${it.n}</span>` : "");
      li.addEventListener("click", () => {
        state.filters[key] = active ? "" : it.name;   // toggle
        refresh(); loadSidebar();
      });
      ul.appendChild(li);
    });
    if (!items.length) ul.innerHTML = `<li style="color:var(--muted-2);cursor:default">—</li>`;
  }

  /* ---------------------------------------------------------------- actions */
  async function paste(id, fmt = "", transform = "") {
    if (!api) return;
    const clip = state.clips.find(x => x.id === id);
    // Snippet / any clip with {placeholders} → fill before pasting.
    const text = (clip && clip.content) || "";
    const names = [...new Set([...text.matchAll(/\{([a-zA-Z0-9_ -]+)\}/g)].map(m => m[1]))];
    if (clip && clip.is_snippet && names.length && !fmt && !transform) {
      const values = {};
      for (const n of names) {
        const v = prompt(`${n}:`, "");
        if (v === null) return;   // cancelled
        values[n] = v;
      }
      await api.paste_snippet(id, values);
      return;
    }
    await api.paste_clip(id, fmt, transform);
  }

  function selectedClip() { return state.clips[state.sel]; }

  /* ---------------------------------------------------------------- context menu */
  const FORMATS = [
    ["plain", "Plain text"],
    ["markdown", "Markdown  ( **bold** )"],
    ["bbcode", "BBCode  ( [b]bold[/b] )"],
    ["markdown", "rentry (Markdown)"],
  ];
  function openContextMenu(e, c) {
    const ctx = $("#ctx");
    const isText = c.type === "text";
    const fmtItems = isText ? FORMATS.map(([f, label]) =>
      `<div class="item" data-paste="${f}">${esc(label)}</div>`).join("") : "";
    const xfItems = isText ? state.transforms.map(tf =>
      `<div class="item" data-xf="${tf}">${esc(TRANSFORM_LABELS[tf] || tf)}</div>`).join("") : "";
    ctx.innerHTML = `
      ${isText ? `<div class="sub-label">Paste as</div>${fmtItems}
      <div class="item has-sub" data-sub="xf">Transform &amp; paste<span class="chev">▸</span>
        <div class="submenu hidden">${xfItems}</div></div>
      <div class="sep"></div>` : ""}
      <div class="item" data-copy="1">Copy to clipboard</div>
      ${c.is_snippet ? `<div class="item" data-edit="1">Edit snippet…</div>` : `<div class="item" data-mksnip="1">Save as snippet…</div>`}
      <div class="item" data-fav="1">${c.favorite ? "Unfavorite" : "Favorite ★"}</div>
      <div class="item" data-cat="1">Set category…</div>
      <div class="sep"></div>
      <div class="item danger" data-del="1">Delete</div>`;
    ctx.classList.remove("hidden");
    const { innerWidth: w, innerHeight: h } = window;
    ctx.style.left = Math.min(e.clientX, w - ctx.offsetWidth - 8) + "px";
    ctx.style.top  = Math.min(e.clientY, h - ctx.offsetHeight - 8) + "px";

    // Transform flyout
    const subHost = ctx.querySelector('[data-sub="xf"]');
    if (subHost) {
      const sub = subHost.querySelector(".submenu");
      subHost.addEventListener("mouseenter", () => {
        sub.classList.remove("hidden");
        const r = subHost.getBoundingClientRect();
        sub.style.left = Math.min(r.right, w - 200) + "px";
        sub.style.top = Math.min(r.top, h - sub.offsetHeight - 8) + "px";
      });
      subHost.addEventListener("mouseleave", () => sub.classList.add("hidden"));
    }

    ctx.onclick = async (ev) => {
      const t = ev.target.closest(".item"); if (!t) return;
      if (t.dataset.sub) return; // flyout host, ignore click
      if (t.dataset.xf != null) await paste(c.id, "", t.dataset.xf);
      else if (t.dataset.paste != null) await paste(c.id, t.dataset.paste);
      else if (t.dataset.copy) { await api.copy_clip(c.id); }
      else if (t.dataset.edit) { const nt = prompt("Snippet text:", c.content || ""); if (nt !== null) { await api.update_clip_text(c.id, nt); refresh(); } }
      else if (t.dataset.mksnip) { const nm = prompt("Snippet name:", (c.preview || "").slice(0, 30)); if (nm) { await api.create_snippet(nm, c.content || ""); } }
      else if (t.dataset.fav) { await api.toggle_favorite(c.id); refresh(); }
      else if (t.dataset.cat) { const cat = prompt("Category:", c.category || ""); if (cat !== null) { await api.set_category(c.id, cat); refresh(); } }
      else if (t.dataset.del) { await api.delete_clip(c.id); refresh(); loadSidebar(); }
      closeContextMenu();
    };
  }
  function closeContextMenu() { $("#ctx").classList.add("hidden"); }

  /* ---------------------------------------------------------------- settings */
  function openSettings() {
    const c = state.config || {};
    const hk = c.hotkeys || {}, mon = c.monitor || {}, ui = c.ui || {}, hist = c.history || {};
    const others = Object.entries(hk).filter(([k]) => k !== "show_window" && k !== "show_favorites");
    $("#settings-body").innerHTML = `
      <div class="field"><label>Show window hotkey</label>
        <input type="text" id="hk_show" value="${esc(hk.show_window || "")}" placeholder="&lt;alt&gt;+v"></div>
      <div class="field"><label>Show favorites hotkey</label>
        <input type="text" id="hk_fav" value="${esc(hk.show_favorites || "")}" placeholder="&lt;alt&gt;+b"></div>
      <div class="field"><label>Extra hotkeys (name = binding, one per line)</label>
        <input type="text" id="hk_extra" value="${esc(others.map(([k, v]) => k + '=' + v).join(', '))}"
          placeholder="clear_history=&lt;ctrl&gt;&lt;alt&gt;+x"></div>
      <p class="hint">Format: <span class="kbd">&lt;alt&gt;+v</span>, <span class="kbd">&lt;ctrl&gt;&lt;shift&gt;+c</span></p>
      <hr style="border-color:var(--line)">
      <div class="field"><label>Accent color</label>
        <div class="row"><input type="color" id="ui_accent" value="${esc(ui.accent || '#7c5cff')}">
        <select id="ui_theme"><option value="dark"${ui.theme !== 'light' ? ' selected' : ''}>Dark</option>
        <option value="light"${ui.theme === 'light' ? ' selected' : ''}>Light</option></select></div></div>
      <div class="field check"><input type="checkbox" id="mon_text" ${mon.capture_text !== false ? 'checked' : ''}><label>Capture text</label></div>
      <div class="field check"><input type="checkbox" id="mon_img" ${mon.capture_images !== false ? 'checked' : ''}><label>Capture images</label></div>
      <div class="field check"><input type="checkbox" id="mon_files" ${mon.capture_files !== false ? 'checked' : ''}><label>Capture files</label></div>
      <div class="field"><label>Max history items (favorites always kept)</label>
        <input type="number" id="hist_max" value="${hist.max_items || 5000}"></div>
      <div class="field"><label>Ignore apps (comma separated)</label>
        <input type="text" id="mon_ignore" value="${esc((mon.ignore_apps || []).join(', '))}"></div>
      <div class="field check"><input type="checkbox" id="ui_sound" ${ui.sound_on_capture ? 'checked' : ''}><label>Beep when something is captured</label></div>
      <hr style="border-color:var(--line)">
      <div class="side-title" style="margin:0 0 8px">Privacy</div>
      <div class="field check"><input type="checkbox" id="pv_enc" ${(c.privacy||{}).encrypt ? 'checked' : ''}><label>Encrypt clip text at rest (key kept in data/secret.key)</label></div>
      <div class="field"><label>Auto-delete secret-looking clips after (minutes, 0 = off)</label>
        <input type="number" id="pv_exp" value="${(c.privacy||{}).secret_expiry_minutes ?? 15}"></div>
      <div class="field"><label>Never store if it matches (regex, one per line)</label>
        <input type="text" id="pv_regex" value="${esc(((c.privacy||{}).never_store_regex||[]).join(' ||| '))}" placeholder="password\\s*[:=]  |||  BEGIN PRIVATE KEY"></div>
      <p class="hint">Separate multiple patterns with <span class="kbd">|||</span></p>
      <hr style="border-color:var(--line)">
      <div class="side-title" style="margin:0 0 8px">Sync &amp; import</div>
      <div class="field"><label>Sync folder (Dropbox/OneDrive — for favorites &amp; snippets)</label>
        <input type="text" id="sy_folder" value="${esc((c.sync||{}).folder || '')}" placeholder="C:\\Users\\you\\Dropbox\\lotc"></div>
      <div class="field check"><input type="checkbox" id="sy_start" ${(c.sync||{}).import_on_start ? 'checked' : ''}><label>Import synced favorites on startup</label></div>
      <div class="row" style="display:flex;gap:8px;margin-bottom:12px">
        <button class="btn" id="btn-sync-export">Export now</button>
        <button class="btn" id="btn-sync-import">Import now</button>
      </div>
      <div class="field"><label>Import history from ClipAngel</label>
        <div class="row"><input type="text" id="ca_path" placeholder="path to ClipAngel .db">
        <button class="btn" id="btn-ca-import">Import</button></div></div>
      <button class="btn" id="btn-clear-history">Clear history (keep favorites)</button>`;
    $("#settings").classList.remove("hidden");
    $("#btn-clear-history").onclick = async () => { await api.clear_history(true); refresh(); loadSidebar(); };
    $("#btn-sync-export").onclick = async () => { const r = await api.sync_export(); alert(r.ok ? `Exported ${r.count} items.` : `Error: ${r.error}`); };
    $("#btn-sync-import").onclick = async () => { const r = await api.sync_import(); alert(r.ok ? `Imported ${r.added} new items.` : `Error: ${r.error}`); refresh(); loadSidebar(); };
    (async () => { const p = await api.clipangel_default_path(); if (p && !$("#ca_path").value) $("#ca_path").value = p; })();
    $("#btn-ca-import").onclick = async () => { const r = await api.import_clipangel($("#ca_path").value.trim()); alert(r.ok ? `Imported ${r.imported} clips from ClipAngel.` : `Error: ${r.error}`); refresh(); loadSidebar(); };
  }
  async function saveSettings() {
    const c = JSON.parse(JSON.stringify(state.config || {}));
    c.hotkeys = c.hotkeys || {};
    c.hotkeys.show_window = $("#hk_show").value.trim();
    c.hotkeys.show_favorites = $("#hk_fav").value.trim();
    // rebuild extra hotkeys
    for (const k of Object.keys(c.hotkeys)) if (k !== "show_window" && k !== "show_favorites") delete c.hotkeys[k];
    $("#hk_extra").value.split(",").forEach(pair => {
      const [name, bind] = pair.split("=").map(s => (s || "").trim());
      if (name && bind) c.hotkeys[name] = bind;
    });
    c.ui = c.ui || {}; c.ui.accent = $("#ui_accent").value; c.ui.theme = $("#ui_theme").value;
    c.ui.sound_on_capture = $("#ui_sound").checked;
    c.monitor = c.monitor || {};
    c.monitor.capture_text = $("#mon_text").checked;
    c.monitor.capture_images = $("#mon_img").checked;
    c.monitor.capture_files = $("#mon_files").checked;
    c.monitor.ignore_apps = $("#mon_ignore").value.split(",").map(s => s.trim()).filter(Boolean);
    c.history = c.history || {}; c.history.max_items = parseInt($("#hist_max").value, 10) || 5000;
    c.privacy = c.privacy || {};
    c.privacy.encrypt = $("#pv_enc").checked;
    c.privacy.secret_expiry_minutes = parseInt($("#pv_exp").value, 10) || 0;
    c.privacy.never_store_regex = $("#pv_regex").value.split("|||").map(s => s.trim()).filter(Boolean);
    c.sync = c.sync || {};
    c.sync.folder = $("#sy_folder").value.trim();
    c.sync.import_on_start = $("#sy_start").checked;
    state.config = await api.save_config(c);
    applyTheme();
    $("#settings").classList.add("hidden");
  }
  function applyTheme() {
    const ui = (state.config && state.config.ui) || {};
    document.documentElement.dataset.theme = ui.theme === "light" ? "light" : "dark";
    if (ui.accent) document.documentElement.style.setProperty("--accent", ui.accent);
  }

  /* ---------------------------------------------------------------- keyboard */
  document.addEventListener("keydown", (e) => {
    if (!$("#settings").classList.contains("hidden")) {
      if (e.key === "Escape") $("#settings").classList.add("hidden");
      return;
    }
    if (!$("#ctx").classList.contains("hidden")) { if (e.key === "Escape") closeContextMenu(); return; }

    if (e.key === "Escape") { api && api.hide(); return; }
    if (e.key === "ArrowDown") { e.preventDefault(); state.sel = Math.min(state.sel + 1, state.clips.length - 1); highlight(); return; }
    if (e.key === "ArrowUp")   { e.preventDefault(); state.sel = Math.max(state.sel - 1, 0); highlight(); return; }
    if (e.key === "Enter") { const c = selectedClip(); if (c) paste(c.id); return; }
    // digit quick-pick 1-9 (only when not typing an edit besides search)
    if (/^[1-9]$/.test(e.key) && document.activeElement === $("#search") && $("#search").value === "") {
      const c = state.clips[+e.key - 1]; if (c) { e.preventDefault(); paste(c.id); }
    }
  });

  /* ---------------------------------------------------------------- wiring */
  function wire() {
    let t;
    $("#search").addEventListener("input", (e) => {
      clearTimeout(t);
      t = setTimeout(() => { state.filters.query = e.target.value.trim(); refresh(); }, 120);
    });
    $$(".seg").forEach(b => b.addEventListener("click", () => {
      $$(".seg").forEach(x => x.classList.remove("active")); b.classList.add("active");
      state.mode = b.dataset.mode; state.sel = 0; refresh();
    }));
    $("#btn-close").addEventListener("click", () => api && api.hide());
    $("#btn-new-snippet").addEventListener("click", async () => {
      const name = prompt("Snippet name:"); if (!name) return;
      const content = prompt("Snippet text (use {placeholders} for fill-in blanks):", ""); if (content === null) return;
      await api.create_snippet(name, content);
      $$(".seg").forEach(x => x.classList.toggle("active", x.dataset.mode === "snippets"));
      state.mode = "snippets"; refresh();
    });
    $("#btn-settings").addEventListener("click", openSettings);
    $("#settings-close").addEventListener("click", () => $("#settings").classList.add("hidden"));
    $("#settings-cancel").addEventListener("click", () => $("#settings").classList.add("hidden"));
    $("#settings-save").addEventListener("click", saveSettings);
    document.addEventListener("click", (e) => { if (!e.target.closest("#ctx")) closeContextMenu(); });
    window.addEventListener("blur", closeContextMenu);
  }

  // Called from Python.
  window.__lotc = {
    onNewClip() { refresh(); loadSidebar(); },
    async onSummon(favorites) {
      state.mode = favorites ? "fav" : "all";
      $$(".seg").forEach(x => x.classList.toggle("active", x.dataset.mode === state.mode));
      state.sel = 0;
      const s = $("#search"); s.value = ""; state.filters.query = "";
      await refresh(); await loadSidebar();
      s.focus();
    },
  };

  async function boot() {
    api = window.pywebview.api;
    state.config = await api.get_config();
    try { state.transforms = await api.transforms(); } catch (e) { state.transforms = []; }
    applyTheme();
    wire();
    await refresh();
    await loadSidebar();
    $("#search").focus();
  }

  if (window.pywebview && window.pywebview.api) boot();
  else window.addEventListener("pywebviewready", boot);
})();
