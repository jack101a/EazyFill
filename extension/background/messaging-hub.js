import { getExtensionStorage, setExtensionStorage } from "./protected-storage.js";
import { getUserscriptRuntimeStatus, handleGMCall, parseUserscript, registerStoredUserscripts } from "./userscript-manager.js";

const asyncHandlers = new Map();

const UI_STORAGE_KEYS = new Set([
  "fp_auth",
  "fp_settings",
  "fp_credits",
  "fp_rules",
  "fp_scripts",
  "fp_profiles",
  "fp_captcha_selectors",
  "fp_popup_captcha_route_draft",
  "fp_sync_meta",
  "fp_last_selector_pick"
]);

const CONTENT_STORAGE_READ_KEYS = new Set([
  "fp_settings",
  "fp_rules",
  "fp_profiles",
  "fp_captcha_selectors"
]);

const CONTENT_STORAGE_WRITE_KEYS = new Set();
const ACCOUNT_STATUS_REFRESH_MS = 30 * 1000;

function ok(data = {}) {
  return { ok: true, ...data };
}

function fail(error) {
  const detail = error?.data?.detail && typeof error.data.detail === "object" ? error.data.detail : null;
  return {
    ok: false,
    error: error?.message || detail?.message || String(error || "Unknown error"),
    code: detail?.error || error?.code || "",
    status: error?.status || 0,
    detail
  };
}

function isOwnExtensionUrl(senderUrl) {
  try {
    const extensionUrl = new URL(chrome.runtime.getURL(""));
    return senderUrl.protocol === extensionUrl.protocol && senderUrl.host === extensionUrl.host;
  } catch (_) {
    return senderUrl.protocol === "chrome-extension:" && senderUrl.host === chrome.runtime.id;
  }
}

function senderKind(sender = {}) {
  if (!sender.id || sender.id !== chrome.runtime.id) return "unknown";

  try {
    const senderUrl = new URL(sender.url || "");
    const isUiPath = ["/popup", "/options"].some((root) => (
      senderUrl.pathname === root || senderUrl.pathname.startsWith(`${root}/`)
    ));
    if (isOwnExtensionUrl(senderUrl) && isUiPath) return "ui";

    if (sender.tab && (senderUrl.protocol === "http:" || senderUrl.protocol === "https:")) {
      return "content";
    }
  } catch (_) {
    return "unknown";
  }

  return "unknown";
}

function isSensitiveStorageKey(key) {
  const normalized = String(key || "").toLowerCase();
  return normalized.startsWith("us_storage:")
    || normalized.startsWith("us_require:")
    || normalized.startsWith("us_resource:")
    || normalized.startsWith("us_menu_commands:")
    || /(?:^|[_:-])(?:auth|api[_-]?key|credential|secret|token|password|passcode|payment|card|cvv|credit|device[_-]?id)(?:$|[_:-])/.test(normalized);
}

function validateStorageKeys(keys, { operation, sender } = {}) {
  if (!Array.isArray(keys) || keys.length === 0) {
    throw new Error(`${operation} requires a non-empty keys array`);
  }

  const kind = senderKind(sender);
  if (kind === "unknown") {
    throw new Error(`${operation} denied: sender is not an EazyFill popup, options page, or content script`);
  }

  const allowlist = kind === "ui"
    ? UI_STORAGE_KEYS
    : operation === "GET_EXTENSION_STORAGE"
      ? CONTENT_STORAGE_READ_KEYS
      : CONTENT_STORAGE_WRITE_KEYS;
  const seen = new Set();

  for (const key of keys) {
    if (typeof key !== "string" || !key || key !== key.trim()) {
      throw new Error(`${operation} denied: storage keys must be non-empty strings without surrounding whitespace`);
    }
    if (seen.has(key)) {
      throw new Error(`${operation} denied: duplicate storage key "${key}"`);
    }
    seen.add(key);
    if (allowlist.has(key)) continue;

    if (isSensitiveStorageKey(key)) {
      throw new Error(`${operation} denied for ${kind} caller: sensitive storage key "${key}" is not accessible`);
    }
    throw new Error(`${operation} denied for ${kind} caller: storage key "${key}" is not allowed`);
  }

  return keys;
}

