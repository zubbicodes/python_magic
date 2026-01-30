const state = {
  scripts: [],
  filtered: [],
  selectedRelPath: null,
  selectedScript: null,
  tab: "combined",
  lastRun: null,
  inputEls: {},
};

const els = {
  rootPill: document.getElementById("rootPathPill"),
  apiBasePill: document.getElementById("apiBasePill"),
  search: document.getElementById("searchInput"),
  list: document.getElementById("scriptList"),
  tpl: document.getElementById("scriptRowTpl"),
  title: document.getElementById("scriptTitle"),
  path: document.getElementById("scriptPath"),
  guidedInputs: document.getElementById("guidedInputs"),
  args: document.getElementById("argsInput"),
  timeout: document.getElementById("timeoutInput"),
  runBtn: document.getElementById("runBtn"),
  runMeta: document.getElementById("runMeta"),
  console: document.getElementById("console"),
  artifacts: document.getElementById("artifacts"),
  advancedBox: document.getElementById("advancedBox"),
  tabs: Array.from(document.querySelectorAll(".tab")),
};

const apiBaseFromQuery = new URLSearchParams(location.search).get("api");
if (apiBaseFromQuery) {
  localStorage.setItem("toolSiteApiBase", apiBaseFromQuery);
}
const API_BASE = localStorage.getItem("toolSiteApiBase") || "";

function apiUrl(path) {
  if (!API_BASE) return path;
  return `${API_BASE}`.replace(/\/$/, "") + path;
}

function escapeText(text) {
  return String(text ?? "");
}

function setBusy(isBusy) {
  els.runBtn.disabled = isBusy || !state.selectedRelPath;
  els.args.disabled = isBusy || !state.selectedRelPath;
  els.search.disabled = isBusy;
  els.list.style.opacity = isBusy ? "0.85" : "1";
  els.runBtn.textContent = isBusy ? "Running…" : "Run";

  for (const el of Object.values(state.inputEls)) {
    if (el && "disabled" in el) el.disabled = isBusy;
  }
}

function setTab(nextTab) {
  state.tab = nextTab;
  for (const btn of els.tabs) {
    btn.classList.toggle("tab--active", btn.dataset.tab === nextTab);
  }
  renderOutput();
}

function renderList() {
  els.list.innerHTML = "";
  const frag = document.createDocumentFragment();
  for (const s of state.filtered) {
    const node = els.tpl.content.firstElementChild.cloneNode(true);
    node.classList.toggle("scriptRow--active", s.relPath === state.selectedRelPath);
    node.querySelector(".scriptRow__name").textContent = s.displayName || s.name;
    node.querySelector(".scriptRow__path").textContent = s.summary
      ? `${s.relPath} — ${s.summary}`
      : s.relPath;
    node.addEventListener("click", () => selectScript(s.relPath));
    frag.appendChild(node);
  }
  els.list.appendChild(frag);
}

function clearInputs() {
  state.inputEls = {};
  els.guidedInputs.innerHTML = "";
}

