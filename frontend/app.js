(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const drop = $("drop");
  const staging = $("staging");
  const stagingList = $("staging-list");
  const stagingMeta = $("staging-meta");
  const queueWrap = $("queue-wrap");
  const empty = $("empty");
  const queueEl = $("queue");
  const detail = $("detail");
  const toasts = $("toasts");
  const srStatus = $("sr-status");

  const IMAGE_RE = /\.(jpe?g|png|webp)$/i;
  const ZIP_RE = /\.zip$/i;

  const state = {
    staging: [],
    job: null,
    selectedId: null,
    checked: new Set(),
    filter: "all",
    query: "",
    poll: null,
    compare: 50,
    busy: false,
    scale: 4,
    minMb: 4,
    maxMb: null,
    customSize: false,
  };

  function currentSettings() {
    const minMb = state.customSize
      ? parseFloat($("min-mb").value) || state.minMb
      : state.minMb;
    let maxMb = null;
    if (state.customSize) {
      const raw = $("max-mb").value;
      if (raw !== "") maxMb = parseFloat(raw);
    }
    return {
      upscale_factor: state.scale,
      min_output_mb: minMb,
      max_output_mb: Number.isFinite(maxMb) ? maxMb : null,
    };
  }

  function syncSizeChips() {
    document.querySelectorAll("[data-mb]").forEach((btn) => {
      const val = btn.getAttribute("data-mb");
      const on = state.customSize ? val === "custom" : val === String(state.minMb);
      btn.classList.toggle("is-on", on);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
    });
    $("custom-size").hidden = !state.customSize;
  }

  document.querySelectorAll("[data-scale]").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.scale = parseInt(btn.getAttribute("data-scale"), 10);
      document.querySelectorAll("[data-scale]").forEach((b) => {
        const on = b === btn;
        b.classList.toggle("is-on", on);
        b.setAttribute("aria-pressed", on ? "true" : "false");
      });
    });
  });
  document.querySelectorAll("[data-mb]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const val = btn.getAttribute("data-mb");
      if (val === "custom") {
        state.customSize = true;
        $("min-mb").value = String(state.minMb);
      } else {
        state.customSize = false;
        state.minMb = parseFloat(val);
        state.maxMb = null;
        $("min-mb").value = val;
        $("max-mb").value = "";
      }
      syncSizeChips();
    });
  });
  $("min-mb").addEventListener("input", () => {
    const n = parseFloat($("min-mb").value);
    if (Number.isFinite(n)) state.minMb = n;
  });

  function toast(message, bad = false) {
    const el = document.createElement("div");
    el.className = "toast" + (bad ? " bad" : "");
    el.textContent = message;
    toasts.appendChild(el);
    setTimeout(() => el.remove(), 4200);
  }

  function announce(text) {
    srStatus.textContent = text;
  }

  function fmtBytes(n) {
    if (!n && n !== 0) return "—";
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    return (n / (1024 * 1024)).toFixed(2) + " MB";
  }

  function fmtDims(w, h) {
    if (!w || !h) return "—";
    return `${w} × ${h}`;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[c]));
  }

  async function inspectImage(file) {
    if (ZIP_RE.test(file.name)) {
      return { kind: "zip", name: file.name, size: file.size, width: null, height: null, format: "ZIP" };
    }
    if (!IMAGE_RE.test(file.name) && !file.type.startsWith("image/")) {
      return { kind: "invalid", name: file.name, size: file.size, error: "Unsupported file type" };
    }
    const url = URL.createObjectURL(file);
    try {
      const dims = await new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => resolve({ width: img.naturalWidth, height: img.naturalHeight });
        img.onerror = () => reject(new Error("unreadable"));
        img.src = url;
      });
      const ext = (file.name.split(".").pop() || "").toUpperCase();
      return { kind: "image", name: file.name, size: file.size, format: ext, ...dims };
    } catch {
      return { kind: "invalid", name: file.name, size: file.size, error: "Could not read this image" };
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  function addFiles(fileList) {
    const incoming = Array.from(fileList || []);
    incoming.forEach(async (file) => {
      const meta = await inspectImage(file);
      state.staging.push({ file, meta, id: crypto.randomUUID() });
      renderStaging();
    });
  }

  function renderStaging() {
    if (!state.staging.length) {
      staging.hidden = true;
      stagingList.innerHTML = "";
      return;
    }
    staging.hidden = false;
    stagingList.innerHTML = "";
    state.staging.forEach((item) => {
      const li = document.createElement("li");
      li.className = "file-row";
      const m = item.meta;
      const ok = m.kind !== "invalid";
      li.innerHTML = `
        <div>
          <div class="file-name">${escapeHtml(m.name)}</div>
          <div class="file-meta">
            ${fmtBytes(m.size)}
            ${m.width ? " · " + fmtDims(m.width, m.height) : ""}
            ${m.format ? " · " + escapeHtml(m.format) : ""}
            ${m.kind === "zip" ? " · image count after upload" : ""}
            · ${ok ? "Ready" : escapeHtml(m.error || "Invalid")}
          </div>
        </div>
        <button type="button" class="btn btn-ghost btn-small" data-remove="${item.id}">Remove</button>
      `;
      stagingList.appendChild(li);
    });
    const n = state.staging.length;
    stagingMeta.textContent = n === 1 ? "1 file" : `${n} files`;
  }

  drop.addEventListener("click", (e) => {
    if (e.target.closest("button")) return;
    $("file-images").click();
  });
  drop.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      $("file-images").click();
    }
  });
  ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => {
    e.preventDefault();
    drop.classList.add("is-drag");
  }));
  ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => {
    e.preventDefault();
    drop.classList.remove("is-drag");
  }));
  drop.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));
  $("file-images").addEventListener("change", (e) => {
    addFiles(e.target.files);
    e.target.value = "";
  });
  $("file-zip").addEventListener("change", (e) => {
    addFiles(e.target.files);
    e.target.value = "";
  });
  $("btn-choose").addEventListener("click", (e) => {
    e.stopPropagation();
    $("file-images").click();
  });
  $("btn-zip").addEventListener("click", (e) => {
    e.stopPropagation();
    $("file-zip").click();
  });
  document.addEventListener("paste", (e) => {
    const items = e.clipboardData && e.clipboardData.files;
    if (items && items.length) addFiles(items);
  });
  stagingList.addEventListener("click", (e) => {
    const id = e.target.getAttribute("data-remove");
    if (!id) return;
    state.staging = state.staging.filter((x) => x.id !== id);
    renderStaging();
  });
  $("btn-clear-staging").addEventListener("click", () => {
    state.staging = [];
    renderStaging();
  });

  async function api(url, opts = {}) {
    const res = await fetch(url, opts);
    const ct = res.headers.get("content-type") || "";
    if (ct.includes("application/json")) {
      const body = await res.json();
      if (!res.ok) {
        const msg = (body.error && body.error.message) || "Request failed.";
        throw new Error(msg);
      }
      return body;
    }
    if (!res.ok) throw new Error(await res.text() || "Request failed.");
    return res;
  }

  $("btn-upload").addEventListener("click", async () => {
    if (!state.staging.length || state.busy) return;
    const valid = state.staging.filter((s) => s.meta.kind !== "invalid");
    if (!valid.length) {
      toast("No valid images to upload.", true);
      return;
    }
    state.busy = true;
    $("btn-upload").disabled = true;
    announce("Uploading…");
    toast("Uploading…");
    try {
      const fd = new FormData();
      valid.forEach((s) => fd.append("files", s.file, s.file.name));
      const job = await api("/api/jobs", { method: "POST", body: fd });
      state.job = job;
      state.staging = [];
      renderStaging();
      state.checked = new Set(job.items.map((i) => i.id));
      state.selectedId = job.items[0] && job.items[0].id;
      renderJob();
      announce(`Uploaded ${job.total} image${job.total === 1 ? "" : "s"}.`);
      toast(`${job.total} image${job.total === 1 ? "" : "s"} ready to process.`);
    } catch (err) {
      toast(err.message || "Upload failed", true);
    } finally {
      state.busy = false;
      $("btn-upload").disabled = false;
    }
  });

  function filteredItems() {
    if (!state.job) return [];
    const q = state.query.trim().toLowerCase();
    return state.job.items.filter((it) => {
      if (state.filter === "processing" && !["processing", "pending"].includes(it.status)) return false;
      if (state.filter === "completed" && it.status !== "completed") return false;
      if (state.filter === "failed" && it.status !== "failed") return false;
      if (q && !it.filename.toLowerCase().includes(q)) return false;
      return true;
    });
  }

  function renderJob() {
    const job = state.job;
    if (!job) {
      queueWrap.hidden = true;
      empty.hidden = false;
      detail.hidden = true;
      document.querySelectorAll("#settings button, #settings input").forEach((el) => {
        el.disabled = false;
      });
      return;
    }
    empty.hidden = true;
    queueWrap.hidden = false;
    const c = job.counts || {};
    const done = c.completed || 0;
    $("summary-line").textContent = `${done} / ${job.total} completed`;
    const pct = job.percent || 0;
    $("progress-bar").style.width = pct + "%";
    $("progress").setAttribute("aria-valuenow", String(pct));
    $("counts").textContent =
      `Completed ${c.completed || 0} · Processing ${c.processing || 0} · Waiting ${c.pending || 0} · Failed ${c.failed || 0}`;
    if (job.eta_seconds && (c.pending || c.processing)) {
      const m = Math.max(1, Math.round(job.eta_seconds / 60));
      $("eta").textContent = `Estimated remaining: ~${m} minute${m === 1 ? "" : "s"}`;
    } else if (job.status === "completed") {
      const elapsed = job.elapsed_seconds || 0;
      const mm = Math.floor(elapsed / 60);
      const ss = elapsed % 60;
      $("eta").textContent = `Total processing time: ${mm}m ${String(ss).padStart(2, "0")}s`;
    } else {
      $("eta").textContent = job.status === "processing" ? "AI upscaling your image…" : "";
    }

    const processing = job.status === "processing" || job.status === "cancelling";
    document.querySelectorAll("#settings button, #settings input").forEach((el) => {
      el.disabled = processing;
    });
    $("btn-process").disabled = processing || !(c.pending);
    $("btn-cancel").disabled = !processing;
    $("btn-retry").disabled = !(c.failed);
    $("btn-download-all").disabled = !(c.completed);

    queueEl.innerHTML = "";
    const items = filteredItems();
    if (!items.length) {
      const li = document.createElement("li");
      li.className = "muted";
      li.textContent = "No images match this filter.";
      queueEl.appendChild(li);
    }
    items.forEach((it) => {
      const li = document.createElement("li");
      li.className = "queue-item" + (it.id === state.selectedId ? " is-on" : "");
      li.dataset.id = it.id;
      const orig = it.original || {};
      const statusLabel = {
        pending: "Waiting",
        processing: "Processing",
        completed: "Completed",
        failed: "Failed",
        cancelled: "Cancelled",
      }[it.status] || it.status;
      const extra = it.status === "processing" ? ` ${it.progress || 0}%` : "";
      li.innerHTML = `
        <label>
          <input class="file-check" type="checkbox" ${state.checked.has(it.id) ? "checked" : ""} data-check="${it.id}" aria-label="Select ${escapeHtml(it.filename)}" />
        </label>
        <button type="button" class="pick" data-pick="${it.id}" style="text-align:left;border:0;background:transparent;padding:0;cursor:pointer;">
          <div class="file-name">${escapeHtml(it.filename)}</div>
          <div class="file-meta">${fmtDims(orig.width, orig.height)} · ${fmtBytes(orig.size)} · ${escapeHtml(orig.format || "")}</div>
          <div class="status ${it.status}">${statusLabel}${extra}</div>
          ${it.error ? `<p class="error-msg">${escapeHtml(it.error)}</p>` : ""}
        </button>
        <div class="row-actions">
          ${it.status === "failed" ? `<button type="button" class="btn btn-ghost btn-small" data-retry="${it.id}">Retry</button>` : ""}
          ${it.status === "completed" ? `<a class="btn btn-ghost btn-small" href="${it.download_url}" download="${escapeHtml(it.download_name || "upscaled.jpg")}">Download JPG</a>` : ""}
        </div>
      `;
      queueEl.appendChild(li);
    });
    renderDetail();
  }

  function renderDetail() {
    const job = state.job;
    const item = job && job.items.find((i) => i.id === state.selectedId);
    if (!item) {
      detail.hidden = true;
      return;
    }
    detail.hidden = false;
    $("compare-before").src = item.preview_url;
    $("compare-after").src = item.result_preview_url || item.preview_url;
    setCompare(state.compare);
    const o = item.original || {};
    const u = item.output || {};
    $("meta-grid").innerHTML = `
      <div class="meta-card">
        <strong>Original</strong>
        <span>${fmtDims(o.width, o.height)}</span>
        <span>${fmtBytes(o.size)}</span>
        <span>${escapeHtml(o.format || "")}</span>
      </div>
      <div class="arrow" aria-hidden="true">↓</div>
      <div class="meta-card">
        <strong>${item.status === "completed" ? "Upscaled" : "Output"}</strong>
        <span>${item.status === "completed" ? fmtDims(u.width, u.height) : "—"}</span>
        <span>${item.status === "completed" ? fmtBytes(u.size) : item.status}</span>
        <span>${item.status === "completed" ? `JPEG · ${u.scale || 4}×` : (item.error || "")}</span>
      </div>
    `;
    const dl = $("btn-download-one");
    if (item.status === "completed") {
      dl.href = item.download_url;
      dl.setAttribute("download", item.download_name || "upscaled.jpg");
      dl.removeAttribute("aria-disabled");
      dl.style.pointerEvents = "";
      dl.style.opacity = "";
    } else {
      dl.href = "#";
      dl.setAttribute("aria-disabled", "true");
      dl.style.pointerEvents = "none";
      dl.style.opacity = "0.45";
    }
    $("btn-retry-one").hidden = item.status !== "failed";
  }

  queueEl.addEventListener("click", (e) => {
    const pick = e.target.closest("[data-pick]");
    if (pick) {
      state.selectedId = pick.getAttribute("data-pick");
      renderJob();
    }
    const retry = e.target.closest("[data-retry]");
    if (retry) retryOne(retry.getAttribute("data-retry"));
  });
  queueEl.addEventListener("change", (e) => {
    const id = e.target.getAttribute("data-check");
    if (!id) return;
    if (e.target.checked) state.checked.add(id);
    else state.checked.delete(id);
  });

  document.querySelectorAll(".pill").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".pill").forEach((b) => b.classList.remove("is-on"));
      btn.classList.add("is-on");
      state.filter = btn.dataset.filter;
      renderJob();
    });
  });
  $("search").addEventListener("input", (e) => {
    state.query = e.target.value;
    renderJob();
  });

  function startPoll() {
    stopPoll();
    state.poll = setInterval(refreshJob, 500);
  }
  function stopPoll() {
    if (state.poll) {
      clearInterval(state.poll);
      state.poll = null;
    }
  }

  async function refreshJob() {
    if (!state.job) return;
    try {
      const job = await api(`/api/jobs/${state.job.id}`);
      state.job = job;
      renderJob();
      const active = job.status === "processing" || job.status === "cancelling" || (job.counts && job.counts.pending && job.status === "processing");
      if (job.status === "completed" || job.status === "cancelled" || job.status === "ready" || job.status === "error") {
        if (!(job.counts && job.counts.processing)) stopPoll();
      }
      if (job.status === "completed") {
        announce("Your image is ready.");
      }
    } catch {
      /* keep polling through transient errors */
    }
  }

  $("btn-process").addEventListener("click", async () => {
    if (!state.job) return;
    try {
      announce("AI upscaling your image…");
      state.job = await api(`/api/jobs/${state.job.id}/process`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(currentSettings()),
      });
      renderJob();
      startPoll();
    } catch (err) {
      toast(err.message, true);
    }
  });

  $("btn-cancel").addEventListener("click", async () => {
    if (!state.job) return;
    try {
      state.job = await api(`/api/jobs/${state.job.id}/cancel`, { method: "POST" });
      renderJob();
      toast("Processing cancelled. Completed images were kept.");
    } catch (err) {
      toast(err.message, true);
    }
  });

  async function retryOne(id) {
    try {
      state.job = await api(`/api/jobs/${state.job.id}/items/${id}/retry`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(currentSettings()),
      });
      renderJob();
      startPoll();
    } catch (err) {
      toast(err.message, true);
    }
  }
  $("btn-retry").addEventListener("click", async () => {
    try {
      state.job = await api(`/api/jobs/${state.job.id}/retry-failed`, { method: "POST" });
      renderJob();
      startPoll();
    } catch (err) {
      toast(err.message, true);
    }
  });
  $("btn-retry-one").addEventListener("click", () => {
    if (state.selectedId) retryOne(state.selectedId);
  });

  $("btn-download-all").addEventListener("click", () => {
    if (!state.job) return;
    window.location = `/api/jobs/${state.job.id}/zip`;
  });
  $("btn-download-selected").addEventListener("click", async () => {
    if (!state.job || !state.checked.size) {
      toast("Select at least one completed image.", true);
      return;
    }
    const res = await fetch(`/api/jobs/${state.job.id}/zip`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_ids: Array.from(state.checked) }),
    });
    if (!res.ok) {
      toast("Nothing to download yet.", true);
      return;
    }
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "upscaled-images.zip";
    a.click();
    URL.revokeObjectURL(a.href);
  });

  $("btn-select-all").addEventListener("click", () => {
    if (!state.job) return;
    state.checked = new Set(filteredItems().map((i) => i.id));
    renderJob();
  });
  $("btn-select-none").addEventListener("click", () => {
    state.checked = new Set();
    renderJob();
  });
  $("btn-remove-selected").addEventListener("click", async () => {
    if (!state.job) return;
    for (const id of Array.from(state.checked)) {
      try {
        state.job = await api(`/api/jobs/${state.job.id}/items/${id}`, { method: "DELETE" });
      } catch (err) {
        toast(err.message, true);
      }
    }
    state.checked = new Set();
    renderJob();
  });
  $("btn-clear-completed").addEventListener("click", async () => {
    if (!state.job) return;
    const ids = state.job.items.filter((i) => i.status === "completed").map((i) => i.id);
    for (const id of ids) {
      state.job = await api(`/api/jobs/${state.job.id}/items/${id}`, { method: "DELETE" });
    }
    renderJob();
  });
  $("btn-clear-all").addEventListener("click", async () => {
    if (!state.job) return;
    await api(`/api/jobs/${state.job.id}`, { method: "DELETE" });
    state.job = null;
    stopPoll();
    renderJob();
    toast("Queue cleared.");
  });

  function setCompare(pct) {
    state.compare = Math.min(100, Math.max(0, pct));
    $("compare-before-wrap").style.width = state.compare + "%";
    $("compare-handle").style.left = state.compare + "%";
  }
  const compare = $("compare");
  function pointerPct(e) {
    const r = compare.getBoundingClientRect();
    const x = (e.clientX ?? (e.touches && e.touches[0].clientX) ?? 0) - r.left;
    return (x / r.width) * 100;
  }
  let dragging = false;
  compare.addEventListener("pointerdown", (e) => {
    dragging = true;
    compare.setPointerCapture(e.pointerId);
    setCompare(pointerPct(e));
  });
  compare.addEventListener("pointermove", (e) => {
    if (dragging) setCompare(pointerPct(e));
  });
  compare.addEventListener("pointerup", () => { dragging = false; });
  compare.addEventListener("pointercancel", () => { dragging = false; });
  compare.addEventListener("keydown", (e) => {
    if (e.key === "ArrowLeft") { e.preventDefault(); setCompare(state.compare - 4); }
    if (e.key === "ArrowRight") { e.preventDefault(); setCompare(state.compare + 4); }
  });

})();
