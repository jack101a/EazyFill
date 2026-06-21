(function () {
  "use strict";

  if (window.EazyFillCaptchaFiller) return;

  const USER_IDLE_MS = 1200;
  const SAFE_FILL_WAIT_MS = 8000;
  const SAFE_FILL_POLL_MS = 150;
  let activityListenersInstalled = false;
  let internalFill = false;
  let lastTrustedActivityAt = 0;
  let compositionActive = false;

  function findTarget(selector) {
    const builder = window.EazyFillSelectorBuilder;
    if (builder?.findBySelector) {
      return builder.findBySelector(selector).find((element) => element instanceof HTMLElement) || null;
    }
    try {
      return document.querySelector(typeof selector === "string" ? selector : selector?.primary);
    } catch (_) {
      return null;
    }
  }

  function isVisible(element) {
    if (!element || !(element instanceof Element)) return false;
    const style = window.getComputedStyle(element);
    if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) return false;
    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function isEditableElement(element) {
    if (!element || !(element instanceof Element)) return false;
    const tag = String(element.tagName || "").toLowerCase();
    return tag === "input" || tag === "textarea" || tag === "select" || element.isContentEditable === true;
  }

  function markTrustedActivity(event) {
    if (internalFill || event?.isTrusted === false) return;
    lastTrustedActivityAt = Date.now();
  }

  function installActivityListeners() {
    if (activityListenersInstalled) return;
    activityListenersInstalled = true;
    document.addEventListener("keydown", markTrustedActivity, true);
    document.addEventListener("input", markTrustedActivity, true);
    document.addEventListener("pointerdown", markTrustedActivity, true);
    document.addEventListener("focusin", markTrustedActivity, true);
    document.addEventListener("compositionstart", (event) => {
      if (internalFill || event?.isTrusted === false) return;
      compositionActive = true;
      lastTrustedActivityAt = Date.now();
    }, true);
    document.addEventListener("compositionend", (event) => {
      if (internalFill || event?.isTrusted === false) return;
      compositionActive = false;
      lastTrustedActivityAt = Date.now();
    }, true);
  }

  function userIsBusyAwayFromTarget(target) {
    const active = document.activeElement;
    if (compositionActive) return true;
    if (!active || active === target || !isEditableElement(active)) return false;
    return Date.now() - lastTrustedActivityAt < USER_IDLE_MS;
  }

  function flash() {
    // Filling should stay visually silent on the page.
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, Math.max(0, Number(ms || 0))));
  }

  function clampDelay(value, fallback = 0, max = 30000) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return fallback;
    return Math.max(0, Math.min(max, Math.round(parsed)));
  }

  function setNativeValue(element, value) {
    const descriptor = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element), "value");
    if (descriptor?.set) descriptor.set.call(element, value);
    else element.value = value;
  }

  function dispatchInput(element, data = null) {
    try {
      element.dispatchEvent(new InputEvent("input", {
        bubbles: true,
        inputType: data === null ? "insertReplacementText" : "insertText",
        data
      }));
    } catch (_) {
      element.dispatchEvent(new Event("input", { bubbles: true }));
    }
  }

  function dispatchKey(element, type, key) {
    try {
      element.dispatchEvent(new KeyboardEvent(type, { bubbles: true, key }));
    } catch (_) {
      // Value and input events remain sufficient on older pages.
    }
  }

  async function typeHumanLike(element, text, options = {}) {
    const minDelay = clampDelay(options.typingMinDelayMs, 45, 1000);
    const maxDelay = Math.max(minDelay, clampDelay(options.typingMaxDelayMs, 110, 1500));
    element.focus();
    setNativeValue(element, "");
    dispatchInput(element);
    let current = "";
    for (const character of text) {
      dispatchKey(element, "keydown", character);
      current += character;
      setNativeValue(element, current);
      dispatchInput(element, character);
      dispatchKey(element, "keyup", character);
      if (current.length < text.length) {
        await sleep(minDelay + Math.floor(Math.random() * (maxDelay - minDelay + 1)));
      }
    }
    element.dispatchEvent(new Event("change", { bubbles: true }));
  }

  async function waitUntilSafeToFill(element, value) {
    const startedAt = Date.now();
    const wanted = String(value || "").trim();
    while (Date.now() - startedAt <= SAFE_FILL_WAIT_MS) {
      if (!document.contains(element) || !isVisible(element) || element.disabled || element.readOnly) {
        return { ok: false, error: "Target field unavailable" };
      }
      const current = String(element.value || element.textContent || "").trim();
      const lastAutoValue = String(element.dataset?.eazyfillCaptchaAutofillValue || "").trim();
      if (current && current !== wanted && current !== lastAutoValue) {
        return { ok: false, error: "Target field already has manual input" };
      }
      if (!userIsBusyAwayFromTarget(element)) return { ok: true };
      await sleep(SAFE_FILL_POLL_MS);
    }
    return { ok: false, error: "User is active in another field" };
  }

  async function setElementValue(element, value, options = {}) {
    const text = String(value ?? "");
    if (!text.trim()) return false;
    if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) {
      if (options.humanTyping === true) {
        internalFill = true;
        try {
          await typeHumanLike(element, text, options);
          try { element.dataset.eazyfillCaptchaAutofillValue = text; } catch (_) {}
        } finally {
          setTimeout(() => { internalFill = false; }, 0);
        }
        return true;
      }
      internalFill = true;
      try {
        setNativeValue(element, text);
        dispatchInput(element);
        element.dispatchEvent(new Event("change", { bubbles: true }));
        try { element.dataset.eazyfillCaptchaAutofillValue = text; } catch (_) {}
      } finally {
        setTimeout(() => { internalFill = false; }, 0);
      }
      return true;
    }
    internalFill = true;
    try {
      element.textContent = text;
      element.dispatchEvent(new Event("input", { bubbles: true }));
      try { element.dataset.eazyfillCaptchaAutofillValue = text; } catch (_) {}
    } finally {
      setTimeout(() => { internalFill = false; }, 0);
    }
    return true;
  }

  async function fillResult(targetSelector, result, options = {}) {
    installActivityListeners();
    const fillDelayMs = clampDelay(options.fillDelayMs ?? options.delayMs);
    if (fillDelayMs) await sleep(fillDelayMs);
    const target = findTarget(targetSelector);
    if (!target) return { ok: false, error: "Target field not found" };
    const safe = await waitUntilSafeToFill(target, result);
    if (!safe.ok) {
      return safe;
    }
    await setElementValue(target, result, options);
    return {
      ok: true,
      fillDelayMs,
      humanTyping: options.humanTyping === true
    };
  }

  window.EazyFillCaptchaFiller = {
    fillResult,
    flash,
    findTarget,
    setElementValue
  };
})();