function validateStorageWrite(values, sender) {
  if (!values || typeof values !== "object" || Array.isArray(values)) {
    throw new Error("SET_EXTENSION_STORAGE requires a values object");
  }
  const keys = Object.keys(values);
  validateStorageKeys(keys, { operation: "SET_EXTENSION_STORAGE", sender });
  return values;
}

async function getActiveSupportedTab() {
  const activeTabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const activeTab = activeTabs.find((item) => item?.id && /^https?:/i.test(item.url || ""));
  if (activeTab) return activeTab;
  const tabs = await chrome.tabs.query({ currentWindow: true });
  const tab = tabs.find((item) => item?.id && /^https?:/i.test(item.url || "")) || null;
  if (!tab?.id || !/^https?:/i.test(tab.url || "")) throw new Error("No supported active tab");
  return tab;
}

function sendTabMessage(tabId, message) {
  return new Promise((resolve) => {
    chrome.tabs.sendMessage(tabId, message, (response) => {
      if (chrome.runtime.lastError) {
        resolve({ ok: false, error: chrome.runtime.lastError.message });
        return;
      }
      resolve(response || { ok: true });
    });
  });
}

async function broadcastToSupportedTabs(message) {
  const tabs = await chrome.tabs.query({ url: ["http://*/*", "https://*/*"] });
  const results = await Promise.all(tabs.map((tab) => sendTabMessage(tab.id, message)));
  return results.filter((result) => result?.ok !== false).length;
}

function escapeRegex(value) {
  return String(value).replace(/[|\\{}()[\]^$+*?.]/g, "\\$&");
}

function globMatches(value, glob) {
  const pattern = `^${escapeRegex(glob || "").replace(/\\\*/g, ".*?")}$`;
  return new RegExp(pattern, "i").test(String(value || ""));
}

function matchChromePattern(url, pattern) {
  const rule = String(pattern || "").trim();
  if (!rule) return false;
  if (rule === "<all_urls>") return /^(https?|file|ftp):/i.test(url);
  const match = rule.match(/^(\*|https?|file|ftp):\/\/([^/]*)\/(.*)$/i);
  if (!match) return false;
  try {
    const parsed = new URL(url);
    const [, rawScheme, rawHost, rawPath] = match;
    const scheme = rawScheme.toLowerCase();
    const schemeOk = scheme === "*"
      ? parsed.protocol === "http:" || parsed.protocol === "https:"
      : parsed.protocol.slice(0, -1).toLowerCase() === scheme;
    if (!schemeOk) return false;
    if (scheme !== "file") {
      const host = parsed.hostname.toLowerCase();
      const ruleHost = rawHost.toLowerCase();
      if (ruleHost !== "*" && !globMatches(host, ruleHost) && !(ruleHost.startsWith("*.") && (host === ruleHost.slice(2) || host.endsWith(ruleHost.slice(1))))) {
        return false;
      }
    }
    return globMatches(parsed.pathname + parsed.search + parsed.hash, `/${rawPath || "*"}`);
  } catch (_) {
    return false;
  }
}

function includeMatches(url, pattern) {
  const rule = String(pattern || "").trim();
  if (!rule) return false;
  if (rule.length > 1 && rule.startsWith("/") && rule.endsWith("/")) {
    try {
      return new RegExp(rule.slice(1, -1), "i").test(url);
    } catch (_) {
      return false;
    }
  }
  return globMatches(url, rule);
}

function userscriptMatchesUrl(script, url) {
  if (!script || script.enabled === false || !url) return false;
  const meta = script.rawCode ? parseUserscript(script.rawCode || "") : script.parsedMeta || {};
  const matches = Array.isArray(meta.matches) ? meta.matches : [];
  const includes = Array.isArray(meta.includes) ? meta.includes : [];
  const excludes = Array.isArray(meta.exclude) ? meta.exclude : [];
  const excludeMatches = Array.isArray(meta.excludeMatches) ? meta.excludeMatches : [];
  if (excludes.some((pattern) => includeMatches(url, pattern))) return false;
  if (excludeMatches.some((pattern) => matchChromePattern(url, pattern))) return false;
  return matches.some((pattern) => matchChromePattern(url, pattern))
    || includes.some((pattern) => includeMatches(url, pattern));
}