function renderGuidedInputs(script) {
  clearInputs();

  const ui = script?.ui;
  const inputs = ui?.inputs;
  if (!ui || ui.mode !== "guided" || !Array.isArray(inputs) || inputs.length === 0) {
    els.guidedInputs.innerHTML = "";
    return;
  }

  const frag = document.createDocumentFragment();

  for (const inputDef of inputs) {
    const key = inputDef?.key;
    const labelText = inputDef?.label || key;
    const type = inputDef?.type || "text";
    if (!key) continue;

    const row = document.createElement("div");
    row.className = "formRow";

    const label = document.createElement("label");
    label.className = "label";
    label.textContent = labelText;
    const id = `inp_${key}`;
    label.setAttribute("for", id);

    let control;
    if (type === "boolean") {
      control = document.createElement("input");
      control.type = "checkbox";
      control.id = id;
      control.checked = Boolean(inputDef?.value);
      control.style.width = "18px";
      control.style.height = "18px";
    } else if (type === "number") {
      control = document.createElement("input");
      control.type = "number";
      control.id = id;
      control.className = "input input--small";
      if (typeof inputDef?.min === "number") control.min = String(inputDef.min);
      if (typeof inputDef?.max === "number") control.max = String(inputDef.max);
      control.value = inputDef?.value != null ? String(inputDef.value) : "";
    } else if (type === "url") {
      control = document.createElement("input");
      control.type = "url";
      control.id = id;
      control.className = "input";
      control.placeholder = "https://example.com/";
      control.value = inputDef?.value != null ? String(inputDef.value) : "";
    } else if (type === "file" || type === "files") {
      control = document.createElement("input");
      control.type = "file";
      control.id = id;
      control.className = "input";
      const accept = Array.isArray(inputDef?.accept) ? inputDef.accept.join(",") : "";
      if (accept) control.setAttribute("accept", accept);
      if (type === "files" || inputDef?.multiple) control.multiple = true;
    } else {
      control = document.createElement("input");
      control.type = "text";
      control.id = id;
      control.className = "input";
      control.value = inputDef?.value != null ? String(inputDef.value) : "";
    }

    row.appendChild(label);
    row.appendChild(control);
    frag.appendChild(row);

    if ((type === "file" || type === "files") && Array.isArray(inputDef?.accept) && inputDef.accept.length) {
      const hint = document.createElement("div");
      hint.className = "fileHint";
      hint.textContent = `Accepted: ${inputDef.accept.join(", ")}`;
      frag.appendChild(hint);
    }

    state.inputEls[key] = control;
  }

  els.guidedInputs.appendChild(frag);
}

function selectScript(relPath) {
  state.selectedRelPath = relPath;
  const script = state.scripts.find((s) => s.relPath === relPath) || null;
  state.selectedScript = script;
  els.title.textContent = script ? script.displayName || script.name : "Select a script";
  els.path.textContent = script ? script.relPath : "";
  els.args.disabled = !script;
  els.runBtn.disabled = !script;
  if (script) {
    renderGuidedInputs(script);
    if (Object.keys(state.inputEls).length) {
      const first = Object.values(state.inputEls)[0];
      if (first && typeof first.focus === "function") first.focus();
    } else {
      els.args.focus();
    }
  }
  state.lastRun = null;
  els.runMeta.textContent = "";
  els.console.textContent = "";
  renderArtifacts([]);
  renderList();
}

function filterScripts(query) {
  const q = query.trim().toLowerCase();
  if (!q) {
    state.filtered = state.scripts;
    renderList();
    return;
  }
  state.filtered = state.scripts.filter((s) => {
    const hay = `${s.displayName ?? ""} ${s.name} ${s.summary ?? ""} ${s.relPath} ${s.folder} ${
      s.description ?? ""
    }`.toLowerCase();
    return hay.includes(q);
  });
  renderList();
}

function renderOutput() {
  const run = state.lastRun;
  if (!run) {
    els.console.textContent = "";
    return;
  }

  const stdout = escapeText(run.stdout);
  const stderr = escapeText(run.stderr);
  if (state.tab === "stdout") {
    els.console.textContent = stdout || "(no stdout)";
    return;
  }
  if (state.tab === "stderr") {
    els.console.textContent = stderr || "(no stderr)";
    return;
  }

  const combined = [stdout && `--- stdout ---\n${stdout}`, stderr && `--- stderr ---\n${stderr}`]
    .filter(Boolean)
    .join("\n\n");
  els.console.textContent = combined || "(no output)";
}

function formatMeta(run) {
  if (!run) return "";
  const parts = [];
  if (typeof run.returnCode === "number") parts.push(`exit ${run.returnCode}`);
  if (typeof run.durationMs === "number") parts.push(`${run.durationMs}ms`);
  if (run.error) parts.push(run.error);
  return parts.join(" · ");
}

