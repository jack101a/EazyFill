(function () {
  "use strict";

  if (window.EazyFillRecorderEngine) return;

  const SESSION_KEY = "__eazyfill_autofill_record_session_v2";
  const DEBOUNCE_MS = 1200;

  let recording = false;
  let paused = false;
  let session = null;
  let listenersInstalled = false;
  let finishTimer = null;
  let lastSignature = "";
  let lastRecordedAt = 0;

  function sendMessage(message) {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage(message, (response) => {
        if (chrome.runtime.lastError) {
          resolve({ ok: false, error: chrome.runtime.lastError.message });
          return;
        }
        resolve(response || { ok: false, error: "No response" });
      });
    });
  }

  function normalizedHost() {
    return String(location.hostname || "").replace(/^www\./, "").toLowerCase();
  }

  function patternForMode(mode) {
    if (mode === "domain") return normalizedHost();
    if (mode === "fullUrl") return location.href;
    return `${normalizedHost()}${location.pathname || "/"}`;
  }

  function nicePageName() {
    const leaf = location.pathname.split("/").filter(Boolean).pop() || normalizedHost();
    return String(leaf)
      .replace(/\.(do|html?|xhtml|php|aspx?)$/i, "")
      .replace(/([a-z])([A-Z])/g, "$1 $2")
      .replace(/[-_]+/g, " ")
      .replace(/\b\w/g, (char) => char.toUpperCase())
      .trim() || normalizedHost();
  }

  function fieldKeyFromLabel(label, fallback) {
    return String(label || fallback || "field")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .slice(0, 48) || "field";
  }

  function selectorShortName(step) {
    const selector = step?.selector || {};
    return step?.label
      || step?.fieldKey
      || selector.label
      || selector.id
      || selector.name
      || selector.css
      || selector.primary
      || step?.action
      || "field";
  }

  function buildRuleName(recordSession) {
    const steps = Array.isArray(recordSession?.steps) ? recordSession.steps : [];
    const page = nicePageName();
    if (!steps.length) return `Autofill ${page}`;
    const actions = steps.map((step) => String(step.action || "").toLowerCase());
    const clickOnly = actions.every((action) => action === "click");
    const primary = String(selectorShortName(steps[0])).replace(/^#/, "").replace(/\s+/g, " ").trim().slice(0, 42);
    if (steps.length === 1) {
      if (actions[0] === "click") return `Click ${primary} on ${page}`;
      return `Fill ${primary} on ${page}`;
    }
    if (clickOnly) return `Click flow on ${page} (${steps.length} steps)`;
    return `${recordSession.ruleType === "flow" ? "Flow" : "Autofill"} ${page} (${steps.length} fields)`;
  }

  function defaultSession() {
    return {
      id: `rec_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
      name: "",
      autoName: true,
      ruleType: "instant",
      matchMode: "domainPath",
      pattern: patternForMode("domainPath"),
      profileId: "default",
      steps: [],
      lastDebug: "Waiting for field interaction.",
      startedAt: new Date().toISOString(),
      updatedAt: Date.now(),
      active: true,
      paused: false
    };
  }

  function normalizeSession(value) {
    const next = value && typeof value === "object" ? value : defaultSession();
    next.steps = Array.isArray(next.steps) ? next.steps : [];
    next.ruleType = next.ruleType === "flow" ? "flow" : "instant";
    next.matchMode = ["domain", "domainPath", "fullUrl"].includes(next.matchMode) ? next.matchMode : "domainPath";
    next.pattern = next.pattern || patternForMode(next.matchMode);
    next.profileId = next.profileId || "default";
    next.active = true;
    next.paused = !!next.paused;
    next.name = next.name || buildRuleName(next);
    return next;
  }

  function persistSession() {
    if (!session) return;
    session.updatedAt = Date.now();
    session.paused = paused;
    try {
      window.sessionStorage?.setItem(SESSION_KEY, JSON.stringify(session));
    } catch (_) {
      // Some pages disable storage; recording can still continue in memory.
    }
  }

  function restoreSession() {
    try {
      const raw = window.sessionStorage?.getItem(SESSION_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!parsed?.active) return null;
      return normalizeSession(parsed);
    } catch (_) {
      return null;
    }
  }

  function clearSession() {
    session = null;
    try {
      window.sessionStorage?.removeItem(SESSION_KEY);
    } catch (_) {}
  }

  function syncAutoName() {
    if (!session) return;
    if (session.autoName !== false) session.name = buildRuleName(session);
  }

  function render() {
    if (!session) return;
    syncAutoName();
    persistSession();
    window.EazyFillRecorderPanel?.renderSession(session);
  }

  function closestRecordable(source) {
    if (!source?.closest) return null;
    return source.closest("input, textarea, select, button, a, [role='button']");
  }

  function isRecordable(element) {
    if (!element || !(element instanceof HTMLElement)) return false;
    if (element.closest?.("#eazyfill-recorder-panel")) return false;
    if (element instanceof HTMLInputElement && element.type === "password") return false;
    const tag = element.tagName.toLowerCase();
    return ["input", "textarea", "select", "button", "a"].includes(tag) || element.getAttribute("role") === "button";
  }

  function isTextLikeInput(element) {
    if (!(element instanceof HTMLInputElement)) return false;
    return !["button", "submit", "reset", "checkbox", "radio", "file", "image", "hidden", "password"].includes(element.type);
  }

  function inferAction(element, eventType) {
    if (element instanceof HTMLSelectElement) return "select";
    if (element instanceof HTMLInputElement) {
      if (element.type === "checkbox") return element.checked ? "check" : "uncheck";
      if (element.type === "radio") return "radio";
      if (["button", "submit", "reset", "image"].includes(element.type)) return "click";
    }
    if (eventType === "submit") return "click";
    if (element instanceof HTMLButtonElement || element.tagName === "A" || element.getAttribute("role") === "button") return "click";
    return "set_value";
  }

  function readValue(element, action) {
    if (action === "click") return "";
    if (element instanceof HTMLInputElement) {
      if (element.type === "checkbox") return !!element.checked;
      if (element.type === "radio") return element.value || "on";
      return element.value;
    }
    if (element instanceof HTMLTextAreaElement || element instanceof HTMLSelectElement) return element.value;
    return element.innerText || element.textContent || "";
  }

  function buildElementMeta(element) {
    return {
      tag: element.tagName.toLowerCase(),
      type: element.type || "",
      id: element.id || "",
      name: element.name || "",
      placeholder: element.getAttribute("placeholder") || "",
      ariaLabel: element.getAttribute("aria-label") || "",
      title: element.getAttribute("title") || "",
      visibleText: ["BUTTON", "A"].includes(element.tagName) ? String(element.innerText || element.textContent || "").trim().slice(0, 160) : "",
      required: !!element.required,
      disabled: !!element.disabled,
      readonly: !!element.readOnly
    };
  }

  function stepTargetSignature(step) {
    const selector = step?.selector || {};
    return [
      step?.action || "",
      selector.id || "",
      selector.name || "",
      selector.css || "",
      selector.primary || "",
      selector.xpath || ""
    ].join("|");
  }

  function stepSignature(step) {
    return [
      session?.matchMode || "",
      session?.pattern || "",
      stepTargetSignature(step),
      String(step?.value ?? "")
    ].join("|");
  }

  function buildStep(element, eventType) {
    const selector = window.EazyFillSelectorBuilder?.buildSelector(element) || {
      strategy: "css",
      primary: element.id ? `#${element.id}` : element.tagName.toLowerCase(),
      css: element.id ? `#${element.id}` : element.tagName.toLowerCase(),
      confidence: 20,
      label: ""
    };
    const action = inferAction(element, eventType);
    const label = selector.label || element.getAttribute("aria-label") || element.name || element.id || element.innerText || element.tagName.toLowerCase();
    const value = readValue(element, action);
    return {
      order: session.steps.length + 1,
      action,
      selector,
      value,
      fieldKey: fieldKeyFromLabel(label, element.name || element.id || `field_${session.steps.length + 1}`),
      label: String(label || "").trim().slice(0, 120),
      required: element.required === true,
      sensitive: false,
      element: buildElementMeta(element),
      runtime: {
        required: true,
        delayMs: session.ruleType === "flow" ? 150 : 100,
        timeoutMs: session.ruleType === "flow" ? 5000 : 3000,
        verifyAfterFill: true
      },
      meta: {
        domain: normalizedHost(),
        path: location.pathname,
        fullUrl: location.href,
        recordedAt: new Date().toISOString()
      }
    };
  }

  function shouldSkipEvent(event, element) {
    if (event.isTrusted === false) return true;
    if (!isRecordable(element)) return true;
    if (["pointerdown", "mousedown", "touchstart"].includes(event.type)) {
      return !(element instanceof HTMLButtonElement || element.tagName === "A" || ["button", "submit", "reset", "image"].includes(element.type || ""));
    }
    if (event.type === "click") {
      return element instanceof HTMLTextAreaElement
        || element instanceof HTMLSelectElement
        || isTextLikeInput(element)
        || (element instanceof HTMLInputElement && ["checkbox", "radio"].includes(element.type));
    }
    if (event.type === "input" && element instanceof HTMLSelectElement) return true;
    return false;
  }

  function capture(event) {
    if (!recording || paused) return;
    const element = closestRecordable(event.submitter || event.target);
    if (shouldSkipEvent(event, element)) return;

    const step = buildStep(element, event.type);
    if (step.action === "click") {
      session.ruleType = "flow";
      session.matchMode = session.matchMode || "domainPath";
      session.pattern = session.pattern || patternForMode(session.matchMode);
    }

    const signature = stepSignature(step);
    const now = Date.now();
    if (signature === lastSignature && now - lastRecordedAt < DEBOUNCE_MS) return;
    lastSignature = signature;
    lastRecordedAt = now;

    const lastStep = session.steps[session.steps.length - 1];
    if (lastStep && ["set_value", "select", "check", "uncheck", "radio"].includes(step.action) && stepTargetSignature(lastStep) === stepTargetSignature(step)) {
      session.steps[session.steps.length - 1] = {
        ...lastStep,
        ...step,
        order: lastStep.order,
        meta: { ...(lastStep.meta || {}), updatedAt: new Date().toISOString() }
      };
    } else {
      session.steps.push(step);
    }

    session.lastDebug = `Captured ${step.action} from ${step.label || "field"}.`;
    render();
  }

  function installCaptureListeners() {
    if (listenersInstalled) return;
    listenersInstalled = true;
    document.addEventListener("input", capture, true);
    document.addEventListener("change", capture, true);
    document.addEventListener("pointerdown", capture, true);
    document.addEventListener("mousedown", capture, true);
    document.addEventListener("touchstart", capture, true);
    document.addEventListener("click", capture, true);
    document.addEventListener("submit", capture, true);
  }

  function removeCaptureListeners() {
    if (!listenersInstalled) return;
    listenersInstalled = false;
    document.removeEventListener("input", capture, true);
    document.removeEventListener("change", capture, true);
    document.removeEventListener("pointerdown", capture, true);
    document.removeEventListener("mousedown", capture, true);
    document.removeEventListener("touchstart", capture, true);
    document.removeEventListener("click", capture, true);
    document.removeEventListener("submit", capture, true);
  }

  function applyPanelUpdate(nextState, changedField) {
    if (!session) return;
    if (changedField === "name") session.autoName = false;
    if (changedField === "matchMode" && nextState.matchMode !== session.matchMode) {
      session.matchMode = nextState.matchMode;
      session.pattern = patternForMode(session.matchMode);
    }
    session.name = nextState.name || session.name;
    session.ruleType = nextState.ruleType === "flow" ? "flow" : "instant";
    session.matchMode = ["domain", "domainPath", "fullUrl"].includes(nextState.matchMode) ? nextState.matchMode : session.matchMode;
    if (changedField !== "matchMode") session.pattern = nextState.pattern || session.pattern;
    session.lastDebug = session.lastDebug || "Waiting for field interaction.";
    persistSession();
    if (changedField === "matchMode") render();
  }

  function removeStep(index) {
    if (!session || index < 0 || index >= session.steps.length) return;
    session.steps.splice(index, 1);
    session.steps.forEach((step, nextIndex) => {
      step.order = nextIndex + 1;
    });
    session.lastDebug = "Step removed.";
    render();
  }

  function clearSteps() {
    if (!session) return;
    session.steps = [];
    session.lastDebug = "Recorder cleared.";
    render();
  }

  async function saveRule(panelState = {}) {
    if (!session?.steps?.length) {
      window.EazyFillRecorderPanel?.setStatus("Interact with a field before saving.", "warning");
      return;
    }
    applyPanelUpdate(panelState, "");
    syncAutoName();
    window.EazyFillRecorderPanel?.setBusy(true);
    window.EazyFillRecorderPanel?.setStatus("Saving rule...", "neutral");

    const ruleType = session.ruleType === "flow" ? "flow" : "instant";
    const now = Date.now();
    const response = await sendMessage({
      type: "RECORDER_SAVE_RULE",
      rule: {
        id: session.id.replace(/^rec_/, "rule_"),
        schemaVersion: 2,
        name: session.name || buildRuleName(session),
        enabled: true,
        priority: 100,
        site: {
          matchMode: session.matchMode,
          pattern: session.pattern || patternForMode(session.matchMode),
          path: location.pathname || "/"
        },
        ruleType,
        execution: {
          mode: ruleType,
          delayMs: ruleType === "flow" ? 150 : 100,
          runOnce: true,
          waitTimeoutMs: ruleType === "flow" ? 5000 : 3000,
          stopOnError: ruleType === "flow"
        },
        steps: session.steps.map((step, index) => ({ ...step, order: index + 1 })),
        profileId: session.profileId || "default",
        createdAt: now,
        updatedAt: now,
        meta: {
          recordedAt: session.startedAt,
          savedAt: new Date().toISOString(),
          recorder: "content_session"
        }
      }
    });

    if (!response.ok) {
      window.EazyFillRecorderPanel?.setBusy(false);
      window.EazyFillRecorderPanel?.setStatus(response.error || "Rule could not be saved.", "error");
      return;
    }
    finish("Rule saved.", "success", true);
  }

  function finish(message, tone, clear = false) {
    removeCaptureListeners();
    recording = false;
    paused = false;
    if (clear) clearSession();
    else if (session) {
      session.active = false;
      persistSession();
    }
    window.EazyFillRecorderPanel?.setBusy(true);
    window.EazyFillRecorderPanel?.setStatus(message, tone);
    clearTimeout(finishTimer);
    finishTimer = setTimeout(() => {
      if (clear) session = null;
      window.EazyFillRecorderPanel?.hide();
      window.EazyFillRecorderPanel?.setBusy(false);
    }, 900);
  }

  function discard() {
    finish("Recording discarded.", "warning", true);
    return { ok: true };
  }

  function showPanel() {
    window.EazyFillRecorderPanel?.show({
      session,
      callbacks: {
        onSave: saveRule,
        onDiscard: discard,
        onClear: clearSteps,
        onRemove: removeStep,
        onUpdate: applyPanelUpdate,
        onPause: () => {
          paused = !paused;
          if (session) {
            session.paused = paused;
            session.lastDebug = paused ? "Recording paused." : "Recording resumed.";
            persistSession();
          }
          return paused;
        }
      }
    });
  }

  function start() {
    if (window.EazyFillExcludedHosts?.isExcludedHost()) return { ok: false, error: "This site is excluded" };
    clearTimeout(finishTimer);
    session = normalizeSession(restoreSession() || session || defaultSession());
    recording = true;
    paused = !!session.paused;
    installCaptureListeners();
    showPanel();
    render();
    return { ok: true, restored: !!session.steps.length, steps: session.steps.length };
  }

  function stop() {
    finish("Recording stopped.", "warning", false);
    return { ok: true };
  }

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message?.type === "TOGGLE_RECORD") {
      sendResponse(message.state === false || recording ? stop() : start());
      return false;
    }
    if (message?.type === "START_RECORDING") {
      sendResponse(start());
      return false;
    }
    return false;
  });

  const restored = restoreSession();
  if (restored?.active) {
    session = restored;
    recording = true;
    paused = !!session.paused;
    installCaptureListeners();
    showPanel();
    render();
  }

  window.EazyFillRecorderEngine = {
    start,
    stop
  };
})();
