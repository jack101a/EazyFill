(function () {
  "use strict";

  if (window.EazyFillCaptchaDetector) return;

  let configCache = null;
  let observer = null;
  let solving = false;
  let scanTimer = null;
  const solvedMap = new Map();
  const SOLVED_MAP_LIMIT = 1000;
  const IMAGE_READY_TIMEOUT_MS = 2000;
  const SCAN_DEBOUNCE_MS = 250;

  function currentDomain() {
    return String(location.hostname || "").replace(/^www\./, "").toLowerCase();
  }

  function sendMessage(message) {
    return new Promise((resolve) => {
      try {
        const maybePromise = chrome.runtime.sendMessage(message);
        if (maybePromise && typeof maybePromise.then === "function") {
          maybePromise
            .then((response) => resolve(response || { ok: false, error: "No response" }))
            .catch((error) => resolve({ ok: false, error: error?.message || String(error) }));
          return;
        }
      } catch (_) {
        // Older Chromium builds require the callback form below.
      }

      chrome.runtime.sendMessage(message, (response) => {
        if (chrome.runtime.lastError) {
          resolve({ ok: false, error: chrome.runtime.lastError.message });
          return;
        }
        resolve(response || { ok: false, error: "No response" });
      });
    });
  }

  function normalizeSiteConfig(raw) {
    const domain = currentDomain();
    if (!raw) return null;
    if (Array.isArray(raw)) {
      return raw.find((item) => item?.domain === domain || item?.host === domain) || null;
    }
    return raw[domain] || raw[`www.${domain}`] || null;
  }

  function routeCandidates(site) {
    if (!site || typeof site !== "object") return [];
    if (site.routes && typeof site.routes === "object") {
      return Object.values(site.routes).filter((item) => item && typeof item === "object");
    }
    return [site];
  }

  function activeProfileId(settings = {}) {
    return String(settings.activeProfileId || "default").trim() || "default";
  }

  function routeProfileIds(route = {}) {
    const ids = Array.isArray(route.profileIds)
      ? route.profileIds
      : Array.isArray(route.profile_ids)
        ? route.profile_ids
        : [route.profileId || route.profile_id || "default"];
    return [...new Set(ids.map((id) => String(id || "default").trim() || "default"))];
  }

  function routeMatchesProfile(route, settings = {}) {
    return routeProfileIds(route).includes(activeProfileId(settings));
  }

  function routeStatus(route) {
    return String(route?.routeStatus || route?.status || "").toLowerCase();
  }

  function isApprovedRoute(route) {
    const status = routeStatus(route);
    return !status || status === "approved";
  }

  function updateSolvedMap(key, value) {
    if (!key) return;
    if (solvedMap.has(key)) {
      solvedMap.delete(key);
    } else if (solvedMap.size >= SOLVED_MAP_LIMIT) {
      const firstKey = solvedMap.keys().next().value;
      solvedMap.delete(firstKey);
    }
    solvedMap.set(key, value);
  }

  function selectRouteForPage(site, { requireApproved = false, requireAutoSolve = false, settings = {} } = {}) {
    const candidates = routeCandidates(site);
    const visible = candidates.filter((route) => {
      if (!routeMatchesProfile(route, settings)) return false;
      const sourceSelector = route.sourceSelector || route.source || route.source_selector;
      if (!sourceSelector || !findBySelector(sourceSelector).length) return false;
      if (requireApproved && !isApprovedRoute(route)) return false;
      if (requireAutoSolve && !(route.autoSolve === true || route.auto_solve === true)) return false;
      return true;
    });
    if (!visible.length) return null;
    return visible.find((route) => route.fieldName === site.activeFieldName || route.field_name === site.activeFieldName) || visible[0];
  }

  async function refreshRouteStatus(route) {
    const sourceSelector = route.sourceSelector || route.source || route.source_selector;
    const targetSelector = route.targetSelector || route.target || route.target_selector;
    if (!sourceSelector || !targetSelector) return route;
    const response = await sendMessage({
      type: "CAPTCHA_ROUTE_STATUS",
      payload: {
        domain: currentDomain(),
        source_selector: sourceSelector,
        target_selector: targetSelector
      }
    });
    if (!response.ok || response.status !== "approved") return route;
    return {
      ...route,
      fieldName: response.field_name || route.fieldName || route.field_name,
      routeStatus: "approved",
      autoSolve: true
    };
  }

  async function loadConfig() {
    const response = await sendMessage({
      type: "GET_EXTENSION_STORAGE",
      keys: ["fp_settings", "fp_captcha_selectors"]
    });
    const data = response.ok ? response.data || {} : {};
    const settings = data.fp_settings || {};
    const site = normalizeSiteConfig(data.fp_captcha_selectors);
    configCache = {
      enabled: settings.extensionEnabled !== false && settings.captchaEnabled !== false,
      site,
      settings,
      behavior: {
        fillDelayMs: settings.captchaFillDelayMs !== undefined
          ? settings.captchaFillDelayMs
          : site?.fillDelayMs ?? site?.delayMs ?? site?.fill_delay_ms ?? 200,
        humanTyping: settings.captchaHumanTyping !== undefined
          ? settings.captchaHumanTyping === true
          : site?.humanTyping !== undefined
            ? site.humanTyping === true
            : site?.human_typing !== undefined
              ? site.human_typing === true
              : true
      }
    };
    return configCache;
  }

  function findBySelector(selector) {
    if (!selector) return [];
    const builder = window.EazyFillSelectorBuilder;
    if (builder?.findBySelector) return builder.findBySelector(selector);
    try {
      return Array.from(document.querySelectorAll(typeof selector === "string" ? selector : selector.primary));
    } catch (_) {
      return [];
    }
  }

  function isVisible(element) {
    if (!element || !(element instanceof Element)) return false;
    const style = window.getComputedStyle(element);
    if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) return false;
    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  async function waitForImageReady(image, timeoutMs = IMAGE_READY_TIMEOUT_MS) {
    if (!(image instanceof HTMLImageElement)) return true;
    const ready = () => image.complete
      && (image.naturalWidth || image.width || image.clientWidth) > 0
      && (image.naturalHeight || image.height || image.clientHeight) > 0;
    if (ready()) return true;
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
      await new Promise((resolve) => setTimeout(resolve, 50));
      if (ready()) return true;
    }
    return ready();
  }

  function canvasToBase64(canvas) {
    try {
      return canvas.toDataURL("image/png").split(",")[1] || "";
    } catch (_) {
      return "";
    }
  }

  async function imageToBase64(image) {
    if (image instanceof HTMLCanvasElement) {
      return canvasToBase64(image);
    }

    if (image instanceof HTMLImageElement) {
      if (!(await waitForImageReady(image))) return "";
      const width = image.naturalWidth || image.width || image.clientWidth || 0;
      const height = image.naturalHeight || image.height || image.clientHeight || 0;
      if (!width || !height) return "";
      try {
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        const context = canvas.getContext("2d");
        if (!context) return "";
        context.drawImage(image, 0, 0, width, height);
        return canvasToBase64(canvas);
      } catch (_) {
        return "";
      }
    }

    return "";
  }

  async function extractPayload(sourceElement) {
    if (!sourceElement) return null;
    const payloadBase64 = await imageToBase64(sourceElement);
    return {
      type: "image",
      payloadBase64,
      metadata: {
        width: sourceElement.naturalWidth || sourceElement.width || sourceElement.clientWidth || 0,
        height: sourceElement.naturalHeight || sourceElement.height || sourceElement.clientHeight || 0,
        captureMethod: sourceElement instanceof HTMLCanvasElement ? "canvas" : "rendered-canvas",
        payloadPrefix: payloadBase64 ? payloadBase64.slice(0, 80) : ""
      }
    };
  }

  async function solve(config = configCache?.site) {
    if (solving) return { ok: false, error: "CAPTCHA solve already in progress" };
    if (!config) return { ok: false, error: "No CAPTCHA selectors configured for this site" };
    config = selectRouteForPage(config, { requireApproved: false, settings: configCache?.settings || {} }) || config;
    if (!isApprovedRoute(config)) {
      config = await refreshRouteStatus(config);
      if (!isApprovedRoute(config)) {
        return { ok: false, error: "CAPTCHA route is pending server approval" };
      }
    }
    const sourceSelector = config.sourceSelector || config.source || config.source_selector;
    const targetSelector = config.targetSelector || config.target || config.target_selector;
    const source = findBySelector(sourceSelector).find(isVisible) || findBySelector(sourceSelector)[0];
    if (!source) return { ok: false, error: "CAPTCHA source not found" };
    const target = findBySelector(targetSelector).find((element) => element instanceof HTMLElement) || null;
    if (!target) return { ok: false, error: "CAPTCHA target not found" };

    solving = true;
    try {
      const payload = await extractPayload(source);
      if (!payload?.payloadBase64) {
        return { ok: false, error: "Could not extract CAPTCHA payload" };
      }
      const routeKey = [
        currentDomain(),
        config.fieldName || config.field_name || config.id || "",
        sourceSelector,
        targetSelector
      ].join("|");
      const imageKey = payload.payloadBase64.slice(0, 120);
      const cached = solvedMap.get(routeKey);
      if (cached?.imageKey === imageKey) {
        const cachedText = String(cached.result || "").trim();
        const targetValue = String(target.value || target.textContent || "").trim();
        if (cachedText && targetValue !== cachedText) {
          const behavior = configCache?.behavior || {};
          const filled = await window.EazyFillCaptchaFiller?.fillResult(targetSelector, cachedText, {
            fillDelayMs: behavior.fillDelayMs ?? 0,
            humanTyping: behavior.humanTyping === true
          });
          return { ok: true, result: cachedText, cached: true, filled };
        }
        return { ok: true, result: cachedText, cached: true, skipped: "same_image" };
      }
      const response = await sendMessage({
        type: "CAPTCHA_SOLVE_REQUEST",
        domain: currentDomain(),
        selectorId: config.id || config.fieldName || config.field_name || currentDomain(),
        fieldName: config.fieldName || config.field_name || config.id || "",
        sourceSelector,
        targetSelector,
        payloadType: payload.type,
        payloadBase64: payload.payloadBase64 || "",
        metadata: {
          ...(payload.metadata || {}),
          configId: config.id || "",
          fieldName: config.fieldName || config.field_name || config.id || "",
          sourceSelector,
          targetSelector
        }
      });
      if (!response.ok) return response;
      const result = String(response.result || response.data?.result || "").trim();
      if (!result) return { ...response, ok: false, error: "CAPTCHA solve returned an empty result" };
      updateSolvedMap(routeKey, { imageKey, result, updatedAt: Date.now() });
      const behavior = configCache?.behavior || {};
      const filled = await window.EazyFillCaptchaFiller?.fillResult(targetSelector, result, {
        fillDelayMs: behavior.fillDelayMs ?? 0,
        humanTyping: behavior.humanTyping === true
      });
      return { ...response, filled };
    } finally {
      solving = false;
    }
  }

  async function scanAndMaybeSolve() {
    const config = configCache || await loadConfig();
    if (!config.enabled || !config.site) return;
    const route = selectRouteForPage(config.site, { requireApproved: true, requireAutoSolve: true, settings: config.settings || {} });
    if (route) solve(route).catch(() => {});
  }

  function scheduleScan() {
    if (scanTimer) clearTimeout(scanTimer);
    scanTimer = setTimeout(() => {
      scanTimer = null;
      scanAndMaybeSolve();
    }, SCAN_DEBOUNCE_MS);
  }

  function startObserver() {
    if (observer) return;
    observer = new MutationObserver(scheduleScan);
    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["src", "style", "class"]
    });
  }

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message?.type === "CAPTCHA_SOLVE_NOW") {
      loadConfig()
        .then(() => solve(message.config || configCache?.site))
        .then(sendResponse)
        .catch((error) => sendResponse({ ok: false, error: error.message }));
      return true;
    }
    if (message?.type === "CAPTCHA_CAPTURE_ROUTE_SAMPLE") {
      Promise.resolve()
        .then(async () => {
          const sourceSelector = message.sourceSelector || message.source_selector || "";
          const targetSelector = message.targetSelector || message.target_selector || "";
          const source = findBySelector(sourceSelector)[0];
          const target = findBySelector(targetSelector)[0];
          if (!source) return { ok: false, error: "CAPTCHA source not found" };
          const payload = await extractPayload(source);
          if (!payload?.payloadBase64) return { ok: false, error: "Could not capture CAPTCHA image" };
          const userLabel = target && "value" in target ? String(target.value || "").trim() : "";
          return {
            ok: true,
            payloadBase64: payload.payloadBase64,
            userLabel,
            metadata: payload.metadata || {}
          };
        })
        .then(sendResponse)
        .catch((error) => sendResponse({ ok: false, error: error.message }));
      return true;
    }
    if (message?.type === "CAPTCHA_CONFIG_UPDATED") {
      configCache = null;
      solvedMap.clear();
      loadConfig().then(() => scanAndMaybeSolve());
      return false;
    }
    return false;
  });

  async function init() {
    if (!/^https?:$/i.test(location.protocol)) return;
    if (window.EazyFillExcludedHosts?.isExcludedHost()) return;
    await loadConfig();
    await scanAndMaybeSolve();
    startObserver();
  }

  window.EazyFillCaptchaDetector = {
    loadConfig,
    scanAndMaybeSolve,
    solve
  };

  init().catch((error) => console.debug("[EazyFill CAPTCHA] init failed:", error));
})();