function arrayBufferToBase64(buf) {
  const bytes = new Uint8Array(buf);
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

function base64ToBlob(base64, mime) {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return new Blob([bytes], { type: mime || "application/octet-stream" });
}

function renderArtifacts(artifacts) {
  els.artifacts.innerHTML = "";
  if (!Array.isArray(artifacts) || artifacts.length === 0) return;

  const frag = document.createDocumentFragment();
  for (const a of artifacts) {
    if (!a?.filename || !a?.base64) continue;
    const mime = a.mime || "application/octet-stream";
    const blob = base64ToBlob(a.base64, mime);
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.className = "artifactBtn";
    link.href = url;
    link.download = a.filename;
    link.textContent = `Download ${a.filename}`;
    frag.appendChild(link);
  }
  els.artifacts.appendChild(frag);
}

async function collectGuidedPayload(script) {
  const ui = script?.ui;
  const inputsDef = ui?.inputs;
  const inputs = {};
  const files = {};

  if (!Array.isArray(inputsDef)) return { inputs, files };

  for (const def of inputsDef) {
    const key = def?.key;
    const type = def?.type;
    if (!key) continue;
    const el = state.inputEls[key];
    if (!el) continue;

    if (type === "boolean") {
      inputs[key] = Boolean(el.checked);
      continue;
    }
    if (type === "number") {
      const n = Number(el.value);
      inputs[key] = Number.isFinite(n) ? n : def?.value ?? null;
      continue;
    }
    if (type === "file" || type === "files") {
      const selected = Array.from(el.files || []);
      if (selected.length === 0) continue;
      const encoded = [];
      for (const f of selected) {
        const buf = await f.arrayBuffer();
        encoded.push({ name: f.name, base64: arrayBufferToBase64(buf) });
      }
      files[key] = encoded;
      continue;
    }
    inputs[key] = el.value != null ? String(el.value) : "";
  }

  return { inputs, files };
}

async function runSelected() {
  if (!state.selectedRelPath) return;

  const timeout = Math.max(1, Math.min(3600, Number(els.timeout.value || 300)));
  const args = els.args.value || "";

  setBusy(true);
  els.runMeta.textContent = "Running…";
  els.console.textContent = "";
  state.lastRun = null;
  renderArtifacts([]);

  try {
    const script = state.selectedScript;
    const isGuided = script?.ui?.mode === "guided";
    const endpoint = isGuided ? "/api/tool/run" : "/api/run";

    let body;
    if (isGuided) {
      const payload = await collectGuidedPayload(script);
      body = JSON.stringify({ toolRelPath: script.relPath, inputs: payload.inputs, files: payload.files });
    } else {
      body = JSON.stringify({ scriptRelPath: state.selectedRelPath, args });
    }

    const res = await fetch(`${apiUrl(endpoint)}?timeout=${encodeURIComponent(timeout)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });

    const payload = await res.json().catch(() => null);
    if (!res.ok) {
      const msg = payload?.error ? String(payload.error) : `Request failed (${res.status})`;
      state.lastRun = { stdout: "", stderr: "", returnCode: null, durationMs: null, error: msg };
      els.runMeta.textContent = formatMeta(state.lastRun);
      renderOutput();
      return;
    }

    state.lastRun = payload;
    els.runMeta.textContent = formatMeta(payload);
    renderOutput();
    renderArtifacts(payload.artifacts || []);
  } catch (e) {
    state.lastRun = { stdout: "", stderr: "", returnCode: null, durationMs: null, error: String(e) };
    els.runMeta.textContent = formatMeta(state.lastRun);
    renderOutput();
  } finally {
    setBusy(false);
  }
}

function bind() {
  els.search.addEventListener("input", (e) => filterScripts(e.target.value));
  els.runBtn.addEventListener("click", runSelected);
  els.args.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) runSelected();
  });
  els.tabs.forEach((btn) => btn.addEventListener("click", () => setTab(btn.dataset.tab)));
}

async function boot() {
  bind();
  setBusy(true);
  els.rootPill.textContent = "Loading…";

  try {
    if (API_BASE) {
      els.apiBasePill.hidden = false;
      els.apiBasePill.textContent = API_BASE;
    }

    const res = await fetch(apiUrl("/api/scripts"));
    const data = await res.json();
    state.scripts = (data.scripts || []).map((s) => ({
      relPath: s.relPath,
      name: s.name,
      folder: s.folder,
      description: s.description,
      displayName: s.displayName,
      summary: s.summary,
      ui: s.ui,
    }));
    state.filtered = state.scripts;
    els.rootPill.textContent = data.root || "";
    renderList();
  } catch (e) {
    els.rootPill.textContent = "Failed to load scripts";
    els.console.textContent = String(e);
  } finally {
    setBusy(false);
  }
}

boot();
