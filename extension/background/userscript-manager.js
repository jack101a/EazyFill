import { getProtectedValues, setProtectedValues } from "./protected-storage.js";

const gmXhrControllers = new Map();
const REGISTERED_PREFIX = "eazyfill:";
const USER_SCRIPT_MESSAGE = "EAZYFILL_USER_SCRIPT_CALL";
const BRIDGE_INIT_ACTION = "bridgeInit";
const CAPABILITY_STORAGE_KEY = "eazyfill_userscript_capabilities_v1";
const registeredScriptCapabilities = new Map();
const documentCapabilities = new Map();
const HIGH_RISK_HOSTS = [
  "paypal.com",
  "stripe.com",
  "razorpay.com",
  "paytm.com",
  "phonepe.com",
  "hdfcbank.com",
  "icicibank.com",
  "axisbank.com",
  "kotak.com",
  "sbi.co.in",
  "onlinesbi.sbi"
];
const HIGH_RISK_EXCLUDE_MATCHES = HIGH_RISK_HOSTS.flatMap((host) => [
  `*://${host}/*`,
  `*://*.${host}/*`
]);
const HIGH_RISK_EXCLUDE_GLOBS = [
  "*://*.bank.in/*",
  "*://*netbanking*/*"
];
const SUPPORTED_ACTIONS = new Set([
  "getValue",
  "setValue",
  "deleteValue",
  "listValues",
  "addValueChangeListener",
  "removeValueChangeListener",
  "xmlhttpRequest",
  "xmlhttpAbort",
  "notification",
  "openInTab",
  "download",
  "registerMenuCommand",
  "unregisterMenuCommand",
  "log"
]);

