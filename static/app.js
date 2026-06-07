/* Mood Map — interactive canvas scatter of your library.
 *
 * World space: x,y in [-1, 1].  x = Sad(-1)↔Happy(+1), y = Calm(-1)↔Energetic(+1).
 * View = pan (px) + zoom (scale).  We redraw the whole scene each frame; with a
 * few hundred points that's plenty fast and keeps the code simple.
 */
(() => {
  "use strict";

  const canvas = document.getElementById("map");
  const ctx = canvas.getContext("2d");
  const tooltip = document.getElementById("tooltip");
  const loader = document.getElementById("loader");
  const loaderText = document.getElementById("loader-text");

  let tracks = [];          // [{id,name,artist,x,y,...}]
  let method = "direct";
  let mode = "demo";

  // view transform
  let zoom = 1;
  let panX = 0;
  let panY = 0;

  // interaction state
  let dragging = false;
  let selecting = false;
  let dragStart = null;     // screen px
  let dragNow = null;       // screen px
  let selection = [];       // selected track objects
  let hoverTrack = null;

  let dpr = window.devicePixelRatio || 1;

  // ---------- geometry ----------
  function baseRadius() {
    return Math.min(canvas.clientWidth, canvas.clientHeight) * 0.42;
  }
  function worldToScreen(wx, wy) {
    const r = baseRadius() * zoom;
    return [
      canvas.clientWidth / 2 + panX + wx * r,
      canvas.clientHeight / 2 + panY - wy * r,
    ];
  }
  function screenToWorld(sx, sy) {
    const r = baseRadius() * zoom;
    return [
      (sx - canvas.clientWidth / 2 - panX) / r,
      -(sy - canvas.clientHeight / 2 - panY) / r,
    ];
  }

  // ---------- color ----------
  // Hue swings blue (sad) → gold (happy); brightness rises with energy.
  function moodColor(x, y, alpha) {
    const hue = 222 + ((x + 1) / 2) * (48 - 222); // 222 → 48
    const light = 40 + ((y + 1) / 2) * 28;         // 40% → 68%
    return `hsla(${hue.toFixed(0)}, 78%, ${light.toFixed(0)}%, ${alpha})`;
  }

  // ---------- drawing ----------
  function resize() {
    dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(canvas.clientWidth * dpr);
    canvas.height = Math.round(canvas.clientHeight * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    draw();
  }

  function drawGrid() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    const [ox, oy] = worldToScreen(0, 0);

    // faint full-bleed grid quadrant tint
    ctx.fillStyle = "rgba(255,209,102,0.025)";
    ctx.fillRect(ox, 0, w - ox, oy);                 // happy + energetic
    ctx.fillStyle = "rgba(91,141,239,0.03)";
    ctx.fillRect(0, oy, ox, h - oy);                 // sad + calm

    // axes
    ctx.strokeStyle = "rgba(154,160,197,0.35)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, oy); ctx.lineTo(w, oy);
    ctx.moveTo(ox, 0); ctx.lineTo(ox, h);
    ctx.stroke();

    // bounding box of the [-1,1] world (the data extent)
    const [bx0, by0] = worldToScreen(-1, 1);
    const [bx1, by1] = worldToScreen(1, -1);
    ctx.strokeStyle = "rgba(108,123,255,0.25)";
    ctx.setLineDash([5, 6]);
    ctx.strokeRect(bx0, by0, bx1 - bx0, by1 - by0);
    ctx.setLineDash([]);
  }

  function drawPoints() {
    const selSet = new Set(selection.map((t) => t.id));
    const r = Math.max(2.2, 3.4 * Math.sqrt(zoom));
    const dim = selection.length > 0;

    for (const t of tracks) {
      const [sx, sy] = worldToScreen(t.x, t.y);
      if (sx < -20 || sy < -20 || sx > canvas.clientWidth + 20 || sy > canvas.clientHeight + 20)
        continue;
      const sel = selSet.has(t.id);
      const alpha = dim && !sel ? 0.18 : 0.92;
      ctx.beginPath();
      ctx.arc(sx, sy, sel ? r + 1.6 : r, 0, Math.PI * 2);
      ctx.fillStyle = moodColor(t.x, t.y, alpha);
      ctx.fill();
      if (sel) {
        ctx.lineWidth = 1.4;
        ctx.strokeStyle = "rgba(255,255,255,0.85)";
        ctx.stroke();
      }
    }

    if (hoverTrack) {
      const [sx, sy] = worldToScreen(hoverTrack.x, hoverTrack.y);
      ctx.beginPath();
      ctx.arc(sx, sy, r + 3.5, 0, Math.PI * 2);
      ctx.lineWidth = 2;
      ctx.strokeStyle = "#fff";
      ctx.stroke();
    }
  }

  function drawSelectionRect() {
    if (!selecting || !dragStart || !dragNow) return;
    const x = Math.min(dragStart.x, dragNow.x);
    const y = Math.min(dragStart.y, dragNow.y);
    const w = Math.abs(dragNow.x - dragStart.x);
    const h = Math.abs(dragNow.y - dragStart.y);
    ctx.fillStyle = "rgba(108,123,255,0.12)";
    ctx.fillRect(x, y, w, h);
    ctx.strokeStyle = "rgba(108,123,255,0.9)";
    ctx.lineWidth = 1.5;
    ctx.strokeRect(x, y, w, h);
  }

  function draw() {
    ctx.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight);
    drawGrid();
    drawPoints();
    drawSelectionRect();
  }

  // ---------- hit testing ----------
  function nearest(sx, sy) {
    let best = null, bestD = 14 * 14;
    for (const t of tracks) {
      const [px, py] = worldToScreen(t.x, t.y);
      const d = (px - sx) ** 2 + (py - sy) ** 2;
      if (d < bestD) { bestD = d; best = t; }
    }
    return best;
  }

  // ---------- data ----------
  async function loadStatus() {
    const r = await fetch("/api/status");
    const s = await r.json();
    mode = s.mode;
    const badge = document.getElementById("mode-badge");
    badge.textContent = s.mode === "live" ? "live · your library" : "demo library";
    badge.classList.add(s.mode);
    const authLink = document.getElementById("auth-link");
    if (authLink && s.live) authLink.textContent = "Reconnect";
  }

  async function loadTracks() {
    showLoader(method === "tsne" || method === "umap"
      ? "Reducing dimensions… (this one thinks for a moment)"
      : "Mapping your moods…");
    try {
      const r = await fetch(`/api/tracks?method=${method}`);
      const data = await r.json();
      if (!r.ok) {
        showLoader(data.error || "Something went wrong.", true);
        return;
      }
      tracks = data.tracks;
      mode = data.mode;
      document.getElementById("track-count").textContent = tracks.length;
      clearSelection();
      draw();
    } catch (e) {
      showLoader("Network error talking to the server.", true);
      return;
    }
    hideLoader();
  }

  function showLoader(text, sticky) {
    loaderText.textContent = text;
    loader.hidden = false;
    if (!sticky) return;
    loader.style.cursor = "pointer";
    loader.onclick = () => { loader.hidden = true; loader.onclick = null; };
  }
  function hideLoader() { loader.hidden = true; }

  // ---------- selection panel ----------
  function regionLabel() {
    if (!selection.length) return "";
    let cx = 0, cy = 0;
    for (const t of selection) { cx += t.x; cy += t.y; }
    cx /= selection.length; cy /= selection.length;
    const mood = cx >= 0 ? "happy" : "sad";
    const en = cy >= 0 ? "energetic" : "calm";
    return `centered on the ${mood} · ${en} region`;
  }

  function renderSelection() {
    const card = document.getElementById("selection-card");
    const empty = document.getElementById("empty-sel");
    if (!selection.length) {
      card.hidden = true;
      empty.hidden = false;
      return;
    }
    card.hidden = false;
    empty.hidden = true;
    document.getElementById("sel-count").textContent = selection.length;
    document.getElementById("sel-region").textContent = regionLabel();
    document.getElementById("playlist-result").hidden = true;

    const nameInput = document.getElementById("playlist-name");
    if (!nameInput.value) {
      let cx = 0, cy = 0;
      for (const t of selection) { cx += t.x; cy += t.y; }
      cx /= selection.length; cy /= selection.length;
      const mood = cx >= 0 ? "Happy" : "Sad";
      const en = cy >= 0 ? "Energetic" : "Calm";
      nameInput.value = `${mood} ${en} Mix`;
    }

    const list = document.getElementById("sel-list");
    list.innerHTML = "";
    for (const t of selection.slice(0, 60)) {
      const li = document.createElement("li");
      li.innerHTML = `${escapeHtml(t.name)} <span class="a">— ${escapeHtml(t.artist || "")}</span>`;
      list.appendChild(li);
    }
    if (selection.length > 60) {
      const li = document.createElement("li");
      li.className = "a";
      li.textContent = `…and ${selection.length - 60} more`;
      list.appendChild(li);
    }
  }

  function clearSelection() {
    selection = [];
    document.getElementById("playlist-name").value = "";
    renderSelection();
    draw();
  }

  function commitSelection() {
    if (!dragStart || !dragNow) return;
    const [wx0, wy0] = screenToWorld(dragStart.x, dragStart.y);
    const [wx1, wy1] = screenToWorld(dragNow.x, dragNow.y);
    const xmin = Math.min(wx0, wx1), xmax = Math.max(wx0, wx1);
    const ymin = Math.min(wy0, wy1), ymax = Math.max(wy0, wy1);
    selection = tracks.filter(
      (t) => t.x >= xmin && t.x <= xmax && t.y >= ymin && t.y <= ymax
    );
    renderSelection();
    draw();
  }

  async function makePlaylist() {
    if (!selection.length) return;
    const name = document.getElementById("playlist-name").value.trim() || "Mood Map Mix";
    const btn = document.getElementById("make-playlist");
    btn.disabled = true; btn.textContent = "Working…";
    try {
      const r = await fetch("/api/playlist", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, ids: selection.map((t) => t.id) }),
      });
      const data = await r.json();
      const result = document.getElementById("playlist-result");
      result.hidden = false;
      if (!r.ok) {
        result.innerHTML = `⚠️ ${escapeHtml(data.error || "Could not create playlist.")}`;
      } else if (data.created && data.url) {
        result.innerHTML =
          `✅ Created <b>${escapeHtml(data.name)}</b> (${data.track_count} songs) — ` +
          `<a href="${data.url}" target="_blank" rel="noopener">open in Spotify ↗</a>`;
      } else {
        result.innerHTML =
          `✅ <b>${escapeHtml(data.name)}</b> ready with ${data.track_count} songs. ` +
          `<span class="muted">Connect Spotify to save it to your account.</span>`;
      }
    } catch (e) {
      const result = document.getElementById("playlist-result");
      result.hidden = false;
      result.textContent = "⚠️ Network error.";
    }
    btn.disabled = false; btn.textContent = "Generate playlist";
  }

  function escapeHtml(s) {
    return (s || "").replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  // ---------- events ----------
  canvas.addEventListener("mousedown", (e) => {
    const rect = canvas.getBoundingClientRect();
    const p = { x: e.clientX - rect.left, y: e.clientY - rect.top };
    dragStart = p; dragNow = p;
    if (e.shiftKey) { selecting = true; } else { dragging = true; }
  });

  window.addEventListener("mousemove", (e) => {
    const rect = canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left, sy = e.clientY - rect.top;

    if (dragging) {
      panX += sx - dragNow.x;
      panY += sy - dragNow.y;
      dragNow = { x: sx, y: sy };
      draw();
      return;
    }
    if (selecting) {
      dragNow = { x: sx, y: sy };
      draw();
      return;
    }

    // hover
    if (sx < 0 || sy < 0 || sx > canvas.clientWidth || sy > canvas.clientHeight) {
      hoverTrack = null; tooltip.hidden = true; draw(); return;
    }
    const t = nearest(sx, sy);
    if (t !== hoverTrack) { hoverTrack = t; draw(); }
    if (t) {
      const [px, py] = worldToScreen(t.x, t.y);
      tooltip.hidden = false;
      tooltip.style.left = px + "px";
      tooltip.style.top = py + "px";
      tooltip.innerHTML =
        `<div class="t-name">${escapeHtml(t.name)}</div>` +
        `<div class="t-artist">${escapeHtml(t.artist || "")}</div>` +
        `<div class="t-feat">valence ${fmt(t.valence)} · energy ${fmt(t.energy)}` +
        (t.tempo ? ` · ${Math.round(t.tempo)} BPM` : "") + `</div>`;
    } else {
      tooltip.hidden = true;
    }
  });

  window.addEventListener("mouseup", () => {
    if (selecting) commitSelection();
    dragging = false; selecting = false;
    dragStart = null; dragNow = null;
  });

  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const sx = e.clientX - rect.left, sy = e.clientY - rect.top;
    const [wx, wy] = screenToWorld(sx, sy);
    const factor = Math.exp(-e.deltaY * 0.0012);
    zoom = Math.min(40, Math.max(0.4, zoom * factor));
    // keep the cursor anchored to the same world point
    const r = baseRadius() * zoom;
    panX = sx - canvas.clientWidth / 2 - wx * r;
    panY = sy - canvas.clientHeight / 2 + wy * r;
    draw();
  }, { passive: false });

  function fmt(v) { return v == null ? "?" : Number(v).toFixed(2); }

  document.getElementById("method-seg").addEventListener("click", (e) => {
    const btn = e.target.closest("button");
    if (!btn) return;
    document.querySelectorAll("#method-seg button").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    method = btn.dataset.method;
    loadTracks();
  });

  document.getElementById("make-playlist").addEventListener("click", makePlaylist);
  document.getElementById("clear-sel").addEventListener("click", clearSelection);
  window.addEventListener("resize", resize);

  // ---------- boot ----------
  (async () => {
    resize();
    await loadStatus();
    await loadTracks();
  })();
})();
