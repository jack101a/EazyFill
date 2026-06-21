(function () {
  "use strict";

  if (window.EazyFillSelectorOverlay) return;

  let active = false;
  let overlay = null;
  let banner = null;
  let tooltip = null;
  let targetField = "source";
  let lastElement = null;
  let timeoutId = null;
  let bannerRemovalId = null;

  function ensureNode(tag, className) {
    const node = document.createElement(tag);
    node.className = className;
    return node;
  }

  function selectorPreview(element) {
    const built = window.EazyFillSelectorBuilder?.buildSelector(element);
    return built?.primary || element?.tagName?.toLowerCase() || "";
  }

  function draw(element, event) {
    if (!element || element === banner || element === tooltip || element === overlay || element.closest?.(".eazyfill-selector-banner")) return;
    lastElement = element;
    if (!overlay) {
      overlay = ensureNode("div", "eazyfill-selector-highlight");
      overlay.style.cssText = [
        "position:absolute",
        "z-index:2147483647",
        "pointer-events:none",
        "box-sizing:border-box",
        "border:2px solid #f59e0b",
        "background:rgba(245,158,11,.16)",
        "border-radius:4px"
      ].join(";");
      document.documentElement.appendChild(overlay);
    }
    if (!tooltip) {
      tooltip = ensureNode("div", "eazyfill-selector-tooltip");
      tooltip.style.cssText = [
        "position:fixed",
        "z-index:2147483647",
        "max-width:280px",
        "padding:5px 7px",
        "border-radius:6px",
        "background:#181a20",
        "color:#f8fafc",
        "border:1px solid rgba(255,255,255,.16)",
        "font:600 11px/1.3 Inter,Segoe UI,system-ui,sans-serif",
        "pointer-events:none",
        "box-shadow:0 10px 26px rgba(0,0,0,.28)",
        "white-space:nowrap",
        "overflow:hidden",
        "text-overflow:ellipsis"
      ].join(";");
      document.documentElement.appendChild(tooltip);
    }

    const rect = element.getBoundingClientRect();
    overlay.style.top = `${rect.top + window.scrollY}px`;
    overlay.style.left = `${rect.left + window.scrollX}px`;
    overlay.style.width = `${Math.max(1, rect.width)}px`;
    overlay.style.height = `${Math.max(1, rect.height)}px`;
    tooltip.textContent = selectorPreview(element);
    tooltip.style.left = `${Math.min(window.innerWidth - 290, (event?.clientX || rect.left) + 12)}px`;
    tooltip.style.top = `${Math.min(window.innerHeight - 34, (event?.clientY || rect.top) + 12)}px`;
  }

  function showBanner() {
    clearTimeout(bannerRemovalId);
    if (banner) banner.remove();
    banner = ensureNode("div", "eazyfill-selector-banner");
    banner.style.cssText = [
      "position:fixed",
      "top:0",
      "left:0",
      "right:0",
      "z-index:2147483647",
      "height:36px",
      "display:flex",
      "align-items:center",
      "justify-content:center",
      "background:#181a20",
      "color:#f8fafc",
      "border-bottom:2px solid #f59e0b",
      "font:700 13px/1 Inter,Segoe UI,system-ui,sans-serif",
      "pointer-events:none",
      "box-shadow:0 8px 24px rgba(0,0,0,.24)"
    ].join(";");
    banner.textContent = `Select the ${targetField.replaceAll("-", " ")} element. Press Esc to cancel.`;
    document.documentElement.appendChild(banner);
  }

  function cleanup(keepBanner = false) {
    clearTimeout(timeoutId);
    timeoutId = null;
    document.removeEventListener("mouseover", onHover, true);
    document.removeEventListener("mousemove", onHover, true);
    document.removeEventListener("click", onClick, true);
    document.removeEventListener("keydown", onKeyDown, true);
    overlay?.remove();
    tooltip?.remove();
    overlay = null;
    tooltip = null;
    lastElement = null;
    active = false;
    if (!keepBanner) {
      banner?.remove();
      banner = null;
    }
  }

  function showOutcome(message, tone = "success") {
    cleanup(true);
    if (!banner) return;
    banner.textContent = message;
    banner.style.borderBottomColor = tone === "success" ? "#10b981" : "#f59e0b";
    bannerRemovalId = setTimeout(() => {
      banner?.remove();
      banner = null;
    }, 1000);
  }

  function cancel(reason = "cancelled") {
    if (!active) return;
    const field = targetField;
    showOutcome(reason === "timed-out" ? "Selector picker timed out." : "Selector selection cancelled.", "warning");
    chrome.runtime.sendMessage({ type: "SELECTOR_PICK_CANCELLED", targetField: field, reason }, () => void chrome.runtime.lastError);
  }

  function onHover(event) {
    if (!active) return;
    draw(event.target, event);
  }

  function onClick(event) {
    if (!active) return;
    event.preventDefault();
    event.stopPropagation();
    const element = lastElement || event.target;
    const selector = window.EazyFillSelectorBuilder?.buildSelector(element) || {
      strategy: "css",
      primary: element.id ? `#${element.id}` : element.tagName.toLowerCase(),
      fallback: "",
      confidence: 25
    };
    const field = targetField;
    showOutcome(`Selected ${selector.primary}`);
    chrome.runtime.sendMessage({
      type: "SELECTOR_PICKED",
      targetField: field,
      selector,
      url: location.href,
      domain: location.hostname
    }, () => void chrome.runtime.lastError);
  }

  function onKeyDown(event) {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      cancel();
    }
  }

  function start(options = {}) {
    if (window.EazyFillExcludedHosts?.isExcludedHost()) {
      return { ok: false, error: "This site is excluded" };
    }
    if (active) cleanup();
    active = true;
    targetField = options.targetField || "source";
    showBanner();
    document.addEventListener("mouseover", onHover, true);
    document.addEventListener("mousemove", onHover, true);
    document.addEventListener("click", onClick, true);
    document.addEventListener("keydown", onKeyDown, true);
    timeoutId = setTimeout(() => cancel("timed-out"), 30000);
    return { ok: true };
  }

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message?.type !== "PICK_ELEMENT") return false;
    sendResponse(start(message));
    return false;
  });

  window.EazyFillSelectorOverlay = {
    start,
    cancel
  };
})();
