(function () {
  "use strict";

  if (window.EazyFillRecorderPanel) return;

  let root = null;
  let dragging = false;
  let dragOffset = { x: 0, y: 0 };
  let callbacks = {};
  let currentSession = null;

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "\"": "&quot;",
      "'": "&#39;"
    }[char]));
  }

  function safeValue(step) {
    if (step.sensitive) return "hidden";
    if (step.action === "click") return "";
    return String(step.value ?? "").slice(0, 64);
  }

  function selectorLabel(step) {
    const selector = step.selector || {};
    return selector.id
      ? `#${selector.id}`
      : selector.name
        ? `[name="${selector.name}"]`
        : selector.css || selector.primary || selector.xpath || "selector";
  }

  function getInputValue(name, fallback = "") {
    return root?.querySelector(`[data-field="${name}"]`)?.value?.trim() || fallback;
  }

  function readPanelState() {
    return {
      name: getInputValue("name", currentSession?.name || ""),
      ruleType: getInputValue("ruleType", currentSession?.ruleType || "instant"),
      matchMode: getInputValue("matchMode", currentSession?.matchMode || "domainPath"),
      pattern: getInputValue("pattern", currentSession?.pattern || "")
    };
  }

  function bindEvents() {
    const handle = root.querySelector('[data-role="handle"]');
    handle.addEventListener("mousedown", (event) => {
      dragging = true;
      const rect = root.getBoundingClientRect();
      dragOffset = { x: event.clientX - rect.left, y: event.clientY - rect.top };
      event.preventDefault();
    });

    document.addEventListener("mousemove", (event) => {
      if (!dragging || !root) return;
      root.style.left = `${Math.max(6, Math.min(window.innerWidth - root.offsetWidth - 6, event.clientX - dragOffset.x))}px`;
      root.style.top = `${Math.max(6, Math.min(window.innerHeight - root.offsetHeight - 6, event.clientY - dragOffset.y))}px`;
      root.style.right = "auto";
      root.style.bottom = "auto";
    });
    document.addEventListener("mouseup", () => {
      dragging = false;
    });

    root.addEventListener("click", (event) => {
      const button = event.target?.closest?.("[data-action]");
      if (!button || !root.contains(button)) return;
      event.preventDefault();
      event.stopPropagation();

      const action = button.dataset.action;
      if (action === "save") callbacks.onSave?.(readPanelState());
      if (action === "discard") callbacks.onDiscard?.();
      if (action === "clear") callbacks.onClear?.();
      if (action === "remove") callbacks.onRemove?.(Number(button.dataset.index || -1));
      if (action === "pause") {
        const paused = callbacks.onPause?.();
        button.textContent = paused ? "Resume" : "Pause";
        setStatus(paused ? "Recording paused." : "Recording resumed.", paused ? "warning" : "neutral");
      }
    }, true);

    root.addEventListener("input", (event) => {
      const field = event.target?.dataset?.field;
      if (!field) return;
      callbacks.onUpdate?.(readPanelState(), field);
    }, true);

    root.addEventListener("change", (event) => {
      const field = event.target?.dataset?.field;
      if (!field) return;
      callbacks.onUpdate?.(readPanelState(), field);
    }, true);
  }

  function createPanel() {
    if (root) return root;
    root = document.createElement("div");
    root.id = "eazyfill-recorder-panel";
    root.style.cssText = [
      "position:fixed",
      "right:18px",
      "bottom:18px",
      "z-index:2147483646",
      "width:380px",
      "max-width:calc(100vw - 24px)",
      "background:#181a20",
      "color:#f8fafc",
      "border:1px solid rgba(255,255,255,.16)",
      "border-radius:8px",
      "box-shadow:0 18px 50px rgba(0,0,0,.34)",
      "font:12px/1.4 Inter,Segoe UI,system-ui,sans-serif",
      "overflow:hidden"
    ].join(";");
    root.innerHTML = '<div data-role="handle" style="display:flex;align-items:center;justify-content:space-between;gap:10px;padding:10px 12px;background:#24262d;border-bottom:1px solid rgba(255,255,255,.12);cursor:move"><strong style="font-size:12px;color:#f59e0b">Recording</strong><button data-action="discard" type="button" title="Stop" style="border:0;background:transparent;color:#a8b3c7;cursor:pointer;font-weight:800">x</button></div><div data-role="body"></div>';
    document.documentElement.appendChild(root);
    bindEvents();
    return root;
  }

  function renderSession(session = {}) {
    currentSession = session;
    createPanel();
    const steps = Array.isArray(session.steps) ? session.steps : [];
    const rows = steps.map((step, index) => {
      const value = safeValue(step);
      const selector = selectorLabel(step);
      const confidence = step.selector?.confidence !== undefined
        ? `<span style="padding:2px 6px;border-radius:999px;background:#153528;color:#8df5bf;border:1px solid rgba(141,245,191,.24)">${escapeHtml(step.selector.confidence)}%</span>`
        : "";
      return `
        <li style="display:grid;grid-template-columns:22px 1fr auto;gap:8px;align-items:start;margin:0 0 8px;padding:8px;border:1px solid rgba(255,255,255,.12);border-radius:8px;background:#101114">
          <span style="height:22px;border-radius:999px;background:#2563eb;color:white;display:grid;place-items:center;font-weight:800;font-size:11px">${index + 1}</span>
          <span style="min-width:0">
            <span style="display:flex;gap:5px;align-items:center;flex-wrap:wrap">
              <strong style="text-transform:capitalize;color:#f8fafc">${escapeHtml(step.action || "step")}</strong>
              <span style="color:#93c5fd">${escapeHtml(step.label || step.fieldKey || "field")}</span>
              ${confidence}
            </span>
            <span style="display:block;margin-top:4px;color:#a8b3c7;font-family:ui-monospace,SFMono-Regular,Consolas,monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${escapeHtml(selector)}</span>
            ${value ? `<span style="display:block;margin-top:4px;color:#cbd5e1">Value: ${escapeHtml(value)}</span>` : ""}
          </span>
          <button data-action="remove" data-index="${index}" type="button" title="Remove step" style="border:1px solid rgba(248,113,113,.35);border-radius:7px;background:#321a1e;color:#fca5a5;padding:3px 7px;font-weight:800;cursor:pointer">x</button>
        </li>
      `;
    }).join("");

    const body = root.querySelector('[data-role="body"]');
    body.innerHTML = `
      <div style="padding:10px 12px;display:grid;grid-template-columns:1fr 1fr;gap:9px">
        <label style="grid-column:1/-1;display:grid;gap:4px;color:#a8b3c7;font-weight:700">
          <span>Rule name</span>
          <input data-field="name" data-role="name" type="text" value="${escapeHtml(session.name || "")}" style="width:100%;box-sizing:border-box;border-radius:6px;border:1px solid rgba(255,255,255,.16);background:#101114;color:#f8fafc;padding:7px 8px">
        </label>
        <label style="display:grid;gap:4px;color:#a8b3c7;font-weight:700">
          <span>Mode</span>
          <select data-field="ruleType" style="width:100%;box-sizing:border-box;border-radius:6px;border:1px solid rgba(255,255,255,.16);background:#101114;color:#f8fafc;padding:7px 8px">
            <option value="instant"${session.ruleType === "instant" ? " selected" : ""}>Instant</option>
            <option value="flow"${session.ruleType === "flow" ? " selected" : ""}>Flow</option>
          </select>
        </label>
        <label style="display:grid;gap:4px;color:#a8b3c7;font-weight:700">
          <span>Scope</span>
          <select data-field="matchMode" style="width:100%;box-sizing:border-box;border-radius:6px;border:1px solid rgba(255,255,255,.16);background:#101114;color:#f8fafc;padding:7px 8px">
            <option value="domainPath"${session.matchMode === "domainPath" ? " selected" : ""}>This page</option>
            <option value="domain"${session.matchMode === "domain" ? " selected" : ""}>Domain</option>
            <option value="fullUrl"${session.matchMode === "fullUrl" ? " selected" : ""}>Exact URL</option>
          </select>
        </label>
        <label style="grid-column:1/-1;display:grid;gap:4px;color:#a8b3c7;font-weight:700">
          <span>Pattern</span>
          <input data-field="pattern" type="text" value="${escapeHtml(session.pattern || "")}" style="width:100%;box-sizing:border-box;border-radius:6px;border:1px solid rgba(255,255,255,.16);background:#101114;color:#f8fafc;padding:7px 8px;font-family:ui-monospace,SFMono-Regular,Consolas,monospace">
        </label>
        <div data-role="status" role="status" aria-live="polite" style="grid-column:1/-1;min-height:17px;color:#a8b3c7">${escapeHtml(session.lastDebug || "Waiting for field interaction.")}</div>
      </div>
      <ol data-role="steps" style="list-style:none;margin:0;padding:0 12px;max-height:240px;overflow:auto">
        ${rows || '<li style="margin-bottom:10px;padding:14px;border:1px dashed rgba(255,255,255,.18);border-radius:8px;color:#a8b3c7;text-align:center">Waiting for field interaction</li>'}
      </ol>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;padding:10px 12px;border-top:1px solid rgba(255,255,255,.12);background:#24262d">
        <button data-action="save" type="button" style="border:0;border-radius:8px;background:#10b981;color:white;padding:8px 9px;font-weight:800;cursor:pointer">Save</button>
        <button data-action="pause" type="button" style="border:1px solid rgba(255,255,255,.16);border-radius:8px;background:#181a20;color:#f8fafc;padding:8px 9px;font-weight:800;cursor:pointer">${session.paused ? "Resume" : "Pause"}</button>
        <button data-action="clear" type="button" style="border:1px solid rgba(255,255,255,.16);border-radius:8px;background:#181a20;color:#f8fafc;padding:8px 9px;font-weight:800;cursor:pointer">Clear</button>
      </div>
    `;
  }

  function renderSteps(steps) {
    renderSession({ ...(currentSession || {}), steps });
  }

  function setBusy(busy) {
    if (!root) return;
    for (const button of root.querySelectorAll("button, input, select")) button.disabled = !!busy;
  }

  function setStatus(message, tone = "neutral") {
    if (!root) return;
    const status = root.querySelector('[data-role="status"]');
    if (!status) return;
    status.textContent = message || "";
    status.style.color = tone === "success" ? "#34d399"
      : tone === "warning" ? "#fbbf24"
        : tone === "error" ? "#f87171" : "#a8b3c7";
  }

  function show(options = {}) {
    callbacks = options.callbacks || {};
    createPanel();
    root.hidden = false;
    setBusy(false);
    renderSession(options.session || { steps: options.steps || [] });
  }

  function hide() {
    if (root) root.hidden = true;
  }

  window.EazyFillRecorderPanel = {
    hide,
    renderSession,
    renderSteps,
    setBusy,
    setStatus,
    show
  };
})();