function randomCapability() {
  const bytes = new Uint8Array(32);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function isPlainObject(value) {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function isNonEmptyString(value, maxLength = 4096) {
  return typeof value === "string" && value.length > 0 && value.length <= maxLength;
}

function isHighRiskUrl(value) {
  try {
    const url = new URL(String(value || ""));
    const host = url.hostname.replace(/^www\./, "").toLowerCase();
    return host.endsWith(".bank.in")
      || host.includes("netbanking")
      || HIGH_RISK_HOSTS.some((domain) => host === domain || host.endsWith(`.${domain}`));
  } catch (_) {
    return true;
  }
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
      if (ruleHost !== "*"
        && !globMatches(host, ruleHost)
        && !(ruleHost.startsWith("*.") && (host === ruleHost.slice(2) || host.endsWith(ruleHost.slice(1))))) {
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
  const meta = script.rawCode ? parseUserscript(script.rawCode || "") : script.parsedMeta || {};
  const matches = Array.isArray(meta.matches) ? meta.matches : [];
  const includes = Array.isArray(meta.includes) ? meta.includes : [];
  const excludes = Array.isArray(meta.exclude) ? meta.exclude : [];
  const excludeMatches = Array.isArray(meta.excludeMatches) ? meta.excludeMatches : [];
  if (excludes.some((pattern) => includeMatches(url, pattern))) return false;
  if (excludeMatches.some((pattern) => matchChromePattern(url, pattern))) return false;
  if (!matches.length && !includes.length) return /^https?:/i.test(url);
  return matches.some((pattern) => matchChromePattern(url, pattern))
    || includes.some((pattern) => includeMatches(url, pattern));
}

function senderPageUrl(sender) {
  return String(sender?.url || sender?.tab?.url || "");
}

function senderDocumentKey(sender, scriptId) {
  const documentId = sender?.documentId
    || `${sender?.tab?.id ?? "no-tab"}:${sender?.frameId ?? 0}:${senderPageUrl(sender)}`;
  return `${documentId}:${scriptId}`;
}

async function getUserscriptsEnabled() {
  const data = await chrome.storage.local.get(["fp_settings"]);
  return data.fp_settings?.extensionEnabled !== false
    && data.fp_settings?.userscriptsEnabled !== false;
}

function isAuthenticatedAuth(auth = {}) {
  return !!String(auth.sessionToken || auth.session_token || "").trim()
    && auth.valid !== false;
}

function activeProfileId(settings = {}) {
  return String(settings.activeProfileId || "default").trim() || "default";
}

function scriptProfileIds(script = {}) {
  const ids = Array.isArray(script.profileIds)
    ? script.profileIds
    : Array.isArray(script.profile_ids)
      ? script.profile_ids
      : [script.profileId || script.profile_id || "default"];
  return [...new Set(ids.map((id) => String(id || "default").trim() || "default"))];
}

function scriptMatchesProfile(script = {}, profileId = "default") {
  return scriptProfileIds(script).includes(String(profileId || "default").trim() || "default");
}

function userscriptsAllowed(settings = {}) {
  return settings.extensionEnabled !== false && settings.userscriptsEnabled !== false;
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

function planLimit(plan, key) {
  if (!plan || typeof plan !== "object") return undefined;
  const limits = plan.limits && typeof plan.limits === "object" ? plan.limits : {};
  if (Object.prototype.hasOwnProperty.call(limits, key)) return limits[key];
  if (plan.allowed_services && Object.prototype.hasOwnProperty.call(plan.allowed_services, `${key}_limit`)) {
    return plan.allowed_services[`${key}_limit`];
  }
  return undefined;
}

function allowedScriptLimit(auth = {}) {
  if (!isAuthenticatedAuth(auth)) return 0;
  const plan = auth.plan || {};
  if (!hasRuntimePlanData(plan) || !featureEnabled(plan, "userscripts", false)) return 0;
  const raw = planLimit(plan, "scripts");
  if (raw === undefined || raw === null || raw === "") return Infinity;
  const value = Number(raw);
  return Number.isFinite(value) ? Math.max(0, Math.floor(value)) : Infinity;
}

function applyScriptPlanLimit(scripts, auth = {}) {
  const limit = allowedScriptLimit(auth);
  if (!Number.isFinite(limit)) return scripts;
  return scripts.slice(0, limit);
}

async function loadBootstrapCapabilities(scripts) {
  const ids = new Set(scripts.map((script) => String(script.id)));
  let stored = {};
  if (chrome.storage.session?.get) {
    const data = await chrome.storage.session.get([CAPABILITY_STORAGE_KEY]);
    stored = isPlainObject(data[CAPABILITY_STORAGE_KEY]) ? data[CAPABILITY_STORAGE_KEY] : {};
  }
  const next = {};
  for (const id of ids) next[id] = isNonEmptyString(stored[id], 128) ? stored[id] : randomCapability();
  if (chrome.storage.session?.set) {
    await chrome.storage.session.set({ [CAPABILITY_STORAGE_KEY]: next });
  }
  return next;
}

async function getRegisteredBootstrapCapability(scriptId) {
  const cached = registeredScriptCapabilities.get(scriptId);
  if (cached) return cached;
  if (!chrome.storage.session?.get || !chrome.userScripts?.getScripts) return "";

  const [sessionData, registrations] = await Promise.all([
    chrome.storage.session.get([CAPABILITY_STORAGE_KEY]),
    chrome.userScripts.getScripts({ ids: [toRegisteredId(scriptId)] }).catch(() => [])
  ]);
  const stored = sessionData[CAPABILITY_STORAGE_KEY];
  const capability = isPlainObject(stored) ? stored[scriptId] : "";
  const isRegistered = (registrations || []).some((item) => item.id === toRegisteredId(scriptId));
  if (!isRegistered || !isNonEmptyString(capability, 128)) return "";
  registeredScriptCapabilities.set(scriptId, capability);
  return capability;
}

function userscriptSetupInfo() {
  return {
    available: !!chrome.userScripts?.register,
    registerAvailable: !!chrome.userScripts?.register,
    unregisterAvailable: !!chrome.userScripts?.unregister,
    getScriptsAvailable: !!chrome.userScripts?.getScripts,
    setupRequired: !chrome.userScripts?.register,
    instructions: [
      "Open chrome://extensions.",
      "Enable Developer mode.",
      "Open EazyFill details.",
      "Enable Allow User Scripts, then reload EazyFill."
    ],
    helpUrl: "chrome://extensions"
  };
}

export async function getUserscriptRuntimeStatus() {
  const status = userscriptSetupInfo();
  let registeredCount = 0;
  if (status.getScriptsAvailable) {
    const scripts = await chrome.userScripts.getScripts().catch(() => []);
    registeredCount = (scripts || []).filter((script) => String(script.id || "").startsWith(REGISTERED_PREFIX)).length;
  }
  return {
    ok: status.available,
    ...status,
    registeredCount
  };
}

export function parseUserscript(code) {
  const meta = {
    matches: [],
    includes: [],
    exclude: [],
    excludeMatches: [],
    requires: [],
    resources: [],
    grants: [],
    connects: [],
    tags: [],
    noframes: false,
    runAt: "document-idle",
    name: "Unnamed",
    version: "0.0",
    description: "",
    namespace: "",
    icon: "",
    author: "",
    license: "",
    homepageURL: "",
    supportURL: "",
    downloadURL: "",
    updateURL: "",
    antifeatures: []
  };
  const match = String(code || "").match(/\/\/\s*==UserScript==([\s\S]*?)\/\/\s*==\/UserScript==/);
  if (!match) return meta;

  const lines = match[1].split("\n");
  let hasDefaultName = false;
  let hasDefaultDescription = false;
  for (const line of lines) {
    const parsed = line.match(/\/\/\s*@([^\s]+)\s*(.*)/);
    if (!parsed) continue;
    const keyToken = parsed[1].trim().toLowerCase();
    const key = keyToken.split(":")[0];
    const localized = keyToken.includes(":");
    const value = parsed[2].trim();
    if (key === "match") meta.matches.push(value);
    else if (key === "include") meta.includes.push(value);
    else if (key === "exclude") meta.exclude.push(value);
    else if (key === "exclude-match") meta.excludeMatches.push(value);
    else if (key === "require") meta.requires.push(value);
    else if (key === "resource") {
      const parts = value.split(/\s+/, 2);
      if (parts.length === 2) meta.resources.push({ name: parts[0], url: parts[1] });
    } else if (key === "grant") meta.grants.push(value);
    else if (key === "connect") meta.connects.push(value);
    else if (key === "tag") meta.tags.push(...value.split(/[,;\s]+/).map((item) => item.trim()).filter(Boolean));
    else if (key === "antifeature") meta.antifeatures.push(value);
    else if (key === "noframes") meta.noframes = true;
    else if (key === "run-at") meta.runAt = value;
    else if (key === "name") {
      if (!localized || !hasDefaultName) meta.name = value || meta.name;
      if (!localized) hasDefaultName = true;
    }
    else if (key === "namespace") meta.namespace = value;
    else if (key === "version") meta.version = value;
    else if (key === "description") {
      if (!localized || !hasDefaultDescription) meta.description = value;
      if (!localized) hasDefaultDescription = true;
    }
    else if (key === "author") meta.author = value;
    else if (key === "license") meta.license = value;
    else if (key === "homepage" || key === "homepageurl" || key === "website" || key === "source") meta.homepageURL = value;
    else if (key === "supporturl") meta.supportURL = value;
    else if (key === "icon" || key === "iconurl" || key === "icon64") meta.icon = value;
    else if (key === "downloadurl") meta.downloadURL = value;
    else if (key === "updateurl") meta.updateURL = value;
  }
  return meta;
}

export async function normalizeUserscript(rawCode, overrides = {}) {
  const parsedMeta = parseUserscript(rawCode);
  const now = Date.now();
  return {
    id: overrides.id || (crypto.randomUUID ? crypto.randomUUID() : `script_${now}_${Math.random().toString(36).slice(2)}`),
    name: overrides.name || parsedMeta.name,
    version: overrides.version || parsedMeta.version,
    enabled: overrides.enabled !== false,
    source: overrides.source || "local",
    sourceUrl: overrides.sourceUrl || "",
    rawCode: String(rawCode || ""),
    parsedMeta,
    installedAt: overrides.installedAt || now,
    updatedAt: now,
    lastError: null,
    storageUsedBytes: 0
  };
}

function toRegisteredId(scriptId) {
  return `${REGISTERED_PREFIX}${String(scriptId || "").replace(/[^a-zA-Z0-9_:-]/g, "_")}`;
}

function mapRunAt(runAt) {
  if (runAt === "document-start") return "document_start";
  if (runAt === "document-end") return "document_end";
  return "document_idle";
}

function buildUserScriptCode(script, bootstrapCapability) {
  const meta = script.parsedMeta || {};
  const id = String(script.id || script.name || "unknown");
  const info = {
    script: {
      name: script.name || meta.name || id,
      namespace: meta.namespace || "",
      version: script.version || meta.version || "",
      description: meta.description || "",
      matches: meta.matches || [],
      includes: meta.includes || [],
      excludes: meta.exclude || [],
      resources: meta.resources || []
    },
    scriptHandler: "EazyFill",
    version: "1.0.0"
  };
  return `
(function(){
  "use strict";
  const __scriptId = ${JSON.stringify(id)};
  const __bootstrapCapability = ${JSON.stringify(bootstrapCapability)};
  const GM_info = ${JSON.stringify(info)};
  let __sessionCapability = "";
  async function __initializeBridge(force) {
    if (__sessionCapability && !force) return __sessionCapability;
    const response = await chrome.runtime.sendMessage({
      type: ${JSON.stringify(USER_SCRIPT_MESSAGE)},
      action: ${JSON.stringify(BRIDGE_INIT_ACTION)},
      requestId: crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2),
      scriptId: __scriptId,
      bootstrapCapability: __bootstrapCapability
    });
    if (!response || response.error || !response.capability) {
      throw new Error(response?.error || "GM bridge initialization failed");
    }
    __sessionCapability = response.capability;
    return __sessionCapability;
  }
  async function __request(action, payload, retried) {
    const capability = await __initializeBridge(false);
    const response = await chrome.runtime.sendMessage({
      type: ${JSON.stringify(USER_SCRIPT_MESSAGE)},
      action,
      requestId: crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2),
      scriptId: __scriptId,
      capability,
      ...(payload || {})
    });
    if (response?.code === "INVALID_CAPABILITY" && !retried) {
      __sessionCapability = "";
      await __initializeBridge(true);
      return __request(action, payload, true);
    }
    if (!response || response.error) throw new Error(response?.error || "GM request failed");
    return response;
  }
  const unsafeWindow = window;
  const GM = {
    info: GM_info,
    addStyle(css) {
      const style = document.createElement("style");
      style.textContent = String(css || "");
      (document.head || document.documentElement).appendChild(style);
      return style;
    },
    addElement(parent, tag, attrs) {
      let targetParent = parent;
      let targetTag = tag;
      let targetAttrs = attrs;
      if (typeof targetParent === "string") {
        targetAttrs = targetTag;
        targetTag = targetParent;
        targetParent = document.head || document.documentElement;
      }
      const element = document.createElement(String(targetTag || "div"));
      Object.entries(targetAttrs || {}).forEach(([name, value]) => {
        if (name === "textContent") element.textContent = value;
        else if (name === "innerHTML") element.innerHTML = value;
        else element.setAttribute(name, value);
      });
      (targetParent || document.head || document.documentElement).appendChild(element);
      return element;
    },
    getValue: (key, defaultValue) => __request("getValue", { key, defaultValue }).then((response) => response.value),
    setValue: (key, value) => __request("setValue", { key, value }).then((response) => response.ok),
    deleteValue: (key) => __request("deleteValue", { key }).then((response) => response.ok),
    listValues: () => __request("listValues", {}).then((response) => response.values || []),
    addValueChangeListener: (key, fn) => {
      const listenerId = crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2);
      __request("addValueChangeListener", { key, listenerId }).catch(() => {});
      return listenerId;
    },
    removeValueChangeListener: (listenerId) => __request("removeValueChangeListener", { listenerId }).then((response) => response.ok),
    xmlhttpRequest(details) {
      const xhrId = crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2);
      let aborted = false;
      const fire = (name, payload) => {
        try {
          const callback = details && details["on" + name];
          if (typeof callback === "function") callback(payload);
        } catch (error) {
          console.error("[EazyFill GM_xmlhttpRequest callback]", error);
        }
      };
      const safeDetails = {
        method: details?.method || "GET",
        url: details?.url || "",
        headers: details?.headers || {},
        data: details?.data ?? null,
        timeout: Number(details?.timeout || 0) || 0,
        responseType: details?.responseType || "",
        anonymous: !!details?.anonymous,
        xhrId
      };
      fire("loadstart", { readyState: 1, responseText: "", response: null });
      fire("readystatechange", { readyState: 1, responseText: "", response: null });
      const operation = __request("xmlhttpRequest", { details: safeDetails })
        .then((response) => {
          if (aborted || response.aborted) fire("abort", { readyState: 4, error: response.error || "aborted" });
          else if (response.timedOut) fire("timeout", { readyState: 4, error: response.error || "timeout" });
          else if (response.response) {
            fire("readystatechange", response.response);
            fire("load", response.response);
          }
          fire("loadend", response.response || { readyState: 4, error: response.error });
          return response;
        })
        .catch((error) => {
          fire(aborted ? "abort" : "error", { readyState: 4, error: error.message });
          fire("loadend", { readyState: 4, error: error.message });
          throw error;
        });
      return {
        abort() {
          aborted = true;
          __request("xmlhttpAbort", { details: { xhrId } }).catch(() => {});
        },
        then: operation.then.bind(operation),
        catch: operation.catch.bind(operation),
        finally: operation.finally.bind(operation)
      };
    },
    notification: (details) => __request("notification", { details }),
    openInTab: (url, opts) => __request("openInTab", { details: { ...(opts || {}), url } }),
    download: (details, name) => __request("download", { details: typeof details === "string" ? { url: details, name } : details }),
    registerMenuCommand: (text, callback, opts) => {
      const id = opts?.id || (crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2));
      __request("registerMenuCommand", { details: { id, text } }).catch(() => {});
      return id;
    },
    unregisterMenuCommand: (id) => __request("unregisterMenuCommand", { details: { id } }).then((response) => response.ok),
    log: (...args) => __request("log", { details: { args } }).catch(() => console.log(...args)),
    setClipboard: (text) => navigator.clipboard?.writeText
      ? navigator.clipboard.writeText(String(text || ""))
      : Promise.reject(new Error("clipboard unavailable"))
  };
  const GM_addStyle = GM.addStyle.bind(GM);
  const GM_addElement = GM.addElement.bind(GM);
  const GM_getValue = GM.getValue.bind(GM);
  const GM_setValue = GM.setValue.bind(GM);
  const GM_deleteValue = GM.deleteValue.bind(GM);
  const GM_listValues = GM.listValues.bind(GM);
  const GM_addValueChangeListener = GM.addValueChangeListener.bind(GM);
  const GM_removeValueChangeListener = GM.removeValueChangeListener.bind(GM);
  const GM_xmlhttpRequest = GM.xmlhttpRequest.bind(GM);
  const GM_notification = GM.notification.bind(GM);
  const GM_openInTab = GM.openInTab.bind(GM);
  const GM_download = GM.download.bind(GM);
  const GM_setClipboard = GM.setClipboard.bind(GM);
  const GM_registerMenuCommand = GM.registerMenuCommand.bind(GM);
  const GM_unregisterMenuCommand = GM.unregisterMenuCommand.bind(GM);
  const GM_log = GM.log.bind(GM);
${script.requiredCode || ""}
${script.rawCode || ""}
})();`;
}

export async function registerStoredUserscripts() {
  const status = await getUserscriptRuntimeStatus();
  if (!status.available) {
    return { ok: false, error: "chrome.userScripts API unavailable", ...status };
  }

  const [data, userscriptsEnabled] = await Promise.all([
    getProtectedValues(["fp_auth", "fp_scripts", "fp_settings"]),
    getUserscriptsEnabled()
  ]);
  const authenticated = isAuthenticatedAuth(data.fp_auth || {});
  const scripts = Array.isArray(data.fp_scripts) ? data.fp_scripts : [];
  const activeProfile = activeProfileId(data.fp_settings || {});
  const candidateScripts = authenticated && userscriptsEnabled
    ? scripts.filter((script) => script && script.enabled !== false && script.rawCode && scriptMatchesProfile(script, activeProfile))
    : [];
  const enabledScripts = applyScriptPlanLimit(candidateScripts, data.fp_auth || {});

  if (chrome.userScripts.getScripts && chrome.userScripts.unregister) {
    const registered = await chrome.userScripts.getScripts();
    const ids = (registered || [])
      .map((script) => script.id)
      .filter((id) => String(id || "").startsWith(REGISTERED_PREFIX));
    if (ids.length) await chrome.userScripts.unregister({ ids });
  }

  registeredScriptCapabilities.clear();
  documentCapabilities.clear();
  if (!authenticated) {
    return { ok: true, count: 0, disabled: true, authRequired: true, ...await getUserscriptRuntimeStatus() };
  }
  if (!userscriptsEnabled) {
    return { ok: true, count: 0, disabled: true, ...await getUserscriptRuntimeStatus() };
  }

  if (chrome.userScripts.configureWorld) {
    await chrome.userScripts.configureWorld({ messaging: true });
  }

  const capabilities = await loadBootstrapCapabilities(enabledScripts);
  const registrations = enabledScripts.map((script) => {
    const meta = script.rawCode ? parseUserscript(script.rawCode || "") : script.parsedMeta || {};
    return {
      id: toRegisteredId(script.id),
      matches: meta.matches?.length ? meta.matches : ["<all_urls>"],
      includeGlobs: meta.includes || [],
      excludeGlobs: [...(meta.exclude || []), ...HIGH_RISK_EXCLUDE_GLOBS],
      excludeMatches: [...(meta.excludeMatches || []), ...HIGH_RISK_EXCLUDE_MATCHES],
      js: [{ code: buildUserScriptCode({ ...script, parsedMeta: meta }, capabilities[String(script.id)]) }],
      runAt: mapRunAt(meta.runAt),
      allFrames: !meta.noframes,
      world: "USER_SCRIPT"
    };
  });

  if (registrations.length) {
    await chrome.userScripts.register(registrations);
    for (const script of enabledScripts) {
      registeredScriptCapabilities.set(String(script.id), capabilities[String(script.id)]);
    }
  }
  return { ok: true, count: registrations.length, ...await getUserscriptRuntimeStatus() };
}

function broadcastUserscriptValueChanged(scriptId, oldValue, newValue) {
  chrome.tabs?.query({}, (tabs) => {
    for (const tab of tabs || []) {
      if (!tab.id) continue;
      chrome.tabs.sendMessage(tab.id, {
        type: "USERSCRIPT_VALUE_CHANGED",
        scriptId,
        oldValue,
        newValue
      }, () => void chrome.runtime.lastError);
    }
  });
}

async function isUserscriptConnectAllowed(script, targetUrl, senderUrl) {
  try {
    const url = new URL(String(targetUrl || ""));
    if (url.protocol !== "http:" && url.protocol !== "https:") return false;
    const meta = script?.rawCode ? parseUserscript(script.rawCode || "") : script?.parsedMeta || {};
    const connects = Array.isArray(meta.connects) ? meta.connects : [];
    if (!connects.length) return false;
    if (connects.includes("*")) return true;
    return connects.some((rule) => {
      const clean = String(rule || "").trim().toLowerCase();
      if (!clean) return false;
      if (clean === "self") {
        try {
          return url.origin === new URL(senderUrl).origin;
        } catch (_) {
          return false;
        }
      }
      const hostRule = clean.replace(/^https?:\/\//, "").split("/")[0].split(":")[0];
      if (hostRule.startsWith("*.")) {
        const base = hostRule.slice(2);
        return url.hostname.toLowerCase() === base || url.hostname.toLowerCase().endsWith(`.${base}`);
      }
      return url.hostname.toLowerCase() === hostRule;
    });
  } catch (_) {
    return false;
  }
}

function validateActionMessage(message) {
  const { action, details } = message;
  if (!SUPPORTED_ACTIONS.has(action)) return "Unsupported GM action";
  if (["getValue", "setValue", "deleteValue", "addValueChangeListener"].includes(action)
    && !isNonEmptyString(message.key, 1024)) {
    return "A non-empty key is required";
  }
  if (action === "setValue" && !Object.prototype.hasOwnProperty.call(message, "value")) {
    return "A value is required";
  }
  if (action === "addValueChangeListener" && !isNonEmptyString(message.listenerId, 256)) {
    return "A listenerId is required";
  }
  if (action === "removeValueChangeListener" && !isNonEmptyString(message.listenerId, 256)) {
    return "A listenerId is required";
  }
  if (action === "xmlhttpRequest") {
    if (!isPlainObject(details) || !isNonEmptyString(details.url, 8192)) return "A request URL is required";
    try {
      const url = new URL(details.url);
      if (url.protocol !== "http:" && url.protocol !== "https:") return "Request URL must use http or https";
    } catch (_) {
      return "Request URL is invalid";
    }
    if (details.headers !== undefined && !isPlainObject(details.headers)) return "Request headers must be an object";
    if (details.method !== undefined && !/^[A-Z]+$/i.test(String(details.method))) return "Request method is invalid";
    if (details.timeout !== undefined && (!Number.isFinite(Number(details.timeout)) || Number(details.timeout) < 0)) {
      return "Request timeout is invalid";
    }
    if (details.responseType !== undefined
      && !["", "text", "json", "arraybuffer", "blob"].includes(String(details.responseType).toLowerCase())) {
      return "Request responseType is unsupported";
    }
  }
  if (action === "xmlhttpAbort" && !isNonEmptyString(details?.xhrId || message.key, 256)) {
    return "An xhrId is required";
  }
  if (["notification", "openInTab", "download", "registerMenuCommand", "unregisterMenuCommand", "log"].includes(action)
    && !isPlainObject(details) && typeof details !== "string") {
    return "Action details are required";
  }
  if (action === "openInTab" || action === "download") {
    const urlValue = typeof details === "string" ? details : details?.url;
    try {
      const url = new URL(String(urlValue || ""));
      if (url.protocol !== "http:" && url.protocol !== "https:") return "URL must use http or https";
    } catch (_) {
      return "A valid URL is required";
    }
  }
  if (action === "registerMenuCommand" && !isNonEmptyString(details?.text, 1024)) {
    return "Menu command text is required";
  }
  if (action === "unregisterMenuCommand" && !isNonEmptyString(details?.id || details?.key || message.key, 256)) {
    return "Menu command id is required";
  }
  if (action === "log" && !Array.isArray(details?.args)) return "Log args must be an array";
  return "";
}

async function authorizeGMCall(message, sender) {
  const scriptId = String(message?.scriptId || "");
  const pageUrl = senderPageUrl(sender);
  if (sender?.id !== chrome.runtime.id || !sender?.tab || !/^https?:/i.test(pageUrl)) {
    return { error: "GM calls are only accepted from an extension user-script document", code: "INVALID_SENDER" };
  }
  if (isHighRiskUrl(pageUrl)) {
    return { error: "Userscripts are disabled on this high-risk host", code: "EXCLUDED_HOST" };
  }
  if (!await getUserscriptsEnabled()) {
    return { error: "Userscripts are disabled", code: "USERSCRIPTS_DISABLED" };
  }
  const data = await getProtectedValues(["fp_scripts"]);
  const scripts = Array.isArray(data.fp_scripts) ? data.fp_scripts : [];
  const script = scripts.find((item) => String(item?.id) === scriptId);
  const bootstrapCapability = await getRegisteredBootstrapCapability(scriptId);
  const settingsData = await getProtectedValues(["fp_settings"]);
  if (!script || !scriptMatchesProfile(script, activeProfileId(settingsData.fp_settings || {})) || script.enabled === false || !script.rawCode || !bootstrapCapability) {
    return { error: "Userscript is not enabled and registered", code: "SCRIPT_NOT_REGISTERED" };
  }
  if (!userscriptMatchesUrl(script, pageUrl)) {
    return { error: "Userscript is not allowed on the sender URL", code: "URL_MISMATCH" };
  }
  const sessionKey = senderDocumentKey(sender, scriptId);
  if (message.action === BRIDGE_INIT_ACTION) {
    if (message.bootstrapCapability !== bootstrapCapability) {
      return { error: "Invalid userscript bootstrap capability", code: "INVALID_CAPABILITY" };
    }
    const capability = randomCapability();
    documentCapabilities.set(sessionKey, capability);
    return { script, pageUrl, sessionKey, capability, initializing: true };
  }
  if (message.capability !== documentCapabilities.get(sessionKey)) {
    return { error: "Invalid or expired userscript document capability", code: "INVALID_CAPABILITY" };
  }
  return { script, pageUrl, sessionKey };
}

export async function handleGMCall(message, sender) {
  const { action, key, value, defaultValue, details, requestId, scriptId } = message;
  if (!isNonEmptyString(requestId, 256) || !isNonEmptyString(scriptId, 256)) {
    return { requestId, error: "requestId and scriptId are required", code: "INVALID_REQUEST" };
  }
  const authorization = await authorizeGMCall(message, sender);
  if (authorization.error) return { requestId, error: authorization.error, code: authorization.code };
  if (authorization.initializing) {
    return { requestId, ok: true, capability: authorization.capability };
  }
  const validationError = validateActionMessage(message);
  if (validationError) return { requestId, error: validationError, code: "INVALID_REQUEST" };

  const namespace = String(scriptId);
  const storageKey = `us_storage:${namespace}`;

  if (action === "getValue") {
    const data = await getProtectedValues([storageKey]);
    const store = data[storageKey] || {};
    return { requestId, value: store[key] !== undefined ? store[key] : defaultValue };
  }

  if (action === "setValue") {
    const data = await getProtectedValues([storageKey]);
    const store = data[storageKey] || {};
    const oldStore = { ...store };
    store[key] = value;
    await setProtectedValues({ [storageKey]: store });
    broadcastUserscriptValueChanged(namespace, oldStore, store);
    return { requestId, ok: true };
  }

  if (action === "deleteValue") {
    const data = await getProtectedValues([storageKey]);
    const store = data[storageKey] || {};
    const oldStore = { ...store };
    delete store[key];
    await setProtectedValues({ [storageKey]: store });
    broadcastUserscriptValueChanged(namespace, oldStore, store);
    return { requestId, ok: true };
  }

  if (action === "listValues") {
    const data = await getProtectedValues([storageKey]);
    return { requestId, values: Object.keys(data[storageKey] || {}) };
  }

  if (action === "addValueChangeListener" || action === "removeValueChangeListener") {
    return { requestId, ok: true };
  }

  if (action === "xmlhttpRequest") {
    let xhrId = `${authorization.sessionKey}:${requestId}`;
    let timeoutId = null;
    let didTimeout = false;
    try {
      const cleanDetails = details || {};
      const allowed = await isUserscriptConnectAllowed(authorization.script, cleanDetails.url, authorization.pageUrl);
      if (!allowed) return { requestId, error: `@connect blocked: ${cleanDetails.url}` };
      xhrId = `${authorization.sessionKey}:${cleanDetails.xhrId || requestId}`;
      const controller = new AbortController();
      gmXhrControllers.set(xhrId, controller);
      if (cleanDetails.timeout && Number(cleanDetails.timeout) > 0) {
        timeoutId = setTimeout(() => {
          didTimeout = true;
          controller.abort();
        }, Number(cleanDetails.timeout));
      }
      const response = await fetch(cleanDetails.url, {
        method: cleanDetails.method || "GET",
        headers: cleanDetails.headers || {},
        body: cleanDetails.data || null,
        credentials: cleanDetails.anonymous ? "omit" : "include",
        signal: controller.signal
      });
      const responseType = String(cleanDetails.responseType || "text").toLowerCase();
      const responseText = responseType === "arraybuffer" || responseType === "blob"
        ? ""
        : await response.clone().text();
      let responseBody = responseText;
      if (responseType === "json") {
        try {
          responseBody = responseText ? JSON.parse(responseText) : null;
        } catch (_) {
          responseBody = null;
        }
      } else if (responseType === "arraybuffer") {
        const buffer = await response.arrayBuffer();
        responseBody = btoa(String.fromCharCode(...new Uint8Array(buffer)));
      } else if (responseType === "blob") {
        const blob = await response.blob();
        const buffer = await blob.arrayBuffer();
        responseBody = `data:${blob.type || "application/octet-stream"};base64,${btoa(String.fromCharCode(...new Uint8Array(buffer)))}`;
      }
      if (timeoutId) clearTimeout(timeoutId);
      gmXhrControllers.delete(xhrId);
      return {
        requestId,
        response: {
          readyState: 4,
          status: response.status,
          statusText: response.statusText,
          finalUrl: response.url,
          responseText,
          response: responseBody,
          responseType,
          responseHeaders: Array.from(response.headers.entries()).map(([header, headerValue]) => `${header}: ${headerValue}`).join("\r\n")
        }
      };
    } catch (error) {
      if (timeoutId) clearTimeout(timeoutId);
      gmXhrControllers.delete(xhrId);
      return {
        requestId,
        aborted: error?.name === "AbortError" && !didTimeout,
        timedOut: didTimeout,
        error: didTimeout ? "timeout" : (error.message || String(error))
      };
    }
  }

  if (action === "xmlhttpAbort") {
    const xhrId = `${authorization.sessionKey}:${details?.xhrId || key}`;
    const controller = gmXhrControllers.get(xhrId);
    if (controller) {
      controller.abort("abort");
      gmXhrControllers.delete(xhrId);
    }
    return { requestId, ok: true };
  }

  if (action === "notification") {
    const text = typeof details === "string" ? details : (details?.text || details?.message || "");
    const title = typeof details === "object" ? (details.title || "Userscript") : "Userscript";
    if (chrome.notifications?.create) {
      chrome.notifications.create({
        type: "basic",
        iconUrl: "icons/icon48.png",
        title,
        message: text || title
      });
      return { requestId, ok: true };
    }
    return { requestId, ok: false, error: "notifications API unavailable" };
  }

  if (action === "openInTab") {
    const url = typeof details === "string" ? details : details?.url;
    if (!url) return { requestId, error: "No URL provided" };
    return new Promise((resolve) => {
      chrome.tabs.create({ url, active: details?.active !== false }, (tab) => {
        if (chrome.runtime.lastError) resolve({ requestId, error: chrome.runtime.lastError.message });
        else resolve({ requestId, ok: true, tabId: tab?.id });
      });
    });
  }

  if (action === "download") {
    const opts = typeof details === "string" ? { url: details } : { ...(details || {}) };
    if (!opts.url) return { requestId, error: "No download URL provided" };
    if (!chrome.downloads?.download) return { requestId, error: "downloads permission is not available" };
    return new Promise((resolve) => {
      chrome.downloads.download({
        url: opts.url,
        filename: opts.name || opts.filename,
        saveAs: !!opts.saveAs
      }, (downloadId) => {
        if (chrome.runtime.lastError) resolve({ requestId, error: chrome.runtime.lastError.message });
        else resolve({ requestId, ok: true, downloadId });
      });
    });
  }

  if (action === "registerMenuCommand") {
    const menuKey = `us_menu_commands:${namespace}`;
    const data = await getProtectedValues([menuKey]);
    const commands = data[menuKey] || {};
    const id = details?.id || `${Date.now()}_${Math.random().toString(36).slice(2)}`;
    commands[id] = { id, text: String(details?.text || ""), registeredAt: Date.now() };
    await setProtectedValues({ [menuKey]: commands });
    return { requestId, ok: true, id };
  }

  if (action === "unregisterMenuCommand") {
    const menuKey = `us_menu_commands:${namespace}`;
    const data = await getProtectedValues([menuKey]);
    const commands = data[menuKey] || {};
    delete commands[details?.id || details?.key || key];
    await setProtectedValues({ [menuKey]: commands });
    return { requestId, ok: true };
  }

  if (action === "log") {
    console.log(`[EazyFill Userscript:${namespace}]`, ...(Array.isArray(details?.args) ? details.args : [details]));
    return { requestId, ok: true };
  }

  return { requestId, error: "Unknown GM action" };
}

if (chrome.runtime.onUserScriptMessage?.addListener) {
  chrome.runtime.onUserScriptMessage.addListener((message, sender, sendResponse) => {
    if (message?.type !== USER_SCRIPT_MESSAGE) return false;
    Promise.resolve(handleGMCall(message, sender))
      .then((response) => sendResponse(response))
      .catch((error) => sendResponse({
        requestId: message?.requestId,
        error: error?.message || String(error),
        code: "INTERNAL_ERROR"
      }));
    return true;
  });
}

if (chrome.storage.onChanged?.addListener) {
  chrome.storage.onChanged.addListener((changes, areaName) => {
    if (areaName !== "local" || (!changes.fp_settings && !changes.fp_auth)) return;
    const oldSettings = changes.fp_settings?.oldValue || {};
    const newSettings = changes.fp_settings?.newValue || {};
    const before = userscriptsAllowed(oldSettings);
    const after = userscriptsAllowed(newSettings);
    if (!changes.fp_auth && before === after && activeProfileId(oldSettings) === activeProfileId(newSettings)) return;
    registerStoredUserscripts().catch((error) => {
      console.debug("[EazyFill] Userscript policy refresh failed:", error?.message || error);
    });
  });
}

export const __securityTest = {
  HIGH_RISK_EXCLUDE_GLOBS,
  HIGH_RISK_EXCLUDE_MATCHES,
  isHighRiskUrl,
  isUserscriptConnectAllowed,
  userscriptMatchesUrl,
  validateActionMessage
};