function ruleMatchesUrl(rule, url) {
  if (!rule || rule.enabled === false || !url) return false;
  try {
    const parsed = new URL(url);
    const host = parsed.hostname.replace(/^www\./, "").toLowerCase();
    const site = normalizeAutofillSite(rule);
    const pattern = String(site.pattern || "").replace(/^https?:\/\//i, "").replace(/^www\./i, "").toLowerCase();
    if (!pattern || pattern === "*") return true;
    if (site.matchMode === "url_prefix") return url.startsWith(String(site.pattern || ""));
    if (site.matchMode === "url_pattern") return globMatches(url, String(site.pattern || "*"));
    if (site.matchMode === "regex") {
      try {
        return new RegExp(String(site.pattern || "")).test(url);
      } catch (_) {
        return false;
      }
    }
    if (site.matchMode === "fullUrl") return String(site.pattern || "") === url || globMatches(url, String(site.pattern || ""));
    if (site.matchMode === "domainPath") {
      const current = `${host}${parsed.pathname || "/"}`;
      return pattern.includes("*")
        ? globMatches(current, pattern)
        : current === pattern || current.startsWith(`${pattern.replace(/\/$/, "")}/`);
    }
    if (site.matchMode === "path") return globMatches(parsed.pathname || "/", String(site.pattern || "*"));
    const pathPattern = String(site.path || "").trim();
    const pathMatches = !pathPattern || pathPattern === "*" || globMatches(parsed.pathname || "/", pathPattern);
    return pathMatches && (host === pattern || host.endsWith(`.${pattern}`) || globMatches(host, pattern));
  } catch (_) {
    return false;
  }
}

function normalizeMatchMode(value) {
  const mode = String(value || "domain").replace(/_/g, "").toLowerCase();
  if (mode === "domainpath") return "domainPath";
  if (mode === "fullurl" || mode === "exacturl") return "fullUrl";
  if (mode === "path") return "path";
  if (mode === "urlprefix") return "url_prefix";
  if (mode === "urlpattern") return "url_pattern";
  if (mode === "regex") return "regex";
  return "domain";
}

function normalizeAutofillSite(rule = {}) {
  const site = rule.site || {};
  return {
    ...site,
    matchMode: normalizeMatchMode(site.matchMode || site.match_mode || rule.matchMode || rule.match_mode),
    pattern: site.pattern || site.domain || rule.domain || rule.host || "*",
    path: site.path || rule.path || ""
  };
}

function normalizeAutofillAction(action) {
  const raw = String(action || "set_value").toLowerCase();
  if (["text", "type", "fill", "input"].includes(raw)) return "set_value";
  if (["check", "uncheck", "checkbox", "radio", "select", "click", "wait", "set_value"].includes(raw)) return raw;
  return "set_value";
}

function firstNonEmpty(...values) {
  for (const value of values) {
    if (value !== undefined && value !== null && value !== "") return value;
  }
  return "";
}

function autofillSelectorFromStep(step = {}) {
  const direct = firstNonEmpty(
    step.selector,
    step.target,
    step.targetSelector,
    step.target_selector,
    step.selectorCss,
    step.selector_css,
    step.cssSelector,
    step.css_selector,
    step.css,
    step.primary
  );
  if (direct) return direct;
  const xpath = firstNonEmpty(step.xpath, step.x_path);
  if (xpath) return { strategy: "xpath", primary: xpath, xpath };
  const id = firstNonEmpty(step.elementId, step.element_id, step.inputId, step.input_id, step.id);
  if (id) return { strategy: "id", primary: `#${id}`, id, element_id: id };
  const name = firstNonEmpty(step.inputName, step.input_name, step.nameAttr, step.name_attr, step.selectorName, step.selector_name, step.name);
  if (name) return { strategy: "name", primary: `[name="${name}"]`, name };
  return "";
}

function autofillValueFromStep(step = {}) {
  return step.value
    ?? step.text
    ?? step.fill
    ?? step.defaultValue
    ?? step.default_value
    ?? "";
}

function normalizeAutofillStep(step = {}, index = 0) {
  const runtime = step.runtime || {};
  return {
    ...step,
    order: Number(step.order || index + 1),
    action: normalizeAutofillAction(step.action || step.type),
    fieldKey: step.fieldKey || step.field_key || step.key || step.name || "",
    selector: autofillSelectorFromStep(step),
    value: autofillValueFromStep(step),
    required: step.required !== false && runtime.required !== false,
    runtime: {
      ...runtime,
      delayMs: runtime.delayMs ?? runtime.delay_ms ?? step.delayMs ?? step.delay_ms,
      timeoutMs: runtime.timeoutMs ?? runtime.timeout_ms ?? step.timeoutMs ?? step.timeout_ms,
      verifyAfterFill: runtime.verifyAfterFill ?? runtime.verify_after_fill ?? step.verifyAfterFill ?? step.verify_after_fill
    }
  };
}

function rawAutofillSteps(rule = {}) {
  if (Array.isArray(rule.steps) && rule.steps.length) return rule.steps;
  if (Array.isArray(rule.actions) && rule.actions.length) return rule.actions;
  if (Array.isArray(rule.fields) && rule.fields.length) return rule.fields;
  return [];
}

function normalizedAutofillSteps(rule = {}) {
  const steps = rawAutofillSteps(rule);
  if (steps.length) return steps.map(normalizeAutofillStep);
  const selector = autofillSelectorFromStep(rule);
  if (!selector) return [];
  return [normalizeAutofillStep({
    order: 1,
    action: rule.action || rule.type || "set_value",
    selector,
    value: autofillValueFromStep(rule),
    fieldKey: rule.fieldKey || rule.field_key || rule.name || "",
    required: false
  })];
}

function normalizeAutofillRule(rule = {}) {
  const now = Date.now();
  const execution = rule.execution || {};
  const mode = String(rule.ruleType || rule.rule_type || execution.mode || "instant").toLowerCase() === "flow" ? "flow" : "instant";
  const steps = normalizedAutofillSteps(rule);
  return {
    ...rule,
    id: rule.id || rule.local_rule_id || (crypto.randomUUID ? crypto.randomUUID() : `rule_${now}_${Math.random().toString(36).slice(2)}`),
    schemaVersion: Number(rule.schemaVersion || rule.schema_version || 2),
    enabled: rule.enabled !== false,
    site: normalizeAutofillSite(rule),
    ruleType: mode,
    execution: {
      ...execution,
      mode,
      delayMs: execution.delayMs ?? execution.delay_ms ?? (mode === "flow" ? 150 : 100),
      waitTimeoutMs: execution.waitTimeoutMs ?? execution.wait_timeout_ms ?? (mode === "flow" ? 5000 : 3000),
      runOnce: execution.runOnce ?? execution.run_once ?? true,
      stopOnError: execution.stopOnError ?? execution.stop_on_error ?? mode === "flow"
    },
    steps,
    profileId: rule.profileId || rule.profile_id || "default",
    profileIds: Array.isArray(rule.profileIds)
      ? rule.profileIds
      : Array.isArray(rule.profile_ids)
        ? rule.profile_ids
        : [rule.profileId || rule.profile_id || "default"],
    priority: Number(rule.priority ?? 100),
    createdAt: rule.createdAt || rule.created_at || now,
    updatedAt: now
  };
}

function isExtensionEnabled(settings = {}) {
  return settings.extensionEnabled !== false;
}

function isAuthenticatedAuth(auth = {}) {
  return !!String(auth.sessionToken || auth.session_token || auth.apiKey || auth.api_key || "").trim()
    && auth.valid !== false;
}

function planFeature(plan, key, fallback = true) {
  if (!plan || typeof plan !== "object") return fallback;
  if (plan.features && Object.prototype.hasOwnProperty.call(plan.features, key)) return plan.features[key];
  if (plan.allowed_services && Object.prototype.hasOwnProperty.call(plan.allowed_services, key)) return plan.allowed_services[key];
  return fallback;
}

function featureEnabled(plan, key, fallback = false) {
  const value = planFeature(plan, key, fallback);
  return value === true || value === 1 || value === "1" || String(value).toLowerCase() === "true";
}

function hasRuntimePlanData(plan) {
  if (!plan || typeof plan !== "object") return false;
  const features = plan.features && typeof plan.features === "object" ? plan.features : {};
  const services = plan.allowed_services && typeof plan.allowed_services === "object" ? plan.allowed_services : {};
  const limits = plan.limits && typeof plan.limits === "object" ? plan.limits : {};
  return Object.keys(features).length > 0 || Object.keys(services).length > 0 || Object.keys(limits).length > 0;
}

function numericValue(...values) {
  for (const value of values) {
    if (value !== undefined && value !== null && value !== "") {
      const number = Number(value);
      if (Number.isFinite(number)) return number;
    }
  }
  return 0;
}

function planCaptchaLimit(plan = {}) {
  const limits = plan?.limits && typeof plan.limits === "object" ? plan.limits : {};
  return numericValue(limits.captcha_daily_limit, plan.captcha_daily_limit, plan.monthly_limit);
}

function creditsCaptchaLimit(credits = {}) {
  const captcha = credits?.captcha || credits || {};
  return numericValue(captcha.dailyLimit, captcha.daily_limit, captcha.captcha_daily_limit);
}

function shouldRefreshRuntimeAuth(auth = {}, credits = null, options = {}) {
  if (!isAuthenticatedAuth(auth)) return false;
  if (!hasRuntimePlanData(auth.plan)) return true;
  if (options.refreshStale) {
    const lastVerifiedAt = Number(auth.lastVerifiedAt || auth.last_verified_at || 0);
    if (!lastVerifiedAt || Date.now() - lastVerifiedAt > ACCOUNT_STATUS_REFRESH_MS) return true;
  }
  if (options.refreshCredits) {
    const expectedLimit = planCaptchaLimit(auth.plan || {});
    const currentLimit = creditsCaptchaLimit(credits || {});
    if (!credits || (expectedLimit > 0 && currentLimit <= 0)) return true;
  }
  return false;
}

async function getRuntimeStorage(keys, authManager, options = {}) {
  let data = await getExtensionStorage(keys);
  if (shouldRefreshRuntimeAuth(data.fp_auth || {}, data.fp_credits || null, options) && authManager?.refreshCachedStatus) {
    await authManager.refreshCachedStatus().catch(() => null);
    data = await getExtensionStorage(keys);
  }
  return data;
}

function planLimit(plan, key) {
  if (!plan || typeof plan !== "object") return undefined;
  const limits = plan.limits && typeof plan.limits === "object" ? plan.limits : {};
  if (Object.prototype.hasOwnProperty.call(limits, key)) return limits[key];
  if (plan.allowed_services && Object.prototype.hasOwnProperty.call(plan.allowed_services, `${key}_limit`)) {
    return plan.allowed_services[`${key}_limit`];
  }
  return undefined;
}

function numericPlanLimit(raw) {
  if (raw === undefined || raw === null || raw === "") return Infinity;
  const value = Number(raw);
  return Number.isFinite(value) ? Math.max(0, Math.floor(value)) : Infinity;
}

function allowedRuleLimit(auth = {}) {
  if (!isAuthenticatedAuth(auth)) return 0;
  const plan = auth.plan || {};
  if (!hasRuntimePlanData(plan) || !featureEnabled(plan, "autofill", false)) return 0;
  if (featureEnabled(plan, "unlimited_rules", false)) return Infinity;
  return numericPlanLimit(planLimit(plan, "rules"));
}

function allowedScriptLimit(auth = {}) {
  if (!isAuthenticatedAuth(auth)) return 0;
  const plan = auth.plan || {};
  if (!hasRuntimePlanData(plan) || !featureEnabled(plan, "userscripts", false)) return 0;
  return numericPlanLimit(planLimit(plan, "scripts"));
}

function planAllowedRules(rules, auth = {}) {
  const limit = allowedRuleLimit(auth);
  return Number.isFinite(limit) ? rules.slice(0, limit) : rules;
}

function planAllowedScripts(scripts, auth = {}) {
  const limit = allowedScriptLimit(auth);
  return Number.isFinite(limit) ? scripts.slice(0, limit) : scripts;
}

function serializedLimit(limit) {
  return Number.isFinite(limit) ? limit : null;
}

function cleanUserscriptTitle(script = {}) {
  const rawMeta = script.rawCode ? parseUserscript(script.rawCode || "") : {};
  return String(rawMeta.name || script.parsedMeta?.name || script.name || "Untitled Script")
    .replace(/^:[a-z]{2}(?:-[a-z0-9-]+)?\s+/i, "")
    .trim() || "Untitled Script";
}

function activeProfileId(settings = {}) {
  return String(settings.activeProfileId || "default").trim() || "default";
}

function itemProfileId(item = {}) {
  return itemProfileIds(item)[0] || "default";
}

function itemProfileIds(item = {}) {
  const ids = Array.isArray(item.profileIds)
    ? item.profileIds
    : Array.isArray(item.profile_ids)
      ? item.profile_ids
      : [item.profileId || item.profile_id || "default"];
  return [...new Set(ids.map((id) => String(id || "default").trim() || "default"))];
}

function itemMatchesProfile(item = {}, profileId = "default") {
  return itemProfileIds(item).includes(String(profileId || "default").trim() || "default");
}

async function assertExtensionEnabled() {
  const data = await getExtensionStorage(["fp_settings"]);
  if (!isExtensionEnabled(data.fp_settings || {})) {
    throw new Error("Extension is turned off");
  }
}

export function registerMessageHandler(type, handler) {
  asyncHandlers.set(type, handler);
}

export function registerCoreMessageHandlers({ apiClient, authManager, captchaHandler, creditManager, syncManager } = {}) {
  registerMessageHandler("GET_EXTENSION_STORAGE", async (message, sender) => {
    const keys = validateStorageKeys(message.keys, { operation: "GET_EXTENSION_STORAGE", sender });
    const data = await getExtensionStorage(keys);
    return ok({ data });
  });

  registerMessageHandler("SET_EXTENSION_STORAGE", async (message, sender) => {
    const values = validateStorageWrite(message.values, sender);
    await setExtensionStorage(values);
    return ok();
  });

  registerMessageHandler("GM_API_CALL", (message) => handleGMCall(message));

  registerMessageHandler("USERSCRIPTS_STATUS", () => getUserscriptRuntimeStatus());
  registerMessageHandler("USERSCRIPTS_REGISTER", () => registerStoredUserscripts());

  if (apiClient) {
    registerMessageHandler("BILLING_PLANS", async () => ok(await apiClient.get("/v2/plans")));
    registerMessageHandler("BILLING_HISTORY", async () => ok(await apiClient.get("/v2/billing/history")));
    registerMessageHandler("BILLING_CREATE_ORDER", async (message) => ok(await apiClient.post("/v2/billing/create-order", message.payload || {})));
    registerMessageHandler("BILLING_VERIFY_PAYMENT", async (message) => ok(await apiClient.post("/v2/billing/verify-payment", message.payload || {})));
  }

  registerMessageHandler("RECORDER_SAVE_RULE", async (message) => {
    const data = await getExtensionStorage(["fp_rules", "fp_settings"]);
    const rules = Array.isArray(data.fp_rules) ? data.fp_rules : [];
    const now = Date.now();
    const rule = normalizeAutofillRule({
      executionCount: 0,
      lastExecutedAt: null,
      ...(message.rule || {}),
      profileId: message.rule?.profileId || message.rule?.profile_id || "default",
      createdAt: message.rule?.createdAt || now
    });
    await setExtensionStorage({ fp_rules: [...rules.filter((item) => item.id !== rule.id), rule] });
    return ok({ rule });
  });

  registerMessageHandler("START_RECORDING", async () => {
    await assertExtensionEnabled();
    const tab = await getActiveSupportedTab();
    return sendTabMessage(tab.id, { type: "START_RECORDING" });
  });

  registerMessageHandler("AUTOFILL_EXECUTE_CURRENT", async (message) => {
    await assertExtensionEnabled();
    const tab = await getActiveSupportedTab();
    const response = await sendTabMessage(tab.id, {
      type: "AUTOFILL_EXECUTE_NOW",
      mode: message.mode || message.executionMode || null,
      ruleId: message.ruleId || null
    });
    if (response.ok && response.succeededSteps && creditManager?.recordAutofillExecution) {
      await creditManager.recordAutofillExecution(response.succeededSteps);
    }
    return response;
  });

  registerMessageHandler("AUTOFILL_AUTO_EXECUTED", async (message) => {
    if (message.succeededSteps && creditManager?.recordAutofillExecution) {
      await creditManager.recordAutofillExecution(message.succeededSteps);
    }
    return ok();
  });

  registerMessageHandler("SELECTOR_PICKED", async (message) => {
    const targetField = String(message.targetField || "");
    const selected = message.selector?.primary || "";
    const current = await chrome.storage.local.get(["fp_popup_captcha_route_draft"]);
    const draft = current.fp_popup_captcha_route_draft && typeof current.fp_popup_captcha_route_draft === "object"
      ? current.fp_popup_captcha_route_draft
      : {};
    const nextDraft = {
      ...draft,
      domain: message.domain || draft.domain || "",
      updatedAt: Date.now()
    };
    if (targetField === "captcha-source" || targetField === "source") {
      nextDraft.sourceSelector = selected;
      nextDraft.source = message.selector || null;
    }
    if (targetField === "captcha-target" || targetField === "target") {
      nextDraft.targetSelector = selected;
      nextDraft.target = message.selector || null;
    }
    await chrome.storage.local.set({
      fp_last_selector_pick: message,
      fp_popup_captcha_route_draft: nextDraft
    });
    return ok();
  });

  registerMessageHandler("SELECTOR_PICK_CANCELLED", async (message) => {
    await chrome.storage.local.set({ fp_last_selector_pick: { cancelled: true, targetField: message.targetField || "" } });
    return ok();
  });

  registerMessageHandler("CAPTCHA_CONFIG_UPDATED", async () => {
    const notifiedTabs = await broadcastToSupportedTabs({ type: "CAPTCHA_CONFIG_UPDATED" });
    return ok({ notifiedTabs });
  });

  registerMessageHandler("CAPTCHA_CAPTURE_ROUTE_SAMPLE", async (message) => {
    await assertExtensionEnabled();
    const tab = await getActiveSupportedTab();
    return sendTabMessage(tab.id, {
      type: "CAPTCHA_CAPTURE_ROUTE_SAMPLE",
      sourceSelector: message.sourceSelector || "",
      targetSelector: message.targetSelector || ""
    });
  });

  registerMessageHandler("GET_STATUS", async () => {
    const data = await getRuntimeStorage(["fp_auth", "fp_settings", "fp_credits", "fp_rules", "fp_scripts"], authManager, {
      refreshCredits: true,
      refreshStale: true
    });
    const auth = data.fp_auth || {};
    const authenticated = isAuthenticatedAuth(auth);
    const rules = Array.isArray(data.fp_rules) ? data.fp_rules : [];
    const scripts = Array.isArray(data.fp_scripts) ? data.fp_scripts : [];
    const settings = data.fp_settings || {};
    const activeProfile = activeProfileId(settings);
    const profileRules = rules.filter((rule) => itemMatchesProfile(rule, activeProfile));
    const profileScripts = scripts.filter((script) => itemMatchesProfile(script, activeProfile));
    const enabledRules = profileRules.filter((rule) => rule.enabled !== false);
    const enabledScripts = profileScripts.filter((script) => script.enabled !== false);
    const planRules = planAllowedRules(enabledRules, auth);
    const planScripts = planAllowedScripts(enabledScripts, auth);
    const extensionEnabled = isExtensionEnabled(settings);
    const autofillAllowed = authenticated && featureEnabled(auth.plan || {}, "autofill", false);
    const userscriptsAllowed = authenticated && featureEnabled(auth.plan || {}, "userscripts", false);
    const autofillEnabled = extensionEnabled && autofillAllowed && settings.autofillEnabled !== false;
    const userscriptsEnabled = extensionEnabled && userscriptsAllowed && settings.userscriptsEnabled !== false;
    const activeTab = await getActiveSupportedTab().catch(() => null);
    const activeUrl = activeTab?.url || "";
    const currentPageScripts = activeUrl && userscriptsEnabled
      ? planScripts.filter((script) => userscriptMatchesUrl({ ...script, enabled: true }, activeUrl))
      : [];
    return ok({
      status: {
        authenticated,
        plan: auth.plan || null,
        credits: data.fp_credits || null,
        settings,
        activeTab: activeUrl ? {
          url: activeUrl,
          hostname: new URL(activeUrl).hostname
        } : null,
        runtime: {
          extensionEnabled,
          autofillAllowed,
          userscriptsAllowed,
          authRequired: !authenticated
        },
        counts: {
          rules: profileRules.length,
          enabledRules: enabledRules.length,
          activeRules: autofillEnabled ? planRules.length : 0,
          limitedRules: Math.max(0, enabledRules.length - planRules.length),
          matchingRules: activeUrl && autofillEnabled ? planRules.filter((rule) => ruleMatchesUrl(rule, activeUrl)).length : null,
          scripts: profileScripts.length,
          enabledScripts: enabledScripts.length,
          activeScripts: userscriptsEnabled ? planScripts.length : 0,
          limitedScripts: Math.max(0, enabledScripts.length - planScripts.length),
          matchingScripts: activeUrl && userscriptsEnabled ? currentPageScripts.filter((script) => script.enabled !== false).length : null
        },
        runningScripts: currentPageScripts.map((script) => ({
          id: String(script.id || ""),
          name: cleanUserscriptTitle(script),
          version: (script.rawCode ? parseUserscript(script.rawCode || "").version : "") || script.version || script.parsedMeta?.version || "1.0.0",
          enabled: script.enabled !== false,
          source: script.source || "local"
        })).slice(0, 8)
      }
    });
  });

  registerMessageHandler("GET_RUNTIME_PLAN_LIMITS", async () => {
    const data = await getRuntimeStorage(["fp_auth", "fp_credits"], authManager, {
      refreshCredits: true,
      refreshStale: true
    });
    const auth = data.fp_auth || {};
    const authenticated = isAuthenticatedAuth(auth);
    return ok({
      limits: {
        rules: serializedLimit(allowedRuleLimit(auth)),
        scripts: serializedLimit(allowedScriptLimit(auth))
      },
      features: {
        autofill: authenticated && featureEnabled(auth.plan || {}, "autofill", false),
        userscripts: authenticated && featureEnabled(auth.plan || {}, "userscripts", false)
      },
      authenticated
    });
  });

  if (authManager) {
    registerMessageHandler("AUTH_STATUS_CHECK", () => authManager.getAuthStatus());
    registerMessageHandler("REGISTER_ACCOUNT", (message) => authManager.registerAccount(message.payload || message));
    registerMessageHandler("VERIFY_OTP", (message) => authManager.verifyOtp(message.payload || message));
    registerMessageHandler("SAVE_API_KEY", (message) => authManager.saveApiKey(message.apiKey, message.options || {}));
    registerMessageHandler("LOGOUT", () => authManager.logout());
  }

  if (captchaHandler) {
    registerMessageHandler("CAPTCHA_SOLVE_REQUEST", async (message) => {
      await assertExtensionEnabled();
      return captchaHandler.solveRequest(message);
    });
    registerMessageHandler("CAPTCHA_SOLVE_CURRENT", async (message) => {
      await assertExtensionEnabled();
      return captchaHandler.solveCurrentTab(message);
    });
    registerMessageHandler("PICK_ELEMENT_CURRENT", (message) => captchaHandler.pickElement(message));
  }

  if (creditManager) {
    registerMessageHandler("CREDIT_CHECK", () => creditManager.getCredits());
    registerMessageHandler("CREDIT_REFRESH", () => creditManager.refreshCredits());
  }

  if (apiClient) {
    registerMessageHandler("CREDIT_HISTORY", async (message) => ok(await apiClient.get(`/v2/credits/history?limit=${encodeURIComponent(message.limit || 12)}`)));
    registerMessageHandler("CAPTCHA_ROUTE_PROPOSE", async (message) => ok(await apiClient.post("/v2/captcha/routes/propose", message.payload || {})));
    registerMessageHandler("CAPTCHA_ROUTE_STATUS", async (message) => {
      const payload = message.payload || {};
      const params = new URLSearchParams({
        domain: payload.domain || "",
        source_selector: payload.source_selector || payload.sourceSelector || "",
        target_selector: payload.target_selector || payload.targetSelector || ""
      });
      return ok(await apiClient.get(`/v2/captcha/routes/status?${params.toString()}`));
    });
  }

  if (syncManager) {
    registerMessageHandler("SYNC_STATUS", () => syncManager.status());
    registerMessageHandler("SYNC_PUSH", () => syncManager.push());
    registerMessageHandler("SYNC_PULL", () => syncManager.pull());
    registerMessageHandler("SYNC_DELETE", () => syncManager.deleteCloudCopy());
  }
}

export function installMessageHub() {
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    const type = message?.type;
    const handler = asyncHandlers.get(type);
    if (!handler) return false;

    Promise.resolve()
      .then(() => handler(message, sender))
      .then((response) => sendResponse(response ?? ok()))
      .catch((error) => sendResponse(fail(error)));
    return true;
  });
}
