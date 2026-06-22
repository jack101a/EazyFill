const STORAGE_KEYS = ["fp_auth", "fp_settings", "fp_credits", "fp_rules", "fp_scripts", "fp_profiles", "fp_captcha_selectors", "fp_sync_meta"];
const DEFAULT_PROFILE_ID = "default";
const CAPTCHA_ROUTE_SUBMIT_COOLDOWN_MS = 24 * 60 * 60 * 1000;
const PANEL_ALIASES = {
  "billing-panel": "account-panel"
};
const DEFAULT_SETTINGS = {
  extensionEnabled: true,
  activeProfileId: DEFAULT_PROFILE_ID,
  captchaEnabled: true,
  captchaFillDelayMs: 200,
  captchaHumanTyping: true,
  captchaLearningConsent: true,
  autofillEnabled: true,
  userscriptsEnabled: true,
  syncEnabled: false,
  theme: "light",
  apiBaseUrl: "https://eazyfill.app"
};

const state = {
  auth: {},
  settings: { ...DEFAULT_SETTINGS },
  credits: {},
  rules: [],
  scripts: [],
  profiles: [],
  captchaSelectors: {},
  syncMeta: {},
  plans: [],
  paymentProviders: [],
  creditPacks: [],
  payments: [],
  usageHistory: [],
  userscriptStatus: {},
  pendingScriptInstall: null,
  selectedRuleId: null,
  selectedScriptId: null,
  selectedProfileId: null,
  profileDetailId: "",
  selectedCaptchaDomain: "",
  selectedCaptchaRouteId: "",
  captchaSearch: "",
  ruleSearch: "",
  ruleStatusFilter: "all",
  selectedRuleIds: new Set(),
  selectedProfileItemKeys: new Set(),
  expandedRuleIds: new Set()
};

const $ = (id) => document.getElementById(id);
const panelIdFor = (id) => PANEL_ALIASES[id] || id;
const setText = (id, text) => { const el = $(id); if (el) el.textContent = String(text); };
const setChecked = (id, checked) => { const el = $(id); if (el) el.checked = !!checked; };
const setValue = (id, value) => { const el = $(id); if (el) el.value = value; };
const setHidden = (target, hidden) => {
  const el = typeof target === "string" ? $(target) : target;
  if (el) el.classList.toggle("is-hidden", !!hidden);
};

function setInlineMessage(node, message, tone = "neutral") {
  if (!node) return;
  node.textContent = message;
  node.classList.remove("is-error", "is-success", "is-neutral");
  node.classList.add(`is-${tone}`);
}

const SVG_NS = "http://www.w3.org/2000/svg";

function appendSvgChild(svg, tagName, attrs) {
  const child = document.createElementNS(SVG_NS, tagName);
  for (const [name, value] of Object.entries(attrs)) {
    child.setAttribute(name, value);
  }
  svg.append(child);
}

function createToastIcon(type) {
  const strokeByType = {
    success: "var(--success)",
    error: "var(--danger)",
    warning: "var(--warning)",
    info: "var(--accent)"
  };
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("width", "16");
  svg.setAttribute("height", "16");
  svg.setAttribute("stroke", strokeByType[type] || strokeByType.info);
  svg.setAttribute("stroke-width", "2.5");
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");

  if (type === "success") {
    appendSvgChild(svg, "polyline", { points: "20 6 9 17 4 12" });
  } else if (type === "error") {
    appendSvgChild(svg, "circle", { cx: "12", cy: "12", r: "10" });
    appendSvgChild(svg, "line", { x1: "15", y1: "9", x2: "9", y2: "15" });
    appendSvgChild(svg, "line", { x1: "9", y1: "9", x2: "15", y2: "15" });
  } else if (type === "warning") {
    appendSvgChild(svg, "path", { d: "M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" });
    appendSvgChild(svg, "line", { x1: "12", y1: "9", x2: "12", y2: "13" });
    appendSvgChild(svg, "line", { x1: "12", y1: "17", x2: "12.01", y2: "17" });
  } else {
    appendSvgChild(svg, "circle", { cx: "12", cy: "12", r: "10" });
    appendSvgChild(svg, "line", { x1: "12", y1: "16", x2: "12", y2: "12" });
    appendSvgChild(svg, "line", { x1: "12", y1: "8", x2: "12.01", y2: "8" });
  }
  return svg;
}

let scriptEditor = null;
function initCodeMirror() {
  if (!window.CM6) return;
  const container = $("script-editor-container");
  if (!container) return;
  scriptEditor = new window.CM6.EditorView({
    state: window.CM6.EditorState.create({
      doc: "",
      extensions: [
        window.CM6.basicSetup,
        window.CM6.javascript(),
        window.CM6.oneDark,
        window.CM6.EditorView.updateListener.of((update) => {
          if (update.docChanged) renderScriptMetaPreview();
        }),
        window.CM6.keymap.of([window.CM6.indentWithTab])
      ]
    }),
    parent: container
  });
  window.scriptEditor = scriptEditor;
}

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

async function getStorage(keys = STORAGE_KEYS) {
  const response = await sendMessage({ type: "GET_EXTENSION_STORAGE", keys });
  if (!response.ok) throw new Error(response.error || "Storage read failed");
  return response.data || {};
}

async function setStorage(values) {
  const response = await sendMessage({ type: "SET_EXTENSION_STORAGE", values });
  if (!response.ok) throw new Error(response.error || "Storage save failed");
  return response;
}

function toast(message, type = "info") {
  const node = $("toast");
  if (!node) return;

  const cleanMsg = typeof message === "string" ? message : String(message);
  const toastType = ["success", "error", "warning", "info"].includes(type) ? type : "info";
  const wrapper = document.createElement("div");
  wrapper.className = `toast-rich ${toastType}`;
  const icon = document.createElement("span");
  icon.className = "toast-icon";
  icon.append(createToastIcon(toastType));
  const content = document.createElement("span");
  content.className = "toast-content";
  content.textContent = cleanMsg;
  const progress = document.createElement("div");
  progress.className = "toast-progress";
  node.replaceChildren(wrapper);
  wrapper.append(icon, content, progress);

  node.classList.add("show");
  clearTimeout(toast.timer);

  const progressEl = node.querySelector(".toast-progress");
  if (progressEl) {
    progressEl.style.transition = "width 2.6s linear";
    requestAnimationFrame(() => {
      progressEl.style.width = "0%";
    });
  }

  toast.timer = setTimeout(() => {
    node.classList.remove("show");
  }, 2600);
}

function normalizeCredits(value = {}) {
  const captcha = value.captcha || {};
  return {
    remaining: captcha.remaining ?? captcha.remainingToday ?? 0,
    used: captcha.used_today ?? captcha.usedToday ?? 0,
    limit: captcha.daily_limit ?? captcha.dailyLimit ?? 0,
    resetsAt: captcha.resets_at ?? captcha.resetsAt ?? null
  };
}

function formatDate(value) {
  if (!value) return "--";
  const date = typeof value === "number" ? new Date(value) : new Date(String(value));
  if (Number.isNaN(date.getTime())) return "--";
  return date.toLocaleString();
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function makeId(prefix) {
  return crypto.randomUUID ? crypto.randomUUID() : `${prefix}_${Date.now()}_${Math.random().toString(36).slice(2)}`;
}

function downloadBlob(filename, blob) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function readFileBytes(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(new Uint8Array(reader.result || new ArrayBuffer(0)));
    reader.onerror = () => reject(reader.error || new Error("File read failed"));
    reader.readAsArrayBuffer(file);
  });
}

function priceLabel(price = {}) {
  const amount = Number(price.amount || 0) / 100;
  const currency = price.currency || "INR";
  if (!amount) return "Free";
  return `${currency} ${amount.toFixed(2)}`;
}

function compactNumber(value) {
  const number = Number(value || 0);
  return Number.isFinite(number) ? number.toLocaleString() : String(value || 0);
}

function planFeatureLabels(plan = {}) {
  const features = plan.features && typeof plan.features === "object" ? plan.features : {};
  const limits = plan.limits && typeof plan.limits === "object" ? plan.limits : {};
  const labels = [];

  if (limits.captcha_daily_limit !== undefined) {
    labels.push(`${compactNumber(limits.captcha_daily_limit)} CAPTCHA credits per cycle`);
  }
  if (limits.max_devices !== undefined) {
    labels.push(`${compactNumber(limits.max_devices)} device${Number(limits.max_devices) === 1 ? "" : "s"}`);
  }
  if (features.autofill) labels.push("Autofill support");
  if (features.userscripts) labels.push("Userscripts support");
  if (features.cloud_sync) labels.push("Cloud sync");
  if (features.portable_pack || features.local_backup_export || features.local_backup_import) labels.push("Import / export");
  if (features.priority_solving) labels.push("Priority solving");
  if (features.unlimited_rules) labels.push("Unlimited rules");
  if (limits.rules !== undefined && limits.rules !== null) labels.push(`${compactNumber(limits.rules)} rules`);
  if (limits.scripts !== undefined && limits.scripts !== null) labels.push(`${compactNumber(limits.scripts)} scripts`);

  return labels.length ? labels : ["Backend-managed entitlements"];
}

function currentPlanCode() {
  return String(state.auth.plan?.code || state.auth.plan_code || "").toLowerCase();
}

function isAuthenticated(auth = state.auth) {
  return !!String(auth.sessionToken || auth.apiKey || "").trim() && auth.valid !== false;
}

function availablePaymentProvider(code) {
  return state.paymentProviders.find((provider) => (
    String(provider.code || "").toLowerCase() === code && provider.available !== false
  ));
}

function preferredBillingProvider(item = {}) {
  const requested = String(item.provider || item.payment_provider || item.preferred_provider || "").toLowerCase();
  if (requested && availablePaymentProvider(requested)) return requested;
  return "razorpay";
}

function billingProviderLabel(code) {
  const provider = state.paymentProviders.find((item) => String(item.code || "").toLowerCase() === code);
  return provider?.name || (code === "razorpay" ? "Razorpay" : code);
}

function openExternalBillingUrl(url) {
  const target = String(url || "").trim();
  if (!target) return false;
  try {
    if (globalThis.chrome?.tabs?.create) {
      chrome.tabs.create({ url: target });
      return true;
    }
  } catch (_) {
    // Fall through to window.open for browsers that do not expose tabs here.
  }
  try {
    return Boolean(window.open(target, "_blank", "noopener,noreferrer"));
  } catch (_) {
    return false;
  }
}

function planAllowsSync(plan) {
  if (!plan || typeof plan !== "object") return false;
  if (plan.features && Object.prototype.hasOwnProperty.call(plan.features, "cloud_sync")) {
    return plan.features.cloud_sync === true;
  }
  if (plan.allowed_services && Object.prototype.hasOwnProperty.call(plan.allowed_services, "sync")) {
    return plan.allowed_services.sync === true;
  }
  return false;
}

function planFeatureValue(plan, key) {
  if (!plan || typeof plan !== "object") return undefined;
  if (plan.features && Object.prototype.hasOwnProperty.call(plan.features, key)) return plan.features[key];
  if (plan.allowed_services && Object.prototype.hasOwnProperty.call(plan.allowed_services, key)) return plan.allowed_services[key];
  return undefined;
}

function planAllowsPortablePack(action, plan = state.auth.plan) {
  const specific = action === "import" ? "local_backup_import" : "local_backup_export";
  const specificValue = planFeatureValue(plan, specific);
  if (specificValue !== undefined) return specificValue === true;
  const portableValue = planFeatureValue(plan, "portable_pack");
  if (portableValue !== undefined) return portableValue === true;
  return false;
}

function requirePortablePackAccess(action) {
  const authenticated = isAuthenticated();
  if (!authenticated) throw new Error("Connect EazyFill before using import/export");
  if (!planAllowsPortablePack(action)) {
    throw new Error("Import/export is not enabled for this plan");
  }
}

function createEmptyCard(message) {
  const card = document.createElement("article");
  card.className = "plan-card";
  const text = document.createElement("p");
  text.className = "empty-copy";
  text.textContent = message;
  card.append(text);
  return card;
}

function normalizeArray(value) {
  return Array.isArray(value) ? value : [];
}

const PORTABLE_PACK_MAGIC = "EAZYFILL-PACK-V1\n";
const PORTABLE_PACK_TYPE = "portable-pack";
const PORTABLE_PACK_ALG = "AES-GCM-HKDF-SHA256-EAZYFILL-PACK";
const PORTABLE_PACK_KEY_MATERIAL = [
  "EazyFill",
  "portable-pack",
  "shareable-extension-format",
  "v1"
].join("\n");

function randomBytes(length) {
  const bytes = new Uint8Array(length);
  crypto.getRandomValues(bytes);
  return bytes;
}

function utf8Bytes(value) {
  return new TextEncoder().encode(String(value || ""));
}

function concatBytes(...chunks) {
  const total = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.length;
  }
  return out;
}

function startsWithBytes(bytes, prefix) {
  if (bytes.length < prefix.length) return false;
  for (let index = 0; index < prefix.length; index += 1) {
    if (bytes[index] !== prefix[index]) return false;
  }
  return true;
}

async function derivePortablePackKey(salt) {
  const material = await crypto.subtle.importKey(
    "raw",
    utf8Bytes(PORTABLE_PACK_KEY_MATERIAL),
    "HKDF",
    false,
    ["deriveKey"]
  );
  return crypto.subtle.deriveKey(
    {
      name: "HKDF",
      salt,
      info: utf8Bytes("eazyfill shareable backup v1"),
      hash: "SHA-256"
    },
    material,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"]
  );
}

function cloneJson(value, fallback) {
  try {
    return JSON.parse(JSON.stringify(value ?? fallback));
  } catch (_) {
    return fallback;
  }
}

function portablePackPayload() {
  const exportedAt = new Date().toISOString();
  return {
    v: 1,
    app: "EazyFill",
    type: PORTABLE_PACK_TYPE,
    alg: PORTABLE_PACK_ALG,
    exportedAt,
    source: {
      profileId: activeProfileId(),
      profileName: profileName(activeProfileId())
    },
    data: {
      profiles: cloneJson(state.profiles, []),
      rules: cloneJson(state.rules, []),
      scripts: cloneJson(state.scripts, []).map((script) => {
        const copy = { ...script };
        delete copy.lastError;
        delete copy.storageUsedBytes;
        return copy;
      }),
      captchaSelectors: cloneJson(state.captchaSelectors, {})
    }
  };
}

async function encryptPortablePackPayload(payload) {
  const salt = randomBytes(16);
  const iv = randomBytes(12);
  const key = await derivePortablePackKey(salt);
  const plaintext = new TextEncoder().encode(JSON.stringify(payload));
  const ciphertext = await crypto.subtle.encrypt(
    {
      name: "AES-GCM",
      iv,
      additionalData: utf8Bytes(PORTABLE_PACK_MAGIC)
    },
    key,
    plaintext
  );
  return concatBytes(utf8Bytes(PORTABLE_PACK_MAGIC), salt, iv, new Uint8Array(ciphertext));
}

async function parsePortablePack(bytes) {
  const header = utf8Bytes(PORTABLE_PACK_MAGIC);
  if (!startsWithBytes(bytes, header) || bytes.length <= header.length + 16 + 12) {
    throw new Error("Use a valid EazyFill backup file.");
  }
  const offset = header.length;
  const salt = bytes.slice(offset, offset + 16);
  const iv = bytes.slice(offset + 16, offset + 28);
  const ciphertext = bytes.slice(offset + 28);
  const key = await derivePortablePackKey(salt);
  const plaintext = await crypto.subtle.decrypt(
    {
      name: "AES-GCM",
      iv,
      additionalData: header
    },
    key,
    ciphertext
  );
  const parsed = JSON.parse(new TextDecoder().decode(plaintext));
  if (parsed?.app !== "EazyFill" || parsed?.type !== PORTABLE_PACK_TYPE || parsed?.alg !== PORTABLE_PACK_ALG) {
    throw new Error("Portable pack does not belong to EazyFill.");
  }
  const data = parsed?.data;
  if (!data || typeof data !== "object") throw new Error("Portable pack is invalid.");
  return {
    source: parsed.source && typeof parsed.source === "object" ? parsed.source : {},
    rules: normalizeArray(data.rules),
    scripts: normalizeArray(data.scripts),
    profiles: normalizeArray(data.profiles),
    captchaSelectors: data.captchaSelectors && typeof data.captchaSelectors === "object" ? data.captchaSelectors : {}
  };
}

function scriptTemplate(name, match, version = "1.0.0") {
  return `// ==UserScript==
// @name         ${name || "EazyFill Script"}
// @namespace    eazyfill.local
// @version      ${version || "1.0.0"}
// @match        ${match || "https://*/*"}
// @grant        GM_getValue
// @grant        GM_setValue
// ==/UserScript==

(function () {
  "use strict";
})();
`;
}

function parseScriptMeta(rawCode, fallbackName, fallbackMatch, fallbackVersion = "1.0.0") {
  const meta = {
    name: fallbackName || "Untitled Script",
    version: fallbackVersion || "1.0.0",
    matches: fallbackMatch ? [fallbackMatch] : ["https://*/*"],
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
    namespace: "eazyfill.local",
    description: "",
    icon: "",
    author: "",
    license: "",
    homepageURL: "",
    supportURL: "",
    downloadURL: "",
    updateURL: "",
    antifeatures: []
  };
  const block = String(rawCode || "").match(/\/\/\s*==UserScript==([\s\S]*?)\/\/\s*==\/UserScript==/);
  if (!block) return meta;

  meta.matches = [];
  let hasDefaultName = false;
  let hasDefaultDescription = false;
  for (const line of block[1].split("\n")) {
    const parsed = line.match(/\/\/\s*@([^\s]+)\s*(.*)/);
    if (!parsed) continue;
    const keyToken = parsed[1].trim().toLowerCase();
    const key = keyToken.split(":")[0];
    const localized = keyToken.includes(":");
    const value = parsed[2].trim();
    if (key === "name") {
      if (!localized || !hasDefaultName) meta.name = value || meta.name;
      if (!localized) hasDefaultName = true;
    }
    else if (key === "namespace") meta.namespace = value;
    else if (key === "version") meta.version = value || meta.version;
    else if (key === "description") {
      if (!localized || !hasDefaultDescription) meta.description = value;
      if (!localized) hasDefaultDescription = true;
    }
    else if (key === "author") meta.author = value;
    else if (key === "license") meta.license = value;
    else if (key === "homepage" || key === "homepageurl" || key === "website" || key === "source") meta.homepageURL = value;
    else if (key === "supporturl") meta.supportURL = value;
    else if (key === "match") meta.matches.push(value);
    else if (key === "include") meta.includes.push(value);
    else if (key === "exclude") meta.exclude.push(value);
    else if (key === "exclude-match") meta.excludeMatches.push(value);
    else if (key === "require") meta.requires.push(value);
    else if (key === "resource") {
      const [name, ...rest] = value.split(/\s+/);
      if (name && rest.length) meta.resources.push({ name, url: rest.join(" ") });
    } else if (key === "grant") meta.grants.push(value);
    else if (key === "connect") meta.connects.push(value);
    else if (key === "tag") meta.tags.push(...value.split(/[,;\s]+/).map((item) => item.trim()).filter(Boolean));
    else if (key === "antifeature") meta.antifeatures.push(value);
    else if (key === "noframes") meta.noframes = true;
    else if (key === "run-at") meta.runAt = value || meta.runAt;
    else if (key === "icon" || key === "iconurl" || key === "icon64") meta.icon = value;
    else if (key === "downloadurl") meta.downloadURL = value;
    else if (key === "updateurl") meta.updateURL = value;
  }
  if (!meta.matches.length && !meta.includes.length) meta.matches = [fallbackMatch || "https://*/*"];
  return meta;
}

async function stableCaptchaFieldName(domain, sourceSelector, targetSelector) {
  const raw = `${normalizeDomain(domain)}|${String(sourceSelector || "").trim()}|${String(targetSelector || "").trim()}`;
  try {
    const bytes = new TextEncoder().encode(raw);
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    const hex = Array.from(new Uint8Array(digest)).slice(0, 8).map((byte) => byte.toString(16).padStart(2, "0")).join("");
    return `captcha_${hex}`;
  } catch (_) {
    let hash = 0;
    for (let index = 0; index < raw.length; index += 1) {
      hash = ((hash << 5) - hash + raw.charCodeAt(index)) >>> 0;
    }
    return `captcha_${hash.toString(16).padStart(8, "0")}`;
  }
}

function updateTheme() {
  const isLight = state.settings.theme === "light";
  document.documentElement.dataset.theme = isLight ? "light" : "dark";
  const logo = $("brand-logo");
  if (logo) {
    logo.src = isLight ? "../brand/logo-dark.png" : "../brand/logo-light.png";
  }
  const sunIcon = document.querySelector("#theme-toggle-btn .sun-icon");
  const moonIcon = document.querySelector("#theme-toggle-btn .moon-icon");
  if (sunIcon && moonIcon) {
    sunIcon.classList.toggle("is-hidden", isLight);
    moonIcon.classList.toggle("is-hidden", !isLight);
  }
}

async function toggleTheme() {
  state.settings.theme = state.settings.theme === "light" ? "dark" : "light";
  const selectTheme = $("setting-theme");
  if (selectTheme) selectTheme.value = state.settings.theme;
  await saveSettings();
}

function renderStatus() {
  const credits = normalizeCredits(state.credits);
  const authenticated = isAuthenticated();
  const syncAvailable = authenticated && planAllowsSync(state.auth.plan);
  const syncEnabled = syncAvailable && !!state.settings.syncEnabled;
  const packExportAvailable = authenticated && planAllowsPortablePack("export");
  const packImportAvailable = authenticated && planAllowsPortablePack("import");
  setText("connection-label", authenticated ? "Connected" : "Disconnected");
  setText("plan-name", state.auth.plan?.name || state.auth.plan?.code || "--");
  setText("device-status", state.auth.device?.status || "--");
  setText("captcha-remaining", credits.remaining || 0);
  setText("captcha-used", credits.used || 0);
  setText("captcha-limit", credits.limit || 0);
  setText("captcha-reset", formatDate(credits.resetsAt));
  setText("sync-status", !authenticated ? "Disconnected" : !syncAvailable ? "Plan locked" : state.settings.syncEnabled ? "On" : "Off");
  setText("sync-last", formatDate(state.syncMeta.lastSyncAt));
  setText("sync-size", formatBytes(state.syncMeta.blobSizeBytes));
  setText("account-user", state.auth.user?.mobile || state.auth.user?.email || "--");
  setText("account-plan", state.auth.plan?.name || state.auth.plan?.code || "--");
  setText("account-device", state.auth.device?.status || "Current browser");
  setText("account-expires", formatDate(state.auth.keyInfo?.expires_at));
  setText("account-summary-status", authenticated ? "Connected" : "Sign in / Sign up");
  setText("account-summary-plan", state.auth.plan?.name || state.auth.plan?.code || "Free Tier");
  setText("account-summary-credits", `${credits.remaining || 0} / ${credits.limit || 0}`);

  // Update Overview panel elements
  setText("overview-credits-remaining", credits.remaining || 0);
  setText("overview-credits-used", `Used ${credits.used || 0} today`);

  // Update Credits Progress Bar
  const limit = credits.limit || 0;
  const remaining = credits.remaining || 0;
  const progressBar = $("overview-credits-progress");
  if (progressBar) {
    if (limit > 0) {
      const percentage = Math.max(0, Math.min(100, (remaining / limit) * 100));
      progressBar.style.width = `${percentage}%`;
      progressBar.className = "progress-bar-fill";
      if (percentage <= 20) {
        progressBar.classList.add("danger");
      } else if (percentage <= 50) {
        progressBar.classList.add("warning");
      }
    } else {
      progressBar.style.width = remaining > 0 ? "100%" : "0%";
      progressBar.className = "progress-bar-fill";
    }
  }

  setText("overview-rules-count", state.rules.length || 0);
  setText("overview-profiles-count", `Active: ${profileName(activeProfileId())}`);
  setText("overview-scripts-count", state.scripts.length || 0);
  setText("overview-account-plan", state.auth.plan?.name || state.auth.plan?.code || "Free Tier");
  setText("overview-account-user", state.auth.user?.mobile || state.auth.user?.email || "Disconnected");
  setText("overview-credits-limit", `/ ${credits.limit || 0}`);
  document.documentElement.dataset.auth = authenticated ? "connected" : "disconnected";

  for (const id of ["sync-refresh-btn", "sync-push-btn", "sync-pull-btn", "sync-delete-btn"]) {
    const button = $(id);
    if (button) button.disabled = !syncAvailable || (id !== "sync-refresh-btn" && !syncEnabled);
  }
  const exportBtn = $("backup-export-btn");
  const restoreBtn = $("backup-restore-btn");
  if (exportBtn) exportBtn.disabled = !packExportAvailable;
  if (restoreBtn) restoreBtn.disabled = !packImportAvailable;
  setText(
    "local-backup-status",
    !authenticated
      ? "Connect EazyFill to use import/export."
      : packExportAvailable || packImportAvailable
        ? "Export EazyFill data or import shared data into a new profile."
        : "Import/export is locked for this plan."
  );

  // Show/Hide Account Connected and Disconnected Views
  const connectedView = $("account-connected-view");
  const disconnectedView = $("account-disconnected-view");
  if (connectedView && disconnectedView) {
    setHidden(connectedView, !authenticated);
    setHidden(disconnectedView, authenticated);
  }
}

function renderSettings() {
  if (!state.settings.activeProfileId) state.settings.activeProfileId = DEFAULT_PROFILE_ID;
  setChecked("setting-captcha", state.settings.captchaEnabled !== false);
  setValue("captcha-fill-delay", normalizeCaptchaDelay(state.settings.captchaFillDelayMs));
  setChecked("captcha-human-typing", state.settings.captchaHumanTyping === true);
  setChecked("captcha-learning-consent", state.settings.captchaLearningConsent === true);
  setChecked("setting-autofill", state.settings.autofillEnabled !== false);
  setChecked("setting-userscripts", state.settings.userscriptsEnabled !== false);
  setChecked("setting-sync", !!state.settings.syncEnabled);
  const syncToggle = $("setting-sync");
  if (syncToggle) {
    const authenticated = isAuthenticated();
    syncToggle.disabled = !authenticated || !planAllowsSync(state.auth.plan);
  }
  setValue("setting-api-base", state.settings.apiBaseUrl || DEFAULT_SETTINGS.apiBaseUrl);
  setValue("setting-theme", state.settings.theme || DEFAULT_SETTINGS.theme);
}

function clearTable(tbody) {
  while (tbody.firstChild) tbody.removeChild(tbody.firstChild);
}

function appendEmptyRow(tbody, colspan, label) {
  const row = document.createElement("tr");
  const cell = document.createElement("td");
  cell.colSpan = colspan;
  cell.className = "empty-row";
  cell.textContent = label;
  row.append(cell);
  tbody.append(row);
}

function matchesText(value, query) {
  return String(value || "").toLowerCase().includes(query);
}

function ruleSitePattern(rule) {
  return rule?.site?.pattern || rule?.domain || rule?.urlPattern || rule?.match || "*";
}

function ruleStepCount(rule) {
  if (Array.isArray(rule?.steps)) return rule.steps.length;
  if (Array.isArray(rule?.actions)) return rule.actions.length;
  if (Array.isArray(rule?.fields)) return rule.fields.length;
  return 0;
}

function ruleStatusLabel(rule) {
  return rule?.enabled === false ? "Paused" : "Active";
}

function ruleMatchesDashboardFilter(rule) {
  if (!itemMatchesActiveProfile(rule)) return false;
  const status = state.ruleStatusFilter || "all";
  if (status === "active" && rule.enabled === false) return false;
  if (status === "paused" && rule.enabled !== false) return false;
  const query = String(state.ruleSearch || "").trim().toLowerCase();
  if (!query) return true;
  return [
    rule?.name || "Untitled Rule",
    ruleSitePattern(rule),
    rule?.profileId || rule?.profile_id || "",
    ruleStatusLabel(rule)
  ].some((value) => matchesText(value, query));
}

function filteredRules() {
  return state.rules.filter(ruleMatchesDashboardFilter);
}

function pruneSelectedRuleIds() {
  const knownIds = new Set(state.rules.map((rule) => rule.id));
  for (const id of [...state.selectedRuleIds]) {
    if (!knownIds.has(id)) state.selectedRuleIds.delete(id);
  }
}

function syncRuleBulkControls(visibleRules) {
  const visible = visibleRules || filteredRules();
  const selectedVisibleCount = visible.filter((rule) => state.selectedRuleIds.has(rule.id)).length;
  const selectedCount = state.selectedRuleIds.size;
  const selectAll = $("rule-select-all");
  if (selectAll) {
    selectAll.checked = visible.length > 0 && selectedVisibleCount === visible.length;
    selectAll.indeterminate = selectedVisibleCount > 0 && selectedVisibleCount < visible.length;
    selectAll.disabled = visible.length === 0;
  }
  for (const id of ["rule-enable-selected-btn", "rule-disable-selected-btn", "rule-delete-selected-btn"]) {
    const button = $(id);
    if (button) button.disabled = selectedCount === 0;
  }
}

function node(tag, className = "", text = "") {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== "") el.textContent = String(text);
  return el;
}

function chip(text, tone = "") {
  const el = node("span", `admin-chip ${tone}`.trim(), text);
  return el;
}

function actionButton(label, className = "icon-text-btn") {
  const button = node("button", className, label);
  button.type = "button";
  return button;
}

function profileValues(profile = {}) {
  return profile.values || profile.data || profile.fields || {};
}

function normalizedProfileId(value) {
  const id = String(value || "").trim();
  return id || DEFAULT_PROFILE_ID;
}

function activeProfileId() {
  const id = normalizedProfileId(state.settings.activeProfileId);
  if (id === DEFAULT_PROFILE_ID || state.profiles.some((profile) => String(profile.id) === id)) return id;
  return DEFAULT_PROFILE_ID;
}

function profileName(profileId) {
  const id = normalizedProfileId(profileId);
  if (id === DEFAULT_PROFILE_ID) return "Global";
  return state.profiles.find((profile) => String(profile.id) === id)?.name || id;
}

function itemProfileId(item = {}) {
  return itemProfileIds(item)[0] || DEFAULT_PROFILE_ID;
}

function itemProfileIds(item = {}) {
  const ids = Array.isArray(item.profileIds)
    ? item.profileIds
    : Array.isArray(item.profile_ids)
      ? item.profile_ids
      : [item.profileId || item.profile_id || DEFAULT_PROFILE_ID];
  return [...new Set(ids.map(normalizedProfileId))];
}

function itemMatchesProfile(item = {}, profileId = activeProfileId()) {
  return itemProfileIds(item).includes(normalizedProfileId(profileId));
}

function withItemProfile(item = {}, profileId = activeProfileId()) {
  const ids = new Set(itemProfileIds(item));
  ids.add(normalizedProfileId(profileId));
  const profileIds = [...ids];
  return {
    ...item,
    profileId: profileIds[0] || DEFAULT_PROFILE_ID,
    profileIds
  };
}

function removeItemProfile(item = {}, profileId = activeProfileId()) {
  const id = normalizedProfileId(profileId);
  let ids = itemProfileIds(item).filter((itemId) => itemId !== id);
  if (!ids.length) {
    if (id === DEFAULT_PROFILE_ID) return null;
    ids = [DEFAULT_PROFILE_ID];
  }
  return {
    ...item,
    profileId: ids[0],
    profileIds: ids
  };
}

function routeProfileIds(route = {}) {
  const ids = Array.isArray(route.profileIds)
    ? route.profileIds
    : Array.isArray(route.profile_ids)
      ? route.profile_ids
      : [route.profileId || route.profile_id || DEFAULT_PROFILE_ID];
  return [...new Set(ids.map(normalizedProfileId))];
}

function routeMatchesProfile(route, profileId = activeProfileId()) {
  return routeProfileIds(route).includes(normalizedProfileId(profileId));
}

function withRouteProfile(route = {}, profileId = activeProfileId()) {
  const existingIds = (Array.isArray(route.profileIds) || Array.isArray(route.profile_ids) || route.profileId || route.profile_id)
    ? routeProfileIds(route)
    : [];
  const ids = new Set(existingIds);
  ids.add(normalizedProfileId(profileId));
  return {
    ...route,
    profileId: normalizedProfileId(profileId),
    profileIds: [...ids]
  };
}

function removeRouteProfile(route = {}, profileId = activeProfileId()) {
  const id = normalizedProfileId(profileId);
  let ids = routeProfileIds(route).filter((item) => item !== id);
  if (!ids.length) {
    if (id === DEFAULT_PROFILE_ID) return null;
    ids = [DEFAULT_PROFILE_ID];
  }
  return {
    ...route,
    profileId: ids[0],
    profileIds: ids
  };
}

function rewriteCaptchaRoutesForDeletedProfile(selectors = {}, deletedProfileId) {
  const deleted = normalizedProfileId(deletedProfileId);
  const next = {};
  for (const [domain, config] of Object.entries(selectors || {})) {
    const routes = {};
    for (const [routeId, route] of Object.entries(captchaRouteMapForConfig(domain, config))) {
      const ids = routeProfileIds(route).map((id) => (id === deleted ? DEFAULT_PROFILE_ID : id));
      routes[routeId] = { ...route, profileId: ids[0] || DEFAULT_PROFILE_ID, profileIds: [...new Set(ids)] };
    }
    writeCaptchaDomainConfig(next, domain, routes, config.activeFieldName);
  }
  return next;
}

function itemMatchesActiveProfile(item = {}) {
  return itemMatchesProfile(item, activeProfileId());
}

function profileUsageCounts(profileId) {
  const id = normalizedProfileId(profileId);
  const captchaRoutes = Object.values(state.captchaSelectors || {}).reduce((count, config) => (
    count + captchaRowsForConfig(config?.domain || "", config).filter((route) => routeMatchesProfile(route, id)).length
  ), 0);
  return {
    rules: state.rules.filter((rule) => itemMatchesProfile(rule, id)).length,
    scripts: state.scripts.filter((script) => itemMatchesProfile(script, id)).length,
    captchaRoutes
  };
}

function profileOptionLabel(profile) {
  return profile.name || "Untitled Profile";
}

function appendProfileOptions(select, selectedValue = activeProfileId()) {
  if (!select) return;
  const selected = normalizedProfileId(selectedValue);
  select.replaceChildren();
  const defaultOption = document.createElement("option");
  defaultOption.value = DEFAULT_PROFILE_ID;
  defaultOption.textContent = "Global";
  select.append(defaultOption);
  for (const profile of state.profiles) {
    const option = document.createElement("option");
    option.value = profile.id || "";
    option.textContent = profileOptionLabel(profile);
    select.append(option);
  }
  select.value = [...select.options].some((option) => option.value === selected) ? selected : DEFAULT_PROFILE_ID;
}

function renderProfileOptions() {
  const current = activeProfileId();
  appendProfileOptions($("active-profile-id"), current);
  for (const id of ["rule-profile-id", "script-profile-id", "captcha-profile-id"]) {
    appendProfileOptions($(id), $(id)?.value || DEFAULT_PROFILE_ID);
  }
  setText("active-profile-name", profileName(current));
  const counts = profileUsageCounts(current);
  setText("active-profile-summary", `${counts.rules} rules | ${counts.scripts} scripts | ${counts.captchaRoutes} CAPTCHA routes`);
}

function isRemoteUserscript(script = {}) {
  return script.source === "remote" || !!(script.sourceUrl || script.updateUrl);
}

function ruleSteps(rule) {
  if (Array.isArray(rule?.steps)) return rule.steps;
  if (Array.isArray(rule?.actions)) return rule.actions;
  if (Array.isArray(rule?.fields)) return rule.fields;
  return [];
}

function selectorLabel(step) {
  const selector = step?.selector || {};
  const element = step?.element || {};
  return step?.label
    || step?.field_key
    || selector.label
    || selector.id
    || selector.name
    || element.placeholder
    || element.visible_text
    || selector.css
    || selector.primary
    || step?.action
    || "field";
}

function rulePurpose(rule) {
  const steps = ruleSteps(rule);
  if (!steps.length) return "No fields configured";
  const labels = steps.slice(0, 3).map((step) => {
    const action = step.action || step.type || "set";
    const label = selectorLabel(step).replace(/^#/, "").slice(0, 34);
    return `${action} ${label}`;
  });
  return `${labels.join(" -> ")}${steps.length > 3 ? ` -> +${steps.length - 3} more` : ""}`;
}

function ruleAccessSummary(rule) {
  const scope = rule?.access_scope || rule?.accessScope || "local";
  if (scope === "plan") return `Plans: ${compactListLabel(rule.plans || [], "none")}`;
  if (scope === "service") return `Services: ${compactListLabel(rule.services || [], "autofill")}`;
  if (scope === "key") return `Keys: ${compactListLabel(rule.api_key_ids || rule.apiKeyIds || [], "none")}`;
  const profile = rule?.profileId || rule?.profile_id || rule?.profile_scope || "default";
  return scope === "local" ? `Profile: ${profile}` : scope;
}

function ruleSelectorSummaries(rule, expanded = false) {
  const steps = ruleSteps(rule);
  const selected = expanded ? steps : steps.slice(0, 2);
  return selected.map((step) => {
    const selector = step?.selector || {};
    const value = selector.css || selector.primary || selector.id || selector.name || selector.xpath || "";
    const label = selector.css ? "css" : selector.id ? "id" : selector.name ? "name" : selector.xpath ? "xpath" : "selector";
    return value ? `${label}: ${value}` : selectorLabel(step);
  }).filter(Boolean);
}

function toggleRuleDetails(id) {
  if (!id) return;
  if (state.expandedRuleIds.has(id)) state.expandedRuleIds.delete(id);
  else state.expandedRuleIds.add(id);
  renderRules();
}

function renderRuleDetailsRow(tbody, rule) {
  const details = document.createElement("tr");
  details.className = "details-row";
  const spacer = document.createElement("td");
  spacer.className = "select-col";
  const cell = document.createElement("td");
  cell.colSpan = 5;
  const box = node("div", "rule-details-box");
  const title = node("div", "rule-details-title", "Fields, flow steps, and selectors");
  box.append(title);
  const steps = ruleSteps(rule);
  if (!steps.length) {
    box.append(node("p", "empty-copy", "No steps saved for this rule."));
  } else {
    const list = node("div", "rule-step-list");
    steps.forEach((step, index) => {
      const item = node("div", "rule-step-item");
      const heading = node("div", "rule-step-heading", `Step ${index + 1} · ${step.action || step.type || "set_value"}`);
      const meta = node("div", "rule-step-meta");
      meta.append(chip(selectorLabel(step), "muted"));
      for (const summary of ruleSelectorSummaries({ steps: [step] }, true)) {
        meta.append(chip(summary, "mono"));
      }
      item.append(heading, meta);
      list.append(item);
    });
    box.append(list);
  }
  cell.append(box);
  details.append(spacer, cell);
  tbody.append(details);
}

function renderRules() {
  const tbody = $("rules-table");
  if (tbody) clearTable(tbody);
  pruneSelectedRuleIds();

  const visibleRules = filteredRules();

  if (!state.rules.length || !visibleRules.length) {
    if (tbody) appendEmptyRow(tbody, 6, state.rules.length ? "No matching rules" : "No rules saved");
    syncRuleBulkControls([]);
    return;
  }

  for (const rule of visibleRules) {
    const name = rule.name || "Untitled Rule";
    const sitePattern = ruleSitePattern(rule);
    const steps = ruleStepCount(rule);
    const statusLabel = ruleStatusLabel(rule);
    if (tbody) {
      const row = document.createElement("tr");
      row.dataset.id = rule.id;
      row.classList.toggle("selected", rule.id === state.selectedRuleId);

      const selectCell = document.createElement("td");
      selectCell.className = "select-col";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.className = "row-checkbox";
      checkbox.checked = state.selectedRuleIds.has(rule.id);
      checkbox.addEventListener("click", (event) => event.stopPropagation());
      checkbox.addEventListener("change", () => {
        if (checkbox.checked) state.selectedRuleIds.add(rule.id);
        else state.selectedRuleIds.delete(rule.id);
        syncRuleBulkControls(visibleRules);
      });
      selectCell.append(checkbox);
      row.append(selectCell);

      const summaryCell = document.createElement("td");
      const summary = node("div", "admin-primary", name);
      const purpose = node("div", "admin-secondary", rulePurpose(rule));
      const idLine = node("div", "admin-kicker", rule.local_rule_id || rule.server_rule_id || rule.id || "");
      summaryCell.append(summary, purpose, idLine);

      const siteCell = document.createElement("td");
      siteCell.append(node("div", "admin-mono", sitePattern));
      siteCell.append(node("div", "admin-secondary", ruleAccessSummary(rule)));

      const statusCell = document.createElement("td");
      statusCell.append(chip(statusLabel, rule.enabled === false ? "danger" : "success"));
      statusCell.append(node("div", "admin-secondary", `${steps} step${steps === 1 ? "" : "s"}`));

      const selectorCell = document.createElement("td");
      selectorCell.className = "selector-cell";
      const selectorWrap = node("div", "chip-wrap");
      const selectorSummaries = ruleSelectorSummaries(rule);
      for (const text of selectorSummaries) selectorWrap.append(chip(text, "mono"));
      if (steps > selectorSummaries.length) selectorWrap.append(chip(`+${steps - selectorSummaries.length} more`, "muted"));
      if (!selectorSummaries.length) selectorWrap.append(chip("No selector", "muted"));
      selectorCell.append(selectorWrap);

      const actionsCell = document.createElement("td");
      const actions = node("div", "row-actions");
      const editBtn = actionButton("Edit");
      editBtn.addEventListener("click", (event) => {
        event.stopPropagation();
        selectRule(rule.id);
      });
      const toggleBtn = actionButton(rule.enabled === false ? "Enable" : "Pause");
      toggleBtn.addEventListener("click", (event) => {
        event.stopPropagation();
        handle(() => setRuleEnabled(rule.id, rule.enabled === false), rule.enabled === false ? "Rule enabled" : "Rule paused");
      });
      const detailsBtn = actionButton(state.expandedRuleIds.has(rule.id) ? "Hide" : "Details");
      detailsBtn.addEventListener("click", (event) => {
        event.stopPropagation();
        toggleRuleDetails(rule.id);
      });
      const deleteBtn = actionButton("Delete", "icon-text-btn danger");
      deleteBtn.addEventListener("click", (event) => {
        event.stopPropagation();
        handle(() => deleteRuleById(rule.id), "Rule deleted");
      });
      actions.append(editBtn, toggleBtn, detailsBtn, deleteBtn);
      actionsCell.append(actions);

      row.append(summaryCell, siteCell, statusCell, selectorCell, actionsCell);
      row.addEventListener("dblclick", () => selectRule(rule.id));
      tbody.append(row);
      if (state.expandedRuleIds.has(rule.id)) renderRuleDetailsRow(tbody, rule);
    }
  }
  syncRuleBulkControls(visibleRules);
}

function scriptMeta(script) {
  const stored = (script?.parsedMeta && typeof script.parsedMeta === "object") ? script.parsedMeta : {};
  const rawCode = script?.rawCode || "";
  const fallbackName = cleanScriptTitle(script?.name || stored.name || "Untitled Script");
  const fallbackMatch = script?.match || stored.matches?.[0] || stored.includes?.[0] || "https://*/*";
  const fallbackVersion = script?.version || stored.version || "1.0.0";
  const parsed = parseScriptMeta(rawCode, fallbackName, fallbackMatch, fallbackVersion);
  const hasMetaBlock = /\/\/\s*==UserScript==[\s\S]*?\/\/\s*==\/UserScript==/.test(String(rawCode || ""));
  const meta = hasMetaBlock
    ? { ...stored, ...parsed }
    : Object.keys(stored).length
      ? { ...parsed, ...stored }
      : parsed;
  meta.name = cleanScriptTitle(meta.name || fallbackName);
  return meta;
}

function cleanScriptTitle(value) {
  return String(value || "")
    .replace(/^:[a-z]{2}(?:-[a-z0-9-]+)?\s+/i, "")
    .trim();
}

function scriptSourceUrl(script, meta = scriptMeta(script)) {
  const value = script?.sourceUrl || script?.updateUrl || meta.downloadURL || meta.updateURL || "";
  if (!value) return "";
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url.href : "";
  } catch (_) {
    return "";
  }
}

function scriptSitesTitle(meta = {}) {
  const matches = normalizeArray(meta.matches);
  const includes = normalizeArray(meta.includes);
  const excludes = normalizeArray(meta.exclude);
  const excludeMatches = normalizeArray(meta.excludeMatches);
  const sections = [
    ["Matches", matches],
    ["Includes", includes],
    ["Excludes", excludes],
    ["Exclude matches", excludeMatches]
  ].filter(([, values]) => values.length);
  if (!sections.length) return "Sites:\n- https://*/*";
  return sections
    .map(([label, values]) => `${label}:\n${values.map((value) => `- ${value}`).join("\n")}`)
    .join("\n\n");
}

function compactListLabel(values, fallback = "--") {
  const list = normalizeArray(values).map((item) => String(item || "").trim()).filter(Boolean);
  if (!list.length) return fallback;
  if (list.length <= 2) return list.join(", ");
  return `${list.slice(0, 2).join(", ")} +${list.length - 2}`;
}

function formatShortDate(value) {
  const timestamp = Number(value || 0);
  if (!timestamp) return "--";
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return "--";
  return date.toLocaleDateString(undefined, { year: "numeric", month: "2-digit", day: "2-digit" });
}

function scriptSizeBytes(script) {
  if (Number(script?.storageUsedBytes || 0) > 0) return Number(script.storageUsedBytes);
  return new Blob([script?.requiredCode || "", script?.rawCode || ""]).size;
}

function scriptFeatureLabels(script) {
  const meta = scriptMeta(script);
  const labels = [];
  const grants = (meta.grants || []).filter((grant) => grant && grant !== "none");
  if (grants.length) labels.push("GM");
  if ((meta.requires || []).length) labels.push(`Require ${meta.requires.length}`);
  if ((meta.connects || []).length) labels.push(`Connect ${meta.connects.includes("*") ? "*" : meta.connects.length}`);
  if (grants.some((grant) => /download/i.test(grant))) labels.push("Download");
  if ((meta.antifeatures || []).length) labels.push("Anti-feature");
  return labels;
}

async function toggleScriptEnabled(script) {
  if (!script?.id) return;
  state.scripts = state.scripts.map((item) => (
    item.id === script.id ? { ...item, enabled: item.enabled === false, updatedAt: Date.now() } : item
  ));
  await setStorage({ fp_scripts: state.scripts });
  await registerUserscripts();
  renderScripts();
  renderStatus();
}

async function deleteScript(scriptId) {
  if (!scriptId) return;
  if (!window.confirm("Delete this userscript?")) return;
  state.scripts = state.scripts.filter((item) => item.id !== scriptId);
  if (state.selectedScriptId === scriptId) state.selectedScriptId = null;
  await setStorage({ fp_scripts: state.scripts });
  await registerUserscripts();
  closeScriptEditor({ clearSelection: false, clearDraft: false });
  renderScripts();
  renderStatus();
}

function openLocalScriptEditor(script = null) {
  const isExisting = !!script?.id;
  state.selectedScriptId = isExisting ? script.id : null;
  setScriptEditorOpen(true);
  const meta = script ? scriptMeta(script) : {};
  const name = script?.name || meta.name || "EazyFill Script";
  const version = script?.version || meta.version || "1.0.0";
  const match = script ? (script.match || meta.matches?.[0] || meta.includes?.[0] || "https://*/*") : "https://*/*";
  const rawCode = script?.rawCode || scriptTemplate(name, match, version);
  setValue("script-name", isExisting ? name : "");
  setValue("script-version", version);
  setValue("script-match", match);
  setChecked("script-enabled", script?.enabled !== false);
  appendProfileOptions($("script-profile-id"), script ? itemProfileId(script) : DEFAULT_PROFILE_ID);
  setValue("script-source-url", "");
  if (scriptEditor) {
    scriptEditor.dispatch({
      changes: {from: 0, to: scriptEditor.state.doc.length, insert: rawCode}
    });
  }
  setText("script-editor-title", isExisting ? name : "<New userscript>");
  renderScriptMetaPreview(rawCode);
  renderScripts();
  requestAnimationFrame(() => {
    $("script-editor-card")?.scrollIntoView({ behavior: "smooth", block: "start" });
    scriptEditor?.focus?.();
    scriptEditor?.requestMeasure?.();
  });
}

function remoteScriptUpdateUrl(script) {
  if (!script || !isRemoteUserscript(script)) return "";
  const meta = scriptMeta(script);
  return script.updateUrl || script.sourceUrl || meta.updateURL || meta.downloadURL || "";
}

async function fetchUpdatedRemoteScript(script) {
  if (!script?.id || !isRemoteUserscript(script)) return;
  const url = remoteScriptUpdateUrl(script);
  if (!url) throw new Error("This URL-managed script does not have an update URL");
  const { rawCode, sourceUrl } = await fetchScriptFromUrl(url);
  return scriptFromRemote(rawCode, sourceUrl, script);
}

async function refreshRemoteScript(script) {
  const refreshed = await fetchUpdatedRemoteScript(script);
  state.scripts = state.scripts.map((item) => (item.id === script.id ? refreshed : item));
  await setStorage({ fp_scripts: state.scripts });
  await registerUserscripts();
  renderScripts();
  renderStatus();
}

async function updateRemoteScriptsForActiveProfile() {
  const remoteScripts = state.scripts.filter((script) => itemMatchesActiveProfile(script) && isRemoteUserscript(script));
  if (!remoteScripts.length) throw new Error(`No URL-managed scripts in ${profileName(activeProfileId())}`);

  const refreshedById = new Map();
  const failures = [];
  for (const script of remoteScripts) {
    try {
      refreshedById.set(script.id, await fetchUpdatedRemoteScript(script));
    } catch (error) {
      failures.push({
        id: script.id,
        name: scriptMeta(script).name || script.name || "Untitled Script",
        message: error?.message || String(error || "Update failed")
      });
    }
  }

  if (!refreshedById.size && failures.length) {
    throw new Error(`Could not update ${failures.length} script${failures.length === 1 ? "" : "s"}: ${failures[0].message}`);
  }

  state.scripts = state.scripts.map((script) => {
    if (refreshedById.has(script.id)) return refreshedById.get(script.id);
    const failure = failures.find((item) => item.id === script.id);
    return failure ? { ...script, lastError: failure.message, updatedAt: Date.now() } : script;
  });
  await setStorage({ fp_scripts: state.scripts });
  await registerUserscripts();
  renderScripts();
  renderProfiles();
  renderStatus();

  if (failures.length) {
    toast(`Updated ${refreshedById.size}; ${failures.length} failed. ${failures[0].name}: ${failures[0].message}`, "warning");
  } else {
    toast(`Updated ${refreshedById.size} script${refreshedById.size === 1 ? "" : "s"}`, "success");
  }
}

function renderScripts() {
  const tbody = $("scripts-table");
  clearTable(tbody);
  const visibleScripts = state.scripts.filter(itemMatchesActiveProfile);
  if (!visibleScripts.length) {
    appendEmptyRow(tbody, 8, `No scripts in ${profileName(activeProfileId())}`);
    renderUserscriptStatus();
    return;
  }
  for (const script of visibleScripts) {
    const meta = scriptMeta(script);
    const name = meta.name || cleanScriptTitle(script.name) || "Untitled Script";
    const version = script.version || meta.version || "1.0.0";
    const remote = isRemoteUserscript(script);
    const row = document.createElement("tr");
    row.dataset.id = script.id;
    row.classList.toggle("selected", script.id === state.selectedScriptId);

    const enabledCell = document.createElement("td");
    enabledCell.className = "script-enabled-cell";
    const toggle = node("button", `mini-switch ${script.enabled !== false ? "on" : ""}`.trim(), "");
    toggle.type = "button";
    toggle.setAttribute("role", "switch");
    toggle.setAttribute("aria-checked", script.enabled !== false ? "true" : "false");
    toggle.title = script.enabled === false ? "Enable userscript" : "Disable userscript";
    toggle.addEventListener("click", () => handle(() => toggleScriptEnabled(script), script.enabled === false ? "Script enabled" : "Script paused"));
    toggle.append(node("span", "mini-switch-knob"));
    enabledCell.append(toggle);

    const nameCell = document.createElement("td");
    const nameWrap = node("div", "script-name-wrap");
    const nameText = node("div", "script-name-text");
    const sourceUrl = remote ? scriptSourceUrl(script, meta) : "";
    const nameNode = sourceUrl ? document.createElement("a") : document.createElement("div");
    nameNode.className = "admin-primary script-display-name";
    nameNode.textContent = name;
    nameNode.title = sourceUrl ? `${name}\n${sourceUrl}` : name;
    if (sourceUrl) {
      nameNode.href = sourceUrl;
      nameNode.target = "_blank";
      nameNode.rel = "noopener noreferrer";
      nameNode.addEventListener("click", (event) => event.stopPropagation());
    }
    nameText.append(nameNode);
    nameWrap.append(nameText);
    nameCell.append(nameWrap);
    if (script.enabled === false) nameCell.append(chip("Disabled", "danger"));

    const versionCell = document.createElement("td");
    versionCell.append(node("div", "admin-primary", version));

    const sizeCell = document.createElement("td");
    sizeCell.append(node("div", "admin-primary", formatBytes(scriptSizeBytes(script))));

    const sitesCell = document.createElement("td");
    const sitesWrap = node("div", "chip-wrap");
    const matches = [...(meta.matches || []), ...(meta.includes || [])].filter(Boolean);
    const sitesTitle = scriptSitesTitle(meta);
    sitesCell.title = sitesTitle;
    sitesWrap.title = sitesTitle;
    matches.slice(0, 2).forEach((match) => {
      const siteChip = chip(match, "mono");
      siteChip.title = sitesTitle;
      sitesWrap.append(siteChip);
    });
    if (matches.length > 2) {
      const moreChip = chip(`+${matches.length - 2} more`, "muted");
      moreChip.title = sitesTitle;
      sitesWrap.append(moreChip);
    }
    if (!matches.length) {
      const fallbackSiteChip = chip("https://*/*", "mono");
      fallbackSiteChip.title = sitesTitle;
      sitesWrap.append(fallbackSiteChip);
    }
    sitesCell.append(sitesWrap);

    const featuresCell = document.createElement("td");
    const features = node("div", "script-feature-chips");
    const featureLabels = scriptFeatureLabels(script);
    const featuresTitle = featureLabels.length ? featureLabels.join("\n") : "None";
    featuresCell.title = featuresTitle;
    featureLabels.forEach((label) => {
      const featureChip = chip(label, label === "Anti-feature" ? "danger" : "muted");
      featureChip.title = featuresTitle;
      features.append(featureChip);
    });
    if (!featureLabels.length) features.append(chip("None", "muted"));
    featuresCell.append(features);

    const updatedCell = document.createElement("td");
    updatedCell.append(node("div", "admin-primary", formatShortDate(script.updatedAt || script.lastUpdatedFromUrlAt || script.installedAt)));

    const actionsCell = document.createElement("td");
    const actions = node("div", "row-actions script-actions");
    if (remote) {
      const refreshBtn = actionButton("Refresh");
      refreshBtn.addEventListener("click", () => handle(() => refreshRemoteScript(script), "Script refreshed from URL"));
      actions.append(refreshBtn);
    } else {
      const editBtn = actionButton("Edit");
      editBtn.addEventListener("click", () => openLocalScriptEditor(script));
      actions.append(editBtn);
    }
    const deleteBtn = node("button", "icon-text-btn danger", "Delete");
    deleteBtn.type = "button";
    deleteBtn.addEventListener("click", () => handle(() => deleteScript(script.id), "Script deleted"));
    actions.append(deleteBtn);
    actionsCell.append(actions);

    row.append(enabledCell, nameCell, versionCell, sizeCell, sitesCell, featuresCell, updatedCell, actionsCell);
    tbody.append(row);
  }
  renderUserscriptStatus();
}

function renderUserscriptStatus() {
  const node = $("script-runtime-status");
  if (!node) return;
  const status = state.userscriptStatus || {};
  if (!Object.keys(status).length) {
    node.dataset.tone = "warning";
    node.textContent = "Checking userscript runtime...";
    return;
  }
  const count = status.registeredCount ?? status.count ?? 0;
  if (status.available || status.ok) {
    node.dataset.tone = "success";
    node.textContent = `Chrome userScripts runtime ready. ${count} script${count === 1 ? "" : "s"} registered.`;
    return;
  }
  node.dataset.tone = "warning";
  const instructions = Array.isArray(status.instructions) ? ` ${status.instructions.join(" ")}` : "";
  node.textContent = `${status.error || "Chrome userScripts runtime is not enabled."}${instructions}`;
}

function uniqueNonEmptyStrings(values = []) {
  return [...new Set((values || []).map((value) => String(value || "").trim()).filter(Boolean))];
}

function scriptSourceHost(url = "") {
  try {
    return new URL(url).hostname.replace(/^www\./, "") || url;
  } catch (_) {
    return url;
  }
}

function buildUserscriptInstallPreview(rawCode, sourceUrl) {
  const hasMetaBlock = /\/\/\s*==UserScript==[\s\S]*?\/\/\s*==\/UserScript==/.test(String(rawCode || ""));
  const meta = parseScriptMeta(rawCode, "", "https://*/*", "1.0.0");
  return {
    rawCode,
    sourceUrl,
    meta,
    hasMetaBlock,
    name: meta.name || "Untitled Script",
    version: meta.version || "1.0.0",
    matches: uniqueNonEmptyStrings([...(meta.matches || []), ...(meta.includes || [])]),
    excludes: uniqueNonEmptyStrings([...(meta.exclude || []), ...(meta.excludeMatches || [])]),
    grants: uniqueNonEmptyStrings(meta.grants || []),
    connects: uniqueNonEmptyStrings(meta.connects || []),
    requires: uniqueNonEmptyStrings(meta.requires || []),
    resources: uniqueNonEmptyStrings((meta.resources || []).map((resource) => `${resource.name}: ${resource.url}`)),
    runAt: meta.runAt || "document-idle",
    author: meta.author || "",
    homepageURL: meta.homepageURL || "",
    sizeBytes: new Blob([rawCode || ""]).size
  };
}

function userscriptInstallRow(label, values, emptyText = "none") {
  const row = node("div", "userscript-install-row");
  row.append(node("div", "userscript-install-label", label));
  const valuesWrap = node("div", "userscript-install-values");
  const items = uniqueNonEmptyStrings(values);
  if (items.length) {
    for (const item of items) {
      const itemChip = chip(item, "mono");
      itemChip.title = item;
      valuesWrap.append(itemChip);
    }
  } else {
    valuesWrap.append(node("span", "admin-secondary", emptyText));
  }
  row.append(valuesWrap);
  return row;
}

function renderUserscriptInstallReview() {
  const card = $("script-install-review-card");
  const body = $("script-install-review-body");
  if (!card || !body) return;
  const pending = state.pendingScriptInstall;
  setHidden(card, !pending);
  body.replaceChildren();
  if (!pending) return;

  const summary = node("div", "userscript-install-summary");
  const main = node("div");
  main.append(node("h4", "userscript-install-title", pending.name));
  const sourceLink = node("a", "userscript-install-source", pending.sourceUrl);
  sourceLink.href = pending.sourceUrl;
  sourceLink.target = "_blank";
  sourceLink.rel = "noopener noreferrer";
  sourceLink.title = pending.sourceUrl;
  main.append(sourceLink);
  if (pending.meta?.description) {
    main.append(node("div", "admin-secondary", pending.meta.description));
  }
  main.append(node("div", "userscript-install-warning", "User-provided code. Install only from sources you trust."));

  const metaWrap = node("div", "userscript-install-meta");
  metaWrap.append(chip(`v${pending.version}`, "success"));
  metaWrap.append(chip(formatBytes(pending.sizeBytes), "muted"));
  metaWrap.append(chip(scriptSourceHost(pending.sourceUrl), "muted"));
  if (pending.runAt) metaWrap.append(chip(pending.runAt, "muted"));
  if (!pending.hasMetaBlock) metaWrap.append(chip("No metadata", "danger"));
  summary.append(main, metaWrap);

  const details = node("div", "userscript-install-details");
  details.append(userscriptInstallRow("Sites", pending.matches, "No @match or @include"));
  details.append(userscriptInstallRow("Excludes", pending.excludes));
  details.append(userscriptInstallRow("Grants", pending.grants, "none"));
  details.append(userscriptInstallRow("Connect", pending.connects, "none"));
  details.append(userscriptInstallRow("Require", pending.requires, "none"));
  if (pending.resources.length) details.append(userscriptInstallRow("Resources", pending.resources));
  if (pending.author) details.append(userscriptInstallRow("Author", [pending.author]));
  if (pending.homepageURL) details.append(userscriptInstallRow("Homepage", [pending.homepageURL]));

  body.append(summary, details);
}

function clearPendingUserscriptInstall() {
  state.pendingScriptInstall = null;
  renderUserscriptInstallReview();
}

async function installPendingUserscript() {
  const pending = state.pendingScriptInstall;
  if (!pending) throw new Error("No userscript is ready to install");
  const script = await scriptFromRemote(pending.rawCode, pending.sourceUrl);
  state.scripts = [...state.scripts, script];
  state.selectedScriptId = null;
  state.pendingScriptInstall = null;
  await setStorage({ fp_scripts: state.scripts });
  await registerUserscripts();
  renderUserscriptInstallReview();
  renderScripts();
  renderProfiles();
  renderStatus();
}

async function refreshUserscriptStatus() {
  const response = await sendMessage({ type: "USERSCRIPTS_STATUS" });
  state.userscriptStatus = response || {};
  renderUserscriptStatus();
  return response;
}

function renderScriptMetaPreview(rawCode = null) {
  const node = $("script-meta-preview");
  if (!node) return;
  const code = rawCode ?? (scriptEditor ? scriptEditor.state.doc.toString() : "");
  if (!String(code || "").trim()) {
    node.dataset.tone = "warning";
    node.textContent = "Script metadata preview will appear here.";
    return;
  }
  const hasMetaBlock = /\/\/\s*==UserScript==[\s\S]*?\/\/\s*==\/UserScript==/.test(code);
  const meta = parseScriptMeta(
    code,
    $("script-name")?.value || "Untitled Script",
    $("script-match")?.value || "https://*/*",
    $("script-version")?.value || "1.0.0"
  );
  const matches = [...(meta.matches || []), ...(meta.includes || [])].filter(Boolean);
  const grants = (meta.grants || []).filter(Boolean);
  if (hasMetaBlock) {
    if (meta.name) setValue("script-name", meta.name);
    if (meta.version) setValue("script-version", meta.version);
    if (matches[0]) setValue("script-match", matches[0]);
    setText("script-editor-title", meta.name || "<New userscript>");
  }
  node.dataset.tone = hasMetaBlock ? "success" : "warning";
  node.textContent = [
    `Name: ${meta.name || "Untitled Script"}`,
    `Version: ${meta.version || "1.0.0"}`,
    `Matches: ${matches.length || 0}`,
    `Grants: ${grants.length ? grants.join(", ") : "none"}`,
    `Size: ${new Blob([code]).size} bytes`,
    hasMetaBlock ? "Metadata block detected." : "No UserScript metadata block; defaults will be used."
  ].join(" | ");
}

function setScriptEditorOpen(open) {
  const card = $("script-editor-card");
  setHidden(card, !open);
  if (open && scriptEditor) {
    requestAnimationFrame(() => scriptEditor.requestMeasure());
  }
}

function clearScriptDraft() {
  setValue("script-name", "");
  setValue("script-version", "1.0.0");
  setValue("script-match", "");
  setValue("script-source-url", "");
  setChecked("script-enabled", true);
  if (scriptEditor) {
    scriptEditor.dispatch({
      changes: {from: 0, to: scriptEditor.state.doc.length, insert: ""}
    });
  }
  renderScriptMetaPreview("");
  setText("script-editor-title", "<New userscript>");
}

function closeScriptEditor({ clearSelection = true, clearDraft = true } = {}) {
  const card = $("script-editor-card");
  if (card) card.classList.remove("userscript-fullscreen-active");
  if (clearDraft) clearScriptDraft();
  if (clearSelection) {
    state.selectedScriptId = null;
    renderScripts();
  }
  setScriptEditorOpen(false);
}

async function registerUserscripts({ surfaceSetupError = false } = {}) {
  const response = await sendMessage({ type: "USERSCRIPTS_REGISTER" });
  state.userscriptStatus = response || {};
  renderUserscriptStatus();
  if (!response.ok && (surfaceSetupError || !response.setupRequired)) {
    const instructions = Array.isArray(response.instructions) ? ` ${response.instructions.join(" ")}` : "";
    throw new Error(`${response.error || "Userscript registration failed."}${instructions}`);
  }
  return response;
}

function renderProfiles() {
  const tbody = $("profiles-table");
  clearTable(tbody);
  const profiles = [{ id: DEFAULT_PROFILE_ID, name: "Global", values: {} }, ...state.profiles];
  for (const profile of profiles) {
    const profileId = normalizedProfileId(profile.id);
    const row = document.createElement("tr");
    row.dataset.id = profileId;
    row.classList.toggle("selected", profileId === state.selectedProfileId);
    row.classList.toggle("active-profile-row", profileId === activeProfileId());

    const nameCell = document.createElement("td");
    nameCell.append(node("div", "admin-primary", profile.name || "Untitled Profile"));
    nameCell.append(node("div", "admin-secondary", profileId));
    if (profileId === activeProfileId()) nameCell.append(chip("Active", "success"));

    const usageCell = document.createElement("td");
    const counts = profileUsageCounts(profileId);
    const usageWrap = node("div", "chip-wrap");
    usageWrap.append(chip(`${counts.rules} rules`, counts.rules ? "success" : "muted"));
    usageWrap.append(chip(`${counts.scripts} scripts`, counts.scripts ? "success" : "muted"));
    usageWrap.append(chip(`${counts.captchaRoutes} CAPTCHA`, counts.captchaRoutes ? "success" : "muted"));
    usageCell.append(usageWrap);

    const actionCell = document.createElement("td");
    const actions = node("div", "row-actions profile-row-actions");
    const editBtn = actionButton("Edit");
    editBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      editProfile(profileId);
    });
    const activateBtn = actionButton(profileId === activeProfileId() ? "Active" : "Use");
    activateBtn.disabled = profileId === activeProfileId();
    activateBtn.addEventListener("click", (event) => {
      event.stopPropagation();
      handle(() => setActiveProfile(profileId), "Profile activated");
    });
    actions.append(editBtn, activateBtn);
    actionCell.append(actions);

    row.append(nameCell, usageCell, actionCell);
    tbody.append(row);
  }
  renderProfileOptions();
  renderProfileItems();
}

function editProfile(profileId) {
  const id = normalizedProfileId(profileId);
  state.profileDetailId = id;
  state.selectedProfileItemKeys.clear();
  if (id === DEFAULT_PROFILE_ID) {
    state.selectedProfileId = null;
    $("profile-name").value = "Global";
    $("profile-id").value = "";
  } else {
    state.selectedProfileId = id;
    const profile = state.profiles.find((item) => String(item.id) === id) || {};
    $("profile-name").value = profile.name || "";
    $("profile-id").value = profile.id || "";
  }
  renderProfiles();
  requestAnimationFrame(() => $("profile-items-surface")?.scrollIntoView({ behavior: "smooth", block: "start" }));
}

function selectProfile(id) {
  state.selectedProfileId = id || null;
  state.profileDetailId = "";
  state.selectedProfileItemKeys.clear();
  const profile = state.profiles.find((item) => item.id === id) || {};
  $("profile-name").value = profile.name || "";
  $("profile-id").value = profile.id || "";
  renderProfiles();
}

function allProfileChoices() {
  return [{ id: DEFAULT_PROFILE_ID, name: "Global" }, ...state.profiles.map((profile) => ({
    id: normalizedProfileId(profile.id),
    name: profile.name || profile.id || "Untitled Profile"
  }))];
}

function createProfileCloneSelect(currentProfileId) {
  const select = document.createElement("select");
  select.className = "profile-clone-select";
  const choices = allProfileChoices().filter((profile) => profile.id !== normalizedProfileId(currentProfileId));
  for (const profile of choices) {
    const option = document.createElement("option");
    option.value = profile.id;
    option.textContent = profile.name;
    select.append(option);
  }
  if (!choices.length) select.disabled = true;
  return select;
}

function populateProfileCloneTarget(select, currentProfileId) {
  if (!select) return;
  const current = normalizedProfileId(currentProfileId);
  const choices = allProfileChoices().filter((profile) => profile.id !== current);
  select.replaceChildren();
  for (const profile of choices) {
    const option = document.createElement("option");
    option.value = profile.id;
    option.textContent = profile.name;
    select.append(option);
  }
  select.disabled = choices.length === 0;
}

function profileItemKey(item) {
  const parts = item.kind === "captcha"
    ? [item.kind, item.domain, item.routeId]
    : [item.kind, item.id];
  return parts.map((part) => encodeURIComponent(String(part || ""))).join(":");
}

function buildProfileItemGroups(profileId) {
  const id = normalizedProfileId(profileId);
  const groups = [
    {
      key: "rules",
      label: "Autofill Rules",
      items: state.rules.filter((rule) => itemMatchesProfile(rule, id)).map((rule) => ({
        kind: "rule",
        id: rule.id,
        name: rule.name || "Untitled Rule",
        profileIds: itemProfileIds(rule)
      }))
    },
    {
      key: "scripts",
      label: "Userscripts",
      items: state.scripts.filter((script) => itemMatchesProfile(script, id)).map((script) => ({
        kind: "script",
        id: script.id,
        name: script.name || scriptMeta(script).name || "Untitled Script",
        profileIds: itemProfileIds(script)
      }))
    },
    { key: "captcha", label: "CAPTCHA Routes", items: [] }
  ];
  for (const [domain, config] of Object.entries(state.captchaSelectors || {})) {
    for (const route of captchaRowsForConfig(domain, config).filter((route) => routeMatchesProfile(route, id))) {
      groups[2].items.push({
        kind: "captcha",
        domain,
        routeId: route.routeId,
        name: route.fieldName || route.routeId || "CAPTCHA Route",
        profileIds: routeProfileIds(route)
      });
    }
  }
  for (const group of groups) {
    group.items = group.items.map((item) => ({ ...item, key: profileItemKey(item) }));
  }
  return groups;
}

function flatProfileItems(groups) {
  return groups.flatMap((group) => group.items);
}

function pruneSelectedProfileItemKeys(visibleItems) {
  const visibleKeys = new Set(visibleItems.map((item) => item.key));
  for (const key of [...state.selectedProfileItemKeys]) {
    if (!visibleKeys.has(key)) state.selectedProfileItemKeys.delete(key);
  }
}

function syncProfileItemBulkControls(visibleItems = []) {
  const selectedVisibleCount = visibleItems.filter((item) => state.selectedProfileItemKeys.has(item.key)).length;
  const selectedCount = state.selectedProfileItemKeys.size;
  const selectAll = $("profile-item-select-all");
  if (selectAll) {
    selectAll.checked = visibleItems.length > 0 && selectedVisibleCount === visibleItems.length;
    selectAll.indeterminate = selectedVisibleCount > 0 && selectedVisibleCount < visibleItems.length;
    selectAll.disabled = visibleItems.length === 0;
  }
  setText("profile-items-selection-summary", `${selectedCount} selected`);
  const cloneTarget = $("profile-bulk-clone-target");
  if (cloneTarget) cloneTarget.disabled = cloneTarget.options.length === 0 || selectedCount === 0;
  for (const id of ["profile-clone-selected-btn", "profile-remove-selected-btn"]) {
    const button = $(id);
    if (button) button.disabled = selectedCount === 0;
  }
}

function appendProfileItemRow(tbody, item) {
  const profileId = normalizedProfileId(state.profileDetailId);
  const row = document.createElement("tr");
  row.className = "profile-item-row";
  row.classList.toggle("selected", state.selectedProfileItemKeys.has(item.key));

  const selectCell = document.createElement("td");
  selectCell.className = "select-col";
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.className = "row-checkbox";
  checkbox.checked = state.selectedProfileItemKeys.has(item.key);
  checkbox.addEventListener("click", (event) => event.stopPropagation());
  checkbox.addEventListener("change", () => {
    if (checkbox.checked) state.selectedProfileItemKeys.add(item.key);
    else state.selectedProfileItemKeys.delete(item.key);
    renderProfileItems();
  });
  selectCell.append(checkbox);

  const itemCell = document.createElement("td");
  itemCell.append(node("div", "admin-primary", item.name));

  const cloneCell = document.createElement("td");
  const cloneWrap = node("div", "profile-clone-controls");
  const cloneSelect = createProfileCloneSelect(profileId);
  const cloneBtn = actionButton("Clone");
  cloneBtn.disabled = cloneSelect.disabled;
  cloneBtn.addEventListener("click", () => handle(() => cloneProfileItem(item, cloneSelect.value), "Cloned to profile"));
  cloneWrap.append(cloneSelect, cloneBtn);
  cloneCell.append(cloneWrap);

  const actionCell = document.createElement("td");
  const actions = node("div", "profile-item-actions");
  const removeBtn = actionButton("Remove", "icon-text-btn danger");
  const isOnlyGlobalOwner = profileId === DEFAULT_PROFILE_ID && item.profileIds.length <= 1;
  removeBtn.disabled = isOnlyGlobalOwner;
  if (isOnlyGlobalOwner) removeBtn.title = "Clone this item to another profile before removing it from Global.";
  removeBtn.addEventListener("click", () => handle(() => removeProfileItem(item), "Removed from profile"));
  actions.append(removeBtn);
  actionCell.append(actions);

  row.append(selectCell, itemCell, cloneCell, actionCell);
  tbody.append(row);
}

function appendProfileCategoryRow(tbody, label) {
  const row = document.createElement("tr");
  row.className = "profile-category-row";
  const cell = document.createElement("td");
  cell.colSpan = 4;
  cell.textContent = label;
  row.append(cell);
  tbody.append(row);
}

function renderProfileItems() {
  const tbody = $("profile-items-table");
  if (!tbody) return;
  clearTable(tbody);
  const surface = $("profile-items-surface");
  const detailId = state.profileDetailId ? normalizedProfileId(state.profileDetailId) : "";
  if (!detailId) {
    setHidden(surface, true);
    state.selectedProfileItemKeys.clear();
    syncProfileItemBulkControls([]);
    return;
  }
  setHidden(surface, false);
  setText("profile-items-title", `${profileName(detailId)} Automations`);
  populateProfileCloneTarget($("profile-bulk-clone-target"), detailId);
  const groups = buildProfileItemGroups(detailId);
  const visibleItems = flatProfileItems(groups);
  pruneSelectedProfileItemKeys(visibleItems);
  const total = visibleItems.length;
  if (!total) {
    appendEmptyRow(tbody, 4, `No automations in ${profileName(detailId)}`);
    syncProfileItemBulkControls([]);
    return;
  }
  for (const group of groups) {
    if (!group.items.length) continue;
    appendProfileCategoryRow(tbody, group.label);
    group.items.forEach((item) => appendProfileItemRow(tbody, item));
  }
  syncProfileItemBulkControls(visibleItems);
}

async function cloneProfileItem(item, targetProfileId) {
  const target = normalizedProfileId(targetProfileId);
  if (!target) throw new Error("Choose a target profile");
  if (item.kind === "rule") {
    state.rules = state.rules.map((rule) => rule.id === item.id ? { ...withItemProfile(rule, target), updatedAt: Date.now() } : rule);
    await setStorage({ fp_rules: state.rules });
  } else if (item.kind === "script") {
    state.scripts = state.scripts.map((script) => script.id === item.id ? { ...withItemProfile(script, target), updatedAt: Date.now() } : script);
    await setStorage({ fp_scripts: state.scripts });
    await registerUserscripts().catch(() => null);
  } else if (item.kind === "captcha") {
    const next = { ...(state.captchaSelectors || {}) };
    const config = next[item.domain] || {};
    const routes = captchaRouteMapForConfig(item.domain, config);
    routes[item.routeId] = withRouteProfile(routes[item.routeId], target);
    writeCaptchaDomainConfig(next, item.domain, routes, config.activeFieldName);
    state.captchaSelectors = next;
    await setStorage({ fp_captcha_selectors: next });
    await sendMessage({ type: "CAPTCHA_CONFIG_UPDATED" }).catch(() => null);
  }
  renderProfiles();
  renderRules();
  renderScripts();
  renderCaptchaConfigs();
  renderStatus();
}

async function removeProfileItem(item) {
  const profileId = state.profileDetailId ? normalizedProfileId(state.profileDetailId) : activeProfileId();
  if (!window.confirm(`Remove this item from ${profileName(profileId)}?`)) return;
  if (item.kind === "rule") {
    state.rules = state.rules.map((rule) => {
      if (rule.id !== item.id) return rule;
      const next = removeItemProfile(rule, profileId);
      if (!next) throw new Error("Clone this item to another profile before removing it from Global.");
      return { ...next, updatedAt: Date.now() };
    });
    await setStorage({ fp_rules: state.rules });
  } else if (item.kind === "script") {
    state.scripts = state.scripts.map((script) => {
      if (script.id !== item.id) return script;
      const next = removeItemProfile(script, profileId);
      if (!next) throw new Error("Clone this item to another profile before removing it from Global.");
      return { ...next, updatedAt: Date.now() };
    });
    await setStorage({ fp_scripts: state.scripts });
    await registerUserscripts().catch(() => null);
  } else if (item.kind === "captcha") {
    const nextSelectors = { ...(state.captchaSelectors || {}) };
    const config = nextSelectors[item.domain] || {};
    const routes = captchaRouteMapForConfig(item.domain, config);
    const nextRoute = removeRouteProfile(routes[item.routeId], profileId);
    if (!nextRoute) throw new Error("Clone this item to another profile before removing it from Global.");
    routes[item.routeId] = nextRoute;
    writeCaptchaDomainConfig(nextSelectors, item.domain, routes, config.activeFieldName);
    state.captchaSelectors = nextSelectors;
    await setStorage({ fp_captcha_selectors: nextSelectors });
    await sendMessage({ type: "CAPTCHA_CONFIG_UPDATED" }).catch(() => null);
  }
  renderProfiles();
  renderRules();
  renderScripts();
  renderCaptchaConfigs();
  renderStatus();
}

function selectedProfileItems() {
  if (!state.profileDetailId) return [];
  const selected = new Set(state.selectedProfileItemKeys);
  return flatProfileItems(buildProfileItemGroups(state.profileDetailId)).filter((item) => selected.has(item.key));
}

async function cloneSelectedProfileItems(targetProfileId) {
  const target = normalizedProfileId(targetProfileId || $("profile-bulk-clone-target")?.value);
  const selected = selectedProfileItems();
  if (!selected.length) return;
  if (!target) throw new Error("Choose a target profile");
  const selectedRules = new Set(selected.filter((item) => item.kind === "rule").map((item) => item.id));
  const selectedScripts = new Set(selected.filter((item) => item.kind === "script").map((item) => item.id));
  const selectedCaptcha = new Map(selected.filter((item) => item.kind === "captcha").map((item) => [`${item.domain}\n${item.routeId}`, item]));
  const now = Date.now();
  let rulesChanged = false;
  let scriptsChanged = false;
  let captchaChanged = false;

  if (selectedRules.size) {
    state.rules = state.rules.map((rule) => {
      if (!selectedRules.has(rule.id)) return rule;
      rulesChanged = true;
      return { ...withItemProfile(rule, target), updatedAt: now };
    });
  }

  if (selectedScripts.size) {
    state.scripts = state.scripts.map((script) => {
      if (!selectedScripts.has(script.id)) return script;
      scriptsChanged = true;
      return { ...withItemProfile(script, target), updatedAt: now };
    });
  }

  if (selectedCaptcha.size) {
    const next = { ...(state.captchaSelectors || {}) };
    for (const [domain, config] of Object.entries(next)) {
      const routes = captchaRouteMapForConfig(domain, config);
      let domainChanged = false;
      for (const routeId of Object.keys(routes)) {
        if (!selectedCaptcha.has(`${domain}\n${routeId}`)) continue;
        routes[routeId] = { ...withRouteProfile(routes[routeId], target), updatedAt: now };
        domainChanged = true;
        captchaChanged = true;
      }
      if (domainChanged) writeCaptchaDomainConfig(next, domain, routes, config.activeFieldName);
    }
    state.captchaSelectors = next;
  }

  const writes = {};
  if (rulesChanged) writes.fp_rules = state.rules;
  if (scriptsChanged) writes.fp_scripts = state.scripts;
  if (captchaChanged) writes.fp_captcha_selectors = state.captchaSelectors;
  if (Object.keys(writes).length) await setStorage(writes);
  if (scriptsChanged) await registerUserscripts().catch(() => null);
  if (captchaChanged) await sendMessage({ type: "CAPTCHA_CONFIG_UPDATED" }).catch(() => null);
  state.selectedProfileItemKeys.clear();
  renderProfiles();
  renderRules();
  renderScripts();
  renderCaptchaConfigs();
  renderStatus();
}

async function removeSelectedProfileItems() {
  const profileId = state.profileDetailId ? normalizedProfileId(state.profileDetailId) : activeProfileId();
  const selected = selectedProfileItems();
  if (!selected.length) return;
  if (profileId === DEFAULT_PROFILE_ID && selected.some((item) => item.profileIds.length <= 1)) {
    throw new Error("Clone selected Global items to another profile before removing them from Global.");
  }
  if (!window.confirm(`Remove ${selected.length} selected item${selected.length === 1 ? "" : "s"} from ${profileName(profileId)}?`)) return;
  const selectedRules = new Set(selected.filter((item) => item.kind === "rule").map((item) => item.id));
  const selectedScripts = new Set(selected.filter((item) => item.kind === "script").map((item) => item.id));
  const selectedCaptcha = new Map(selected.filter((item) => item.kind === "captcha").map((item) => [`${item.domain}\n${item.routeId}`, item]));
  const now = Date.now();
  let rulesChanged = false;
  let scriptsChanged = false;
  let captchaChanged = false;

  if (selectedRules.size) {
    state.rules = state.rules.map((rule) => {
      if (!selectedRules.has(rule.id)) return rule;
      const next = removeItemProfile(rule, profileId);
      if (!next) throw new Error("Clone selected Global items to another profile before removing them from Global.");
      rulesChanged = true;
      return { ...next, updatedAt: now };
    });
  }

  if (selectedScripts.size) {
    state.scripts = state.scripts.map((script) => {
      if (!selectedScripts.has(script.id)) return script;
      const next = removeItemProfile(script, profileId);
      if (!next) throw new Error("Clone selected Global items to another profile before removing them from Global.");
      scriptsChanged = true;
      return { ...next, updatedAt: now };
    });
  }

  if (selectedCaptcha.size) {
    const nextSelectors = { ...(state.captchaSelectors || {}) };
    for (const [domain, config] of Object.entries(nextSelectors)) {
      const routes = captchaRouteMapForConfig(domain, config);
      let domainChanged = false;
      for (const routeId of Object.keys(routes)) {
        if (!selectedCaptcha.has(`${domain}\n${routeId}`)) continue;
        const nextRoute = removeRouteProfile(routes[routeId], profileId);
        if (!nextRoute) throw new Error("Clone selected Global items to another profile before removing them from Global.");
        routes[routeId] = { ...nextRoute, updatedAt: now };
        domainChanged = true;
        captchaChanged = true;
      }
      if (domainChanged) writeCaptchaDomainConfig(nextSelectors, domain, routes, config.activeFieldName);
    }
    state.captchaSelectors = nextSelectors;
  }

  const writes = {};
  if (rulesChanged) writes.fp_rules = state.rules;
  if (scriptsChanged) writes.fp_scripts = state.scripts;
  if (captchaChanged) writes.fp_captcha_selectors = state.captchaSelectors;
  if (Object.keys(writes).length) await setStorage(writes);
  if (scriptsChanged) await registerUserscripts().catch(() => null);
  if (captchaChanged) await sendMessage({ type: "CAPTCHA_CONFIG_UPDATED" }).catch(() => null);
  state.selectedProfileItemKeys.clear();
  renderProfiles();
  renderRules();
  renderScripts();
  renderCaptchaConfigs();
  renderStatus();
}

function setAllVisibleProfileItemsSelected(selected) {
  if (!state.profileDetailId) return;
  for (const item of flatProfileItems(buildProfileItemGroups(state.profileDetailId))) {
    if (selected) state.selectedProfileItemKeys.add(item.key);
    else state.selectedProfileItemKeys.delete(item.key);
  }
  renderProfileItems();
}

async function setActiveProfile(profileId) {
  state.settings = {
    ...state.settings,
    activeProfileId: normalizedProfileId(profileId)
  };
  await setStorage({ fp_settings: state.settings });
  await registerUserscripts().catch(() => null);
  await sendMessage({ type: "CAPTCHA_CONFIG_UPDATED" }).catch(() => null);
  state.selectedRuleIds.clear();
  state.selectedRuleId = null;
  state.selectedScriptId = null;
  state.selectedCaptchaDomain = "";
  state.selectedCaptchaRouteId = "";
  renderStatus();
  renderProfiles();
  renderRules();
  renderScripts();
  resetCaptchaEditor();
}

function captchaStatusValue(route = {}) {
  return String(route.routeStatus || route.route_status || route.status || "").trim().toLowerCase();
}

function captchaStatusLabel(route = {}) {
  const status = captchaStatusValue(route);
  if (!status) return "Ready";
  return status.split(/[_\s-]+/).filter(Boolean).map((part) => part[0].toUpperCase() + part.slice(1)).join(" ");
}

function captchaStatusTone(route = {}) {
  const status = captchaStatusValue(route);
  if (!status || status === "approved" || status === "pre_approved" || status === "preapproved") return "success";
  if (status === "pending" || status === "submitted") return "warning";
  if (status === "rejected" || status === "blocked") return "danger";
  return "muted";
}

function isCaptchaRouteApproved(route = {}) {
  return ["approved", "pre_approved", "preapproved"].includes(captchaStatusValue(route));
}

function captchaRouteSubmitTimestamp(route = {}) {
  const status = captchaStatusValue(route);
  const value = route.lastSubmittedAt
    || route.last_submitted_at
    || route.submittedAt
    || route.submitted_at
    || route.proposedAt
    || route.proposed_at
    || (["pending", "submitted"].includes(status) ? route.updatedAt || route.updated_at : 0);
  const timestamp = Number(value || 0);
  return Number.isFinite(timestamp) ? timestamp : 0;
}

function captchaRouteSubmitWaitMs(route = {}) {
  const timestamp = captchaRouteSubmitTimestamp(route);
  if (!timestamp) return 0;
  return Math.max(0, CAPTCHA_ROUTE_SUBMIT_COOLDOWN_MS - (Date.now() - timestamp));
}

function captchaRouteSubmitCooldownLabel(ms) {
  const hours = Math.ceil(Math.max(0, ms) / (60 * 60 * 1000));
  return `${hours}h`;
}

function sameCaptchaRoute(route, sourceSelector, targetSelector) {
  return String(route.sourceSelector || "").trim() === String(sourceSelector || "").trim()
    && String(route.targetSelector || "").trim() === String(targetSelector || "").trim();
}

function normalizeCaptchaRoute(domain, routeId, route = {}, config = {}) {
  const baseAutoSolve = config.autoSolve === true || config.auto_solve === true;
  const autoSolve = route.autoSolve === true || route.auto_solve === true || baseAutoSolve;
  const status = route.routeStatus || route.route_status || route.status || (autoSolve ? "approved" : "");
  const profileIds = routeProfileIds(route.profileIds || route.profile_ids ? route : { ...route, profileId: route.profileId || route.profile_id || config.profileId || config.profile_id });
  return {
    id: route.id || routeId,
    routeId,
    domain,
    profileId: profileIds[0] || DEFAULT_PROFILE_ID,
    profileIds,
    fieldName: route.fieldName || route.field_name || routeId || "captcha",
    taskType: route.taskType || route.task_type || route.sourceDataType || route.source_data_type || config.taskType || config.task_type || "image",
    sourceSelector: route.sourceSelector || route.source_selector || route.source || "",
    targetSelector: route.targetSelector || route.target_selector || route.target || "",
    autoSolve,
    routeStatus: status,
    proposalId: route.proposalId || route.proposal_id || "",
    lastSubmittedAt: route.lastSubmittedAt || route.last_submitted_at || route.submittedAt || route.submitted_at || route.proposedAt || route.proposed_at || null,
    learningConsent: route.learningConsent === true || route.learning_consent === true,
    updatedAt: route.updatedAt || route.updated_at || config.updatedAt || config.updated_at || null,
    raw: route
  };
}

function captchaRowsForConfig(domain, config = {}) {
  const routeMap = config.routes && typeof config.routes === "object" && !Array.isArray(config.routes)
    ? config.routes
    : null;
  if (routeMap && Object.keys(routeMap).length) {
    return Object.entries(routeMap).map(([routeId, route]) => normalizeCaptchaRoute(domain, routeId, route, config));
  }
  const hasLegacyRoute = !!(
    config.sourceSelector
    || config.source_selector
    || config.source
    || config.targetSelector
    || config.target_selector
    || config.target
  );
  if (!hasLegacyRoute) return [];
  return [normalizeCaptchaRoute(domain, config.fieldName || config.field_name || config.id || domain, config, config)];
}

function captchaRouteMapForConfig(domain, config = {}) {
  return Object.fromEntries(captchaRowsForConfig(domain, config).map((route) => [
    route.routeId,
    {
      ...(route.raw || {}),
      id: route.routeId,
      domain,
      profileId: route.profileId,
      profileIds: route.profileIds,
      fieldName: route.fieldName,
      taskType: route.taskType,
      sourceSelector: route.sourceSelector,
      targetSelector: route.targetSelector,
      autoSolve: route.autoSolve,
      routeStatus: route.routeStatus,
      proposalId: route.proposalId,
      lastSubmittedAt: route.lastSubmittedAt,
      learningConsent: route.learningConsent,
      updatedAt: route.updatedAt || Date.now()
    }
  ]));
}

function writeCaptchaDomainConfig(next, domain, routes, activeFieldName = "") {
  const routeKeys = Object.keys(routes);
  if (!routeKeys.length) {
    delete next[domain];
    return;
  }
  next[domain] = {
    id: domain,
    domain,
    activeFieldName: activeFieldName && routes[activeFieldName] ? activeFieldName : routeKeys[0],
    routes,
    updatedAt: Date.now()
  };
}

function resetCaptchaEditor() {
  state.selectedCaptchaDomain = "";
  state.selectedCaptchaRouteId = "";
  setValue("captcha-domain-orig", "");
  setValue("captcha-domain", "");
  appendProfileOptions($("captcha-profile-id"), DEFAULT_PROFILE_ID);
  setValue("captcha-field-name", "");
  setValue("captcha-source-selector", "");
  setValue("captcha-target-selector", "");
  setChecked("captcha-auto-solve", false);
  setText("captcha-editor-title", "Record CAPTCHA Route");
  renderCaptchaConfigs();
}

function renderCaptchaConfigs() {
  const tbody = $("captcha-configs-table");
  clearTable(tbody);
  const entries = Object.entries(state.captchaSelectors || {});
  if (!entries.length) {
    appendEmptyRow(tbody, 6, "No CAPTCHA routes saved");
    return;
  }
  const query = String(state.captchaSearch || "").trim().toLowerCase();
  let rendered = 0;
  for (const [domain, config] of entries) {
    const routes = captchaRowsForConfig(domain, config);
    for (const route of routes) {
      if (!routeMatchesProfile(route)) continue;
      if (query && ![
        domain,
        route.fieldName,
        route.taskType,
        route.sourceSelector,
        route.targetSelector,
        route.autoSolve ? "auto" : "manual",
        captchaStatusLabel(route)
      ].some((value) => matchesText(value, query))) {
        continue;
      }
      const row = document.createElement("tr");
      row.dataset.domain = domain;
      row.dataset.routeId = route.routeId;
      row.classList.toggle(
        "selected",
        domain === state.selectedCaptchaDomain && route.routeId === (state.selectedCaptchaRouteId || route.routeId)
      );
      const domainCell = document.createElement("td");
      domainCell.append(node("div", "admin-mono", domain));
      domainCell.append(chip(captchaStatusLabel(route), captchaStatusTone(route)));

      const fieldCell = document.createElement("td");
      fieldCell.append(node("div", "admin-primary", route.fieldName));
      fieldCell.append(chip(route.taskType || "image", "muted"));

      const sourceCell = document.createElement("td");
      sourceCell.append(chip(route.sourceSelector || "-", "mono"));

      const targetCell = document.createElement("td");
      targetCell.append(chip(route.targetSelector || "-", "mono"));

      const modeCell = document.createElement("td");
      const toggle = node("button", `mini-switch ${route.autoSolve ? "on" : ""}`.trim(), "");
      toggle.type = "button";
      toggle.setAttribute("role", "switch");
      toggle.setAttribute("aria-checked", route.autoSolve ? "true" : "false");
      toggle.title = route.autoSolve ? "Disable autosolve" : "Enable autosolve";
      toggle.addEventListener("click", () => handle(() => setCaptchaRouteEnabled(domain, route.routeId, !route.autoSolve), route.autoSolve ? "CAPTCHA route disabled" : "CAPTCHA route enabled"));
      toggle.append(node("span", "mini-switch-knob"));
      const modeWrap = node("div", "route-mode-wrap");
      modeWrap.append(toggle, chip(route.autoSolve ? "Auto" : "Manual", route.autoSolve ? "success" : "muted"));
      modeCell.append(modeWrap);

      const actionsCell = document.createElement("td");
      const actions = node("div", "row-actions captcha-actions");
      const editBtn = actionButton("Edit");
      editBtn.addEventListener("click", () => selectCaptchaConfig(domain, route.routeId));
      const deleteBtn = actionButton("Delete", "icon-text-btn danger");
      deleteBtn.addEventListener("click", () => handle(() => deleteCaptchaRoute(domain, route.routeId), "CAPTCHA route deleted"));
      actions.append(editBtn, deleteBtn);
      if (!isCaptchaRouteApproved(route)) {
        const waitMs = captchaRouteSubmitWaitMs(route);
        const resendBtn = actionButton(waitMs > 0 ? "Submitted" : "Send to Server");
        resendBtn.disabled = waitMs > 0;
        if (waitMs > 0) resendBtn.title = `Available again in ${captchaRouteSubmitCooldownLabel(waitMs)}`;
        resendBtn.addEventListener("click", () => handle(() => resendCaptchaRoute(domain, route.routeId), "CAPTCHA route submitted"));
        actions.append(resendBtn);
      }
      actionsCell.append(actions);

      row.append(domainCell, fieldCell, sourceCell, targetCell, modeCell, actionsCell);
      row.addEventListener("dblclick", () => selectCaptchaConfig(domain, route.routeId));
      tbody.append(row);
      rendered += 1;
    }
  }
  if (!rendered) appendEmptyRow(tbody, 6, "No matching CAPTCHA routes");
}

function selectCaptchaConfig(domain, routeId = "") {
  state.selectedCaptchaDomain = domain || "";
  state.selectedCaptchaRouteId = routeId || "";
  const config = domain ? state.captchaSelectors?.[domain] || {} : {};
  const routes = captchaRouteMapForConfig(domain, config);
  const route = routeId && routes[routeId] ? routes[routeId] : {};
  setValue("captcha-domain-orig", domain || "");
  setValue("captcha-domain", domain || "");
  appendProfileOptions($("captcha-profile-id"), routeMatchesProfile(route) ? activeProfileId() : (route.profileId || DEFAULT_PROFILE_ID));
  setValue("captcha-field-name", route.fieldName || route.field_name || routeId || "");
  setValue("captcha-source-selector", route.sourceSelector || route.source_selector || route.source || "");
  setValue("captcha-target-selector", route.targetSelector || route.target_selector || route.target || "");
  setChecked("captcha-auto-solve", route.autoSolve === true || route.auto_solve === true);
  setText("captcha-editor-title", routeId ? "Edit CAPTCHA Route" : "Record CAPTCHA Route");
  renderCaptchaConfigs();
  requestAnimationFrame(() => {
    const title = $("captcha-editor-title");
    title?.scrollIntoView({ behavior: "smooth", block: "start" });
    $("captcha-domain")?.focus();
  });
}

function focusAccountSignup() {
  activatePanel("account-panel");
  requestAnimationFrame(() => {
    $("account-disconnected-view")?.scrollIntoView({ behavior: "smooth", block: "start" });
    $("options-signup-identifier")?.focus();
  });
}

function renderBilling() {
  const plansGrid = $("plans-grid");
  const creditsGrid = $("credits-grid");
  const authenticated = isAuthenticated();
  if (plansGrid) plansGrid.replaceChildren();
  if (creditsGrid) creditsGrid.replaceChildren();

  if (!state.plans.length) {
    if (plansGrid) plansGrid.append(createEmptyCard("Plans will appear here after the backend responds. Click Refresh if this stays empty."));
  }

  const billingProvider = preferredBillingProvider();

  const activeCode = currentPlanCode();
  for (const plan of state.plans) {
    const card = document.createElement("article");
    const planCode = String(plan.code || "").toLowerCase();
    const isCurrent = !!activeCode && planCode === activeCode;
    card.className = ["plan-card", plan.features?.priority_solving ? "premium" : "", isCurrent ? "current" : ""].filter(Boolean).join(" ");

    const title = document.createElement("h4");
    title.textContent = plan.name || plan.code || "Backend Plan";
    card.append(title);

    const priceBox = document.createElement("div");
    priceBox.className = "plan-price-box";
    const price = priceLabel(plan.price || { amount: plan.price_amount || 0, currency: plan.currency || "INR" });
    const [currency, ...amountParts] = price.split(" ");
    const currencyNode = document.createElement("span");
    currencyNode.className = "plan-price-currency";
    currencyNode.textContent = amountParts.length ? currency : "";
    const amountNode = document.createElement("span");
    amountNode.className = "plan-price";
    amountNode.textContent = amountParts.length ? amountParts.join(" ") : price;
    const periodNode = document.createElement("span");
    periodNode.className = "plan-price-period";
    periodNode.textContent = Number(plan.price?.amount || plan.price_amount || 0) > 0 ? `/${plan.duration_days || 30} days` : "";
    priceBox.append(currencyNode, amountNode, periodNode);
    card.append(priceBox);

    const credits = document.createElement("div");
    credits.className = "plan-credits";
    credits.textContent = plan.description || `${compactNumber(plan.limits?.captcha_daily_limit || 0)} CAPTCHA credits`;
    card.append(credits);

    const features = document.createElement("ul");
    features.className = "plan-features";
    for (const label of planFeatureLabels(plan).slice(0, 4)) {
      const item = document.createElement("li");
      item.textContent = label;
      features.append(item);
    }
    card.append(features);

    const button = document.createElement("button");
    button.className = authenticated ? "primary-btn choose-plan-btn" : "secondary-btn choose-plan-btn";
    button.disabled = isCurrent;
    button.textContent = isCurrent
      ? "Current Plan"
      : authenticated
        ? `Continue with ${billingProviderLabel(billingProvider)}`
        : "Sign In First";
    if (!isCurrent) {
      button.addEventListener("click", () => {
        if (!authenticated) {
          focusAccountSignup();
          toast("Sign in first, then choose a plan.", "info");
          return;
        }
        handle(() => createBillingOrder(plan), "Order created");
      });
    }
    card.append(button);

    if (plansGrid) plansGrid.append(card);
  }

  setHidden("credit-packs-surface", !state.creditPacks.length);

  for (const pack of state.creditPacks) {
    const card = document.createElement("article");
    card.className = "plan-card";

    const title = document.createElement("h4");
    title.textContent = pack.name || pack.code || "Credit Pack";
    card.append(title);

    const priceBox = document.createElement("div");
    priceBox.className = "plan-price-box";
    const label = priceLabel(pack.price || { amount: pack.price_amount || 0, currency: pack.currency || "INR" });
    const [currency, ...amountParts] = label.split(" ");
    const currencyNode = document.createElement("span");
    currencyNode.className = "plan-price-currency";
    currencyNode.textContent = amountParts.length ? currency : "";
    const amountNode = document.createElement("span");
    amountNode.className = "plan-price";
    amountNode.textContent = amountParts.length ? amountParts.join(" ") : label;
    priceBox.append(currencyNode, amountNode);
    card.append(priceBox);

    const credits = document.createElement("div");
    credits.className = "plan-credits";
    credits.textContent = pack.credits || pack.description || "Backend-managed add-on";
    card.append(credits);

    const button = document.createElement("button");
    button.className = "secondary-btn buy-pack-btn";
    button.textContent = authenticated ? `Buy with ${billingProviderLabel(billingProvider)}` : "Sign In First";
    button.addEventListener("click", () => {
      if (!authenticated) {
        focusAccountSignup();
        toast("Sign in first, then buy credits.", "info");
        return;
      }
      handle(() => createBillingOrder(pack), "Order created");
    });
    card.append(button);

    if (creditsGrid) creditsGrid.append(card);
  }

  const usageTbody = $("usage-history-table");
  clearTable(usageTbody);
  if (!state.usageHistory.length) {
    appendEmptyRow(usageTbody, 5, "No usage history yet");
  } else {
    for (const item of state.usageHistory) {
      const row = document.createElement("tr");
      const start = item.cycle_start || item.cycleStart || item.date || "";
      const end = item.cycle_end || item.cycleEnd || item.resets_at || "";
      const used = item.captcha_used ?? item.used ?? 0;
      const limit = item.captcha_limit ?? item.limit ?? 0;
      const remaining = item.captcha_remaining ?? item.remaining ?? Math.max(0, Number(limit || 0) - Number(used || 0));
      for (const text of [
        `${formatDate(start)} - ${formatDate(end)}`,
        used,
        limit,
        remaining,
        item.blocked ? "Limit reached" : "OK"
      ]) {
        const cell = document.createElement("td");
        cell.textContent = String(text);
        row.append(cell);
      }
      usageTbody.append(row);
    }
  }

  const tbody = $("payments-table");
  clearTable(tbody);
  if (!state.payments.length) {
    appendEmptyRow(tbody, 4, "No payments yet");
    return;
  }
  for (const payment of state.payments) {
    const row = document.createElement("tr");
    for (const text of [
      `#${payment.id}`,
      payment.plan_name || payment.plan_code || payment.plan_id || "--",
      `${payment.currency || "INR"} ${(Number(payment.amount || 0) / 100).toFixed(2)}`,
      payment.status || "--"
    ]) {
      const cell = document.createElement("td");
      cell.textContent = String(text);
      row.append(cell);
    }
    tbody.append(row);
  }
}

function selectRule(id) {
  state.selectedRuleId = id;
  const rule = id ? (state.rules.find((item) => item.id === id) || { steps: [] }) : { steps: [] };
  renderProfileOptions();
  $("rule-id").value = id || "";
  $("rule-name").value = rule.name || "";
  $("rule-domain").value = rule.domain || rule.site?.pattern || "";
  if ($("rule-profile-id")) $("rule-profile-id").value = id ? itemProfileId(rule) : DEFAULT_PROFILE_ID;
  $("rule-enabled").checked = rule.enabled !== false;

  setHidden("rules-list-view", true);
  setHidden("rules-editor-view", false);

  renderRuleSteps(rule.steps || []);
}

function selectorDisplayValue(selector) {
  if (!selector) return "";
  if (typeof selector === "string") return selector;
  return selector.css || selector.primary || selector.xpath || "";
}

function selectorJson(selector) {
  try {
    return JSON.stringify(selector || {});
  } catch (_) {
    return "{}";
  }
}

function readSelectorFromRow(row, selectorInput) {
  const raw = selectorInput?.value?.trim() || "";
  let preserved = {};
  try {
    preserved = JSON.parse(row.dataset.selectorJson || "{}");
  } catch (_) {
    preserved = {};
  }
  if (!preserved || typeof preserved !== "object" || Array.isArray(preserved)) {
    return raw;
  }
  const next = { ...preserved };
  if (raw) {
    next.primary = raw;
    if (!raw.startsWith("/")) next.css = raw;
    else next.xpath = raw;
  }
  return next.primary || next.css || next.xpath ? next : raw;
}

function editorActionForStep(step = {}) {
  if (step.action === "text") return "set_value";
  if (step.action === "checkbox") {
    return ["false", "0", "off", "no"].includes(String(step.value).toLowerCase()) || step.value === false ? "uncheck" : "check";
  }
  return step.action || "set_value";
}

function renderRuleSteps(steps) {
  const container = $("rule-steps-container");
  if (!container) return;
  container.replaceChildren();
  if (!steps.length) {
    const empty = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 6;
    cell.className = "table-empty-cell";
    cell.textContent = "No steps recorded. Add one manually or use the Visual Recorder.";
    empty.append(cell);
    container.append(empty);
    return;
  }
  steps.forEach((step, index) => {
    const selectedAction = editorActionForStep(step);
    const stepEl = document.createElement("tr");
    stepEl.className = "step-row";
    stepEl.dataset.index = index;
    stepEl.dataset.selectorJson = selectorJson(step.selector);
    stepEl.dataset.runtimeJson = selectorJson(step.runtime || {});
    stepEl.dataset.elementJson = selectorJson(step.element || {});
    stepEl.dataset.metaJson = selectorJson(step.meta || {});
    stepEl.setAttribute("draggable", "true");

    const dragCell = document.createElement("td");
    dragCell.className = "drag-handle text-center";
    dragCell.setAttribute("draggable", "false");
    dragCell.textContent = "::";

    const actionCell = document.createElement("td");
    const actionSelect = document.createElement("select");
    actionSelect.className = "step-action autofill-select";
    [
      ["set_value", "Set Value"],
      ["select", "Select"],
      ["click", "Click"],
      ["check", "Check"],
      ["uncheck", "Uncheck"],
      ["radio", "Radio"],
      ["wait", "Wait"]
    ].forEach(([value, label]) => {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      option.selected = selectedAction === value;
      actionSelect.append(option);
    });
    actionCell.append(actionSelect);

    const selectorCell = document.createElement("td");
    const nameContainer = document.createElement("div");
    nameContainer.className = "name-container";
    const labelInput = document.createElement("input");
    labelInput.type = "text";
    labelInput.className = "step-label autofill-input";
    labelInput.value = step.label || "";
    labelInput.placeholder = "Field Label (e.g. Email)";
    const selectorInput = document.createElement("input");
    selectorInput.type = "text";
    selectorInput.className = "step-selector autofill-input secondary-input";
    selectorInput.value = selectorDisplayValue(step.selector);
    selectorInput.placeholder = "CSS Selector (e.g. #email)";
    nameContainer.append(labelInput, selectorInput);
    selectorCell.append(nameContainer);

    const valueCell = document.createElement("td");
    const valueContainer = document.createElement("div");
    valueContainer.className = "value-container";
    const valueInput = document.createElement("input");
    valueInput.type = "text";
    valueInput.className = "step-value autofill-input";
    valueInput.value = String(step.value ?? "");
    valueInput.placeholder = "Value (e.g. {@email})";
    const editButton = document.createElement("button");
    editButton.className = "edit-badge-btn";
    editButton.type = "button";
    editButton.title = "Edit text value";
    editButton.textContent = "Edit";
    valueContainer.append(valueInput, editButton);
    valueCell.append(valueContainer);

    const siteCell = document.createElement("td");
    const siteBadge = document.createElement("span");
    siteBadge.className = "site-badge";
    siteBadge.textContent = $("rule-domain")?.value || "*";
    siteCell.append(siteBadge);

    const removeCell = document.createElement("td");
    removeCell.className = "text-center";
    const removeButton = document.createElement("button");
    removeButton.className = "remove-step-btn autofill-remove";
    removeButton.type = "button";
    removeButton.title = "Remove Step";
    removeButton.textContent = "-";
    removeCell.append(removeButton);
    stepEl.append(dragCell, actionCell, selectorCell, valueCell, siteCell, removeCell);

    // Drag and Drop Event Listeners
    stepEl.addEventListener("dragstart", (e) => {
      e.dataTransfer.setData("text/plain", index);
      stepEl.classList.add("dragging");
    });

    stepEl.addEventListener("dragover", (e) => {
      e.preventDefault();
      const draggingEl = container.querySelector(".dragging");
      if (draggingEl && draggingEl !== stepEl) {
        stepEl.classList.add("drag-over");
      }
    });

    stepEl.addEventListener("dragleave", () => {
      stepEl.classList.remove("drag-over");
    });

    stepEl.addEventListener("dragend", () => {
      stepEl.classList.remove("dragging");
      container.querySelectorAll(".step-row").forEach(row => row.classList.remove("drag-over"));
    });

    stepEl.addEventListener("drop", (e) => {
      e.preventDefault();
      stepEl.classList.remove("drag-over");
      const dragIndex = parseInt(e.dataTransfer.getData("text/plain"), 10);
      const dropIndex = index;

      if (isNaN(dragIndex) || dragIndex === dropIndex) return;

      const currentSteps = readRuleSteps();
      const [movedItem] = currentSteps.splice(dragIndex, 1);
      currentSteps.splice(dropIndex, 0, movedItem);

      currentSteps.forEach((s, idx) => s.order = idx + 1);

      renderRuleSteps(currentSteps);
      toast("Steps reordered", "success");
    });

    stepEl.querySelector(".remove-step-btn").addEventListener("click", () => {
      const currentSteps = readRuleSteps();
      currentSteps.splice(index, 1);
      renderRuleSteps(currentSteps);
    });

    const ruleDomainInput = $("rule-domain");
    if (ruleDomainInput) {
      ruleDomainInput.addEventListener("input", () => {
        const badge = stepEl.querySelector(".site-badge");
        if (badge) badge.textContent = ruleDomainInput.value || "*";
      });
    }

    container.append(stepEl);
  });
}

function readRuleSteps() {
  const container = $("rule-steps-container");
  if (!container) return [];
  const steps = [];
  container.querySelectorAll("tr.step-row").forEach((el, index) => {
    const labelEl = el.querySelector(".step-label");
    const actionEl = el.querySelector(".step-action");
    const selectorEl = el.querySelector(".step-selector");
    const valueEl = el.querySelector(".step-value");
    if (actionEl && selectorEl && valueEl) {
      let runtime = {};
      let element = {};
      let meta = {};
      try { runtime = JSON.parse(el.dataset.runtimeJson || "{}"); } catch (_) {}
      try { element = JSON.parse(el.dataset.elementJson || "{}"); } catch (_) {}
      try { meta = JSON.parse(el.dataset.metaJson || "{}"); } catch (_) {}
      steps.push({
        order: index + 1,
        label: labelEl ? labelEl.value : "",
        action: actionEl.value,
        selector: readSelectorFromRow(el, selectorEl),
        value: valueEl.value,
        required: false,
        runtime,
        element,
        meta
      });
    }
  });
  return steps;
}

async function saveSettings() {
  state.settings = {
    ...state.settings,
    activeProfileId: activeProfileId(),
    captchaEnabled: $("setting-captcha")?.checked !== false,
    captchaFillDelayMs: normalizeCaptchaDelay($("captcha-fill-delay")?.value),
    captchaHumanTyping: $("captcha-human-typing")?.checked === true,
    captchaLearningConsent: $("captcha-learning-consent")?.checked === true,
    autofillEnabled: $("setting-autofill")?.checked !== false,
    userscriptsEnabled: $("setting-userscripts")?.checked !== false,
    syncEnabled: !!$("setting-sync")?.checked,
    apiBaseUrl: $("setting-api-base")?.value.trim() || DEFAULT_SETTINGS.apiBaseUrl,
    theme: $("setting-theme")?.value || DEFAULT_SETTINGS.theme
  };
  await setStorage({ fp_settings: state.settings });
  await sendMessage({ type: "CAPTCHA_CONFIG_UPDATED" }).catch(() => null);
  updateTheme();
  renderStatus();
  renderSettings();
}

async function saveRule() {
  const now = Date.now();
  const id = $("rule-id").value || state.selectedRuleId || makeId("rule");
  const existing = state.rules.find((item) => item.id === id) || {};
  const domain = $("rule-domain").value.trim();
  const existingSite = existing.site || {};
  const site = {
    ...existingSite,
    matchMode: existingSite.matchMode || existingSite.match_mode || "domain",
    pattern: domain || existingSite.pattern || existing.domain || "*"
  };
  if (existingSite.path) site.path = existingSite.path;
  const ruleType = existing.ruleType || existing.rule_type || existing.execution?.mode || "instant";
  const profileId = $("rule-profile-id") ? $("rule-profile-id").value : DEFAULT_PROFILE_ID;
  const rule = {
    ...existing,
    id,
    schemaVersion: existing.schemaVersion || existing.schema_version || 2,
    name: $("rule-name").value.trim() || "Untitled Rule",
    domain: domain || existing.domain || site.pattern,
    site,
    ruleType,
    execution: {
      ...(existing.execution || {}),
      mode: ruleType,
      delayMs: existing.execution?.delayMs ?? existing.execution?.delay_ms ?? 100,
      waitTimeoutMs: existing.execution?.waitTimeoutMs ?? existing.execution?.wait_timeout_ms ?? 3000,
      runOnce: existing.execution?.runOnce ?? existing.execution?.run_once ?? true,
      stopOnError: existing.execution?.stopOnError ?? existing.execution?.stop_on_error ?? ruleType === "flow"
    },
    priority: Number(existing.priority ?? 100),
    profileId,
    profileIds: [...new Set([...(existing.profileIds || existing.profile_ids || []), profileId].map(normalizedProfileId))],
    enabled: $("rule-enabled").checked,
    steps: readRuleSteps(),
    createdAt: existing.createdAt || now,
    updatedAt: now
  };
  state.rules = [...state.rules.filter((item) => item.id !== id), rule];

  setHidden("rules-editor-view", true);
  setHidden("rules-list-view", false);

  state.selectedRuleId = null;
  await setStorage({ fp_rules: state.rules });
  renderRules();
  renderProfiles();
  renderStatus();
}

async function deleteRule() {
  const id = $("rule-id").value || state.selectedRuleId;
  if (!id) return;
  state.rules = state.rules.filter((item) => item.id !== id);
  state.selectedRuleIds.delete(id);
  state.selectedRuleId = null;

  setHidden("rules-editor-view", true);
  setHidden("rules-list-view", false);

  await setStorage({ fp_rules: state.rules });
  renderRules();
  renderProfiles();
  renderStatus();
}

async function setRuleEnabled(ruleId, enabled) {
  if (!ruleId) return;
  const now = Date.now();
  state.rules = state.rules.map((rule) => (
    rule.id === ruleId ? { ...rule, enabled: !!enabled, updatedAt: now } : rule
  ));
  await setStorage({ fp_rules: state.rules });
  renderRules();
  renderStatus();
}

async function deleteRuleById(ruleId) {
  if (!ruleId) return;
  if (!window.confirm("Delete this autofill rule?")) return;
  state.rules = state.rules.filter((item) => item.id !== ruleId);
  state.selectedRuleIds.delete(ruleId);
  if (state.selectedRuleId === ruleId) {
    state.selectedRuleId = null;
    setHidden("rules-editor-view", true);
    setHidden("rules-list-view", false);
  }
  await setStorage({ fp_rules: state.rules });
  renderRules();
  renderProfiles();
  renderStatus();
}

async function setSelectedRulesEnabled(enabled) {
  if (!state.selectedRuleIds.size) return;
  const selected = new Set(state.selectedRuleIds);
  const now = Date.now();
  state.rules = state.rules.map((rule) => (
    selected.has(rule.id) ? { ...rule, enabled: !!enabled, updatedAt: now } : rule
  ));
  await setStorage({ fp_rules: state.rules });
  renderRules();
  renderStatus();
}

async function deleteSelectedRules() {
  if (!state.selectedRuleIds.size) return;
  const count = state.selectedRuleIds.size;
  if (!window.confirm(`Delete ${count} selected rule${count === 1 ? "" : "s"}?`)) return;
  const selected = new Set(state.selectedRuleIds);
  state.rules = state.rules.filter((rule) => !selected.has(rule.id));
  if (selected.has(state.selectedRuleId)) {
    state.selectedRuleId = null;
    if ($("rule-name")) $("rule-name").value = "";
    if ($("rule-domain")) $("rule-domain").value = "";
  }
  state.selectedRuleIds.clear();
  await setStorage({ fp_rules: state.rules });
  renderRules();
  renderProfiles();
  renderStatus();
}

function setAllVisibleRulesSelected(selected) {
  for (const rule of filteredRules()) {
    if (selected) state.selectedRuleIds.add(rule.id);
    else state.selectedRuleIds.delete(rule.id);
  }
  renderRules();
}

async function saveProfile() {
  const now = Date.now();
  const id = ($("profile-id").value.trim() || state.selectedProfileId || makeId("profile")).replace(/[^a-zA-Z0-9_-]/g, "_");
  const existing = state.profiles.find((item) => item.id === id) || {};
  const profile = {
    ...existing,
    id,
    name: $("profile-name").value.trim() || "Untitled Profile",
    values: existing.values || existing.data || existing.fields || {},
    createdAt: existing.createdAt || now,
    updatedAt: now
  };
  state.profiles = [...state.profiles.filter((item) => item.id !== id), profile];
  state.selectedProfileId = id;
  await setStorage({ fp_profiles: state.profiles });
  renderProfiles();
  renderStatus();
}

async function deleteProfile() {
  if (!state.selectedProfileId) return;
  const deletedProfileId = state.selectedProfileId;
  state.profiles = state.profiles.filter((item) => item.id !== state.selectedProfileId);
  state.rules = state.rules.map((rule) => (
    itemMatchesProfile(rule, deletedProfileId)
      ? { ...(removeItemProfile(rule, deletedProfileId) || { ...rule, profileId: DEFAULT_PROFILE_ID, profileIds: [DEFAULT_PROFILE_ID] }), updatedAt: Date.now() }
      : rule
  ));
  state.scripts = state.scripts.map((script) => (
    itemMatchesProfile(script, deletedProfileId)
      ? { ...(removeItemProfile(script, deletedProfileId) || { ...script, profileId: DEFAULT_PROFILE_ID, profileIds: [DEFAULT_PROFILE_ID] }), updatedAt: Date.now() }
      : script
  ));
  state.captchaSelectors = rewriteCaptchaRoutesForDeletedProfile(state.captchaSelectors, deletedProfileId);
  if (activeProfileId() === deletedProfileId) state.settings.activeProfileId = DEFAULT_PROFILE_ID;
  state.selectedProfileId = null;
  $("profile-name").value = "";
  $("profile-id").value = "";
  await setStorage({
    fp_profiles: state.profiles,
    fp_rules: state.rules,
    fp_scripts: state.scripts,
    fp_captcha_selectors: state.captchaSelectors,
    fp_settings: state.settings
  });
  await registerUserscripts().catch(() => null);
  await sendMessage({ type: "CAPTCHA_CONFIG_UPDATED" }).catch(() => null);
  renderProfiles();
  renderRules();
  renderScripts();
  renderCaptchaConfigs();
  renderStatus();
}

async function saveScript() {
  const now = Date.now();
  const id = state.selectedScriptId || makeId("script");
  const name = $("script-name").value.trim() || "Untitled Script";
  const version = $("script-version")?.value.trim() || "1.0.0";
  const match = $("script-match").value.trim() || "https://*/*";
  const rawCode = scriptEditor ? scriptEditor.state.doc.toString() : scriptTemplate(name, match, version);
  const existing = state.scripts.find((item) => item.id === id) || {};
  if (existing.id && isRemoteUserscript(existing)) {
    throw new Error("URL-managed scripts cannot be edited here. Refresh from URL or delete the script.");
  }
  const parsedMeta = parseScriptMeta(rawCode, name, match, version);
  const requiredCode = await fetchRequiredCode(parsedMeta.requires, existing.sourceUrl || parsedMeta.updateURL || parsedMeta.downloadURL || location.href);
  const script = {
    ...existing,
    id,
    name: parsedMeta.name || name,
    version: parsedMeta.version || version,
    profileId: $("script-profile-id")?.value || DEFAULT_PROFILE_ID,
    profileIds: [...new Set([...(existing.profileIds || existing.profile_ids || []), $("script-profile-id")?.value || DEFAULT_PROFILE_ID].map(normalizedProfileId))],
    enabled: $("script-enabled").checked,
    source: "local",
    sourceUrl: "",
    updateUrl: parsedMeta.updateURL || parsedMeta.downloadURL || "",
    autoUpdate: false,
    rawCode,
    requiredCode,
    parsedMeta,
    installedAt: existing.installedAt || now,
    updatedAt: now,
    lastError: null,
    storageUsedBytes: existing.storageUsedBytes || 0
  };
  state.scripts = [...state.scripts.filter((item) => item.id !== id), script];
  state.selectedScriptId = null;
  await setStorage({ fp_scripts: state.scripts });
  await registerUserscripts();
  closeScriptEditor({ clearSelection: false });
  renderScripts();
  renderProfiles();
  renderStatus();
}

function normalizeDomain(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  try {
    return new URL(raw.includes("://") ? raw : `https://${raw}`).hostname.replace(/^www\./, "").toLowerCase();
  } catch (_) {
    return raw.split("/")[0].replace(/^www\./, "").toLowerCase();
  }
}

function normalizeCaptchaDelay(value) {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 0;
  return Math.max(0, Math.min(30000, Math.round(parsed)));
}

async function saveCaptchaConfig() {
  const domain = normalizeDomain($("captcha-domain").value);
  if (!domain) throw new Error("Enter a domain");
  const sourceSelector = $("captcha-source-selector").value.trim();
  const targetSelector = $("captcha-target-selector").value.trim();
  if (!sourceSelector || !targetSelector) throw new Error("Source and target selectors are required");
  const next = { ...(state.captchaSelectors || {}) };
  const profileId = $("captcha-profile-id")?.value || DEFAULT_PROFILE_ID;
  const selectedRouteId = state.selectedCaptchaRouteId || "";
  const previousDomain = normalizeDomain($("captcha-domain-orig")?.value || state.selectedCaptchaDomain || domain);
  const previousConfig = next[previousDomain] || {};
  const previousRoutes = captchaRouteMapForConfig(previousDomain, previousConfig);
  const existingSelectedRoute = selectedRouteId ? previousRoutes[selectedRouteId] || {} : {};
  const targetConfig = previousDomain === domain ? previousConfig : (next[domain] || {});
  const targetRoutes = captchaRouteMapForConfig(domain, targetConfig);
  const autoSolve = $("captcha-auto-solve").checked;
  const stableRouteId = await stableCaptchaFieldName(domain, sourceSelector, targetSelector);
  const duplicateRouteId = Object.entries(targetRoutes).find(([routeId, route]) => (
    routeId !== selectedRouteId && sameCaptchaRoute(route, sourceSelector, targetSelector)
  ))?.[0] || "";
  const routeId = duplicateRouteId || stableRouteId;
  if (selectedRouteId && previousDomain === domain && selectedRouteId !== routeId) {
    const detached = removeRouteProfile(targetRoutes[selectedRouteId], profileId);
    if (detached) targetRoutes[selectedRouteId] = detached;
    else delete targetRoutes[selectedRouteId];
  }
  if (selectedRouteId && previousDomain && previousDomain !== domain) {
    const detached = removeRouteProfile(previousRoutes[selectedRouteId], profileId);
    if (detached) previousRoutes[selectedRouteId] = detached;
    else delete previousRoutes[selectedRouteId];
    writeCaptchaDomainConfig(next, previousDomain, previousRoutes, previousConfig.activeFieldName);
  }
  const existingRoute = targetRoutes[routeId] || existingSelectedRoute || {};
  const requestedFieldName = $("captcha-field-name")?.value.trim() || "";
  const routeStatus = existingRoute.routeStatus || existingRoute.route_status || existingRoute.status || (existingRoute.autoSolve === true ? "approved" : "local_only");
  const updatedRoute = {
    ...withRouteProfile(existingRoute, profileId),
    id: routeId,
    domain,
    profileId,
    profileIds: routeProfileIds(withRouteProfile(existingRoute, profileId)),
    fieldName: requestedFieldName || existingRoute.fieldName || existingRoute.field_name || routeId,
    sourceSelector,
    targetSelector,
    taskType: "image",
    autoSolve,
    routeStatus,
    proposalId: existingRoute.proposalId || existingRoute.proposal_id || "",
    lastSubmittedAt: existingRoute.lastSubmittedAt || existingRoute.last_submitted_at || null,
    learningConsent: existingRoute.learningConsent === true || state.settings.captchaLearningConsent === true,
    updatedAt: Date.now()
  };
  targetRoutes[routeId] = updatedRoute;
  writeCaptchaDomainConfig(next, domain, targetRoutes, routeId);
  state.captchaSelectors = next;
  state.selectedCaptchaDomain = domain;
  state.selectedCaptchaRouteId = routeId;
  setValue("captcha-domain-orig", domain);
  setValue("captcha-field-name", updatedRoute.fieldName);
  await setStorage({ fp_captcha_selectors: next });
  await sendMessage({ type: "CAPTCHA_CONFIG_UPDATED" }).catch(() => null);
  renderCaptchaConfigs();
  renderProfiles();
}

async function setCaptchaRouteEnabled(domain, routeId, enabled) {
  const next = { ...(state.captchaSelectors || {}) };
  const config = next[domain] || {};
  const routes = captchaRouteMapForConfig(domain, config);
  if (!routes[routeId]) return;
  routes[routeId] = { ...routes[routeId], autoSolve: !!enabled, updatedAt: Date.now() };
  writeCaptchaDomainConfig(next, domain, routes, routeId);
  state.captchaSelectors = next;
  await setStorage({ fp_captcha_selectors: next });
  await sendMessage({ type: "CAPTCHA_CONFIG_UPDATED" }).catch(() => null);
  renderCaptchaConfigs();
  renderProfiles();
}

async function deleteCaptchaRoute(domain, routeId) {
  if (!domain || !routeId) return;
  if (!window.confirm("Delete this CAPTCHA route?")) return;
  const next = { ...(state.captchaSelectors || {}) };
  const config = next[domain] || {};
  const routes = captchaRouteMapForConfig(domain, config);
  if (!routes[routeId]) return;
  const detached = removeRouteProfile(routes[routeId], activeProfileId());
  if (detached) routes[routeId] = detached;
  else delete routes[routeId];
  writeCaptchaDomainConfig(next, domain, routes, config.activeFieldName);
  if (state.selectedCaptchaDomain === domain && state.selectedCaptchaRouteId === routeId) {
    state.selectedCaptchaDomain = "";
    state.selectedCaptchaRouteId = "";
    resetCaptchaEditor();
  } else {
    state.captchaSelectors = next;
  }
  state.captchaSelectors = next;
  await setStorage({ fp_captcha_selectors: next });
  await sendMessage({ type: "CAPTCHA_CONFIG_UPDATED" }).catch(() => null);
  renderCaptchaConfigs();
  renderProfiles();
}

async function resendCaptchaRoute(domain, routeId) {
  const config = state.captchaSelectors?.[domain] || {};
  const route = captchaRouteMapForConfig(domain, config)[routeId];
  if (!route) throw new Error("CAPTCHA route not found");
  if (isCaptchaRouteApproved(route)) throw new Error("This CAPTCHA route is already approved");
  const waitMs = captchaRouteSubmitWaitMs(route);
  if (waitMs > 0) throw new Error(`Send to server is available again in ${captchaRouteSubmitCooldownLabel(waitMs)}`);
  const sourceSelector = route.sourceSelector || route.source_selector || "";
  const targetSelector = route.targetSelector || route.target_selector || "";
  if (!sourceSelector || !targetSelector) throw new Error("Source and target selectors are required");

  let fieldName = route.fieldName || route.field_name || routeId;
  let routeStatus = route.routeStatus || route.route_status || route.status || "local_only";
  let proposalId = route.proposalId || route.proposal_id || "";
  const statusResponse = await sendMessage({
    type: "CAPTCHA_ROUTE_STATUS",
    payload: {
      domain,
      source_selector: sourceSelector,
      target_selector: targetSelector
    }
  });
  const statusData = statusResponse.data || statusResponse;
  if (statusResponse.ok && statusData.status) {
    routeStatus = statusData.status;
    proposalId = statusData.proposal_id || proposalId;
    fieldName = statusData.field_name || fieldName;
  }
  if (isCaptchaRouteApproved({ routeStatus })) {
    const next = { ...(state.captchaSelectors || {}) };
    const routes = captchaRouteMapForConfig(domain, next[domain] || {});
    routes[routeId] = {
      ...routes[routeId],
      fieldName,
      routeStatus,
      proposalId,
      autoSolve: true,
      updatedAt: Date.now()
    };
    writeCaptchaDomainConfig(next, domain, routes, routeId);
    state.captchaSelectors = next;
    await setStorage({ fp_captcha_selectors: next });
    await sendMessage({ type: "CAPTCHA_CONFIG_UPDATED" }).catch(() => null);
    renderCaptchaConfigs();
    renderProfiles();
    return;
  }

  const proposal = await sendMessage({
    type: "CAPTCHA_ROUTE_PROPOSE",
    payload: {
      domain,
      source_selector: sourceSelector,
      target_selector: targetSelector,
      field_name: fieldName,
      page_url: "",
      learning_consent: state.settings.captchaLearningConsent === true,
      consent_version: state.settings.captchaLearningConsent === true ? "captcha-learning-v1" : "",
      sample_payload_base64: "",
      user_label: "",
      metadata: {}
    }
  });
  if (!proposal.ok) throw new Error(proposal.error || "Could not submit CAPTCHA route");
  routeStatus = proposal.status || proposal.data?.status || routeStatus;
  proposalId = proposal.proposal_id || proposal.data?.proposal_id || proposalId;
  fieldName = proposal.field_name || proposal.data?.field_name || fieldName;

  const next = { ...(state.captchaSelectors || {}) };
  const routes = captchaRouteMapForConfig(domain, next[domain] || {});
  const submittedAt = Date.now();
  routes[routeId] = {
    ...routes[routeId],
    fieldName,
    routeStatus,
    proposalId,
    lastSubmittedAt: submittedAt,
    learningConsent: state.settings.captchaLearningConsent === true,
    updatedAt: submittedAt
  };
  writeCaptchaDomainConfig(next, domain, routes, routeId);
  state.captchaSelectors = next;
  await setStorage({ fp_captcha_selectors: next });
  await sendMessage({ type: "CAPTCHA_CONFIG_UPDATED" }).catch(() => null);
  renderCaptchaConfigs();
  renderProfiles();
}

function normalizeScriptUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) throw new Error("Enter a script URL");
  const url = new URL(raw);
  if (url.protocol !== "https:" && url.protocol !== "http:") throw new Error("Script URL must use http or https");
  if (/^(?:www\.)?greasyfork\.org$/i.test(url.hostname) && !/\.user\.js(?:$|[?#])/i.test(url.href)) {
    const parts = url.pathname.split("/").filter(Boolean);
    const scriptsIndex = parts.findIndex((part) => part.toLowerCase() === "scripts");
    const scriptToken = scriptsIndex >= 0 ? parts[scriptsIndex + 1] || "" : "";
    const idMatch = scriptToken.match(/^(\d+)(?:-(.+))?$/);
    if (idMatch) {
      const slug = idMatch[2] || "script";
      return `${url.origin}/scripts/${idMatch[1]}/code/${encodeURIComponent(slug)}.user.js`;
    }
  }
  return url.href;
}

async function fetchScriptFromUrl(value) {
  const url = normalizeScriptUrl(value);
  const response = await fetch(url, {
    method: "GET",
    credentials: "omit",
    cache: "no-store",
    redirect: "follow"
  });
  if (!response.ok) throw new Error(`Script download failed: HTTP ${response.status}`);
  const rawCode = await response.text();
  if (!rawCode.trim()) throw new Error("Downloaded script is empty");
  if (rawCode.length > 1024 * 1024) throw new Error("Downloaded script is larger than 1 MB");
  return {
    rawCode,
    sourceUrl: response.url || url
  };
}

async function fetchRequiredCode(requires = [], baseUrl = "") {
  const urls = [...new Set((requires || []).map((url) => String(url || "").trim()).filter(Boolean))];
  const chunks = [];
  let totalBytes = 0;
  for (const rawUrl of urls) {
    const url = new URL(rawUrl, baseUrl || location.href);
    if (url.protocol !== "https:" && url.protocol !== "http:") {
      throw new Error(`Unsupported @require URL: ${rawUrl}`);
    }
    const response = await fetch(url.href, {
      method: "GET",
      credentials: "omit",
      cache: "no-store",
      redirect: "follow"
    });
    if (!response.ok) throw new Error(`@require download failed: HTTP ${response.status}`);
    const code = await response.text();
    totalBytes += new Blob([code]).size;
    if (totalBytes > 1024 * 1024) throw new Error("@require libraries are larger than 1 MB");
    chunks.push(`\n/* @require ${response.url || url.href} */\n${code}\n`);
  }
  return chunks.join("\n");
}

async function scriptFromRemote(rawCode, sourceUrl, existing = {}) {
  const parsedMeta = parseScriptMeta(rawCode, existing.name || "", existing.parsedMeta?.matches?.[0] || "https://*/*", existing.version || "1.0.0");
  const requiredCode = await fetchRequiredCode(parsedMeta.requires, sourceUrl);
  const now = Date.now();
  return {
    ...existing,
    id: existing.id || makeId("script"),
    name: parsedMeta.name || existing.name || "Untitled Script",
    version: parsedMeta.version || existing.version || "1.0.0",
    profileId: existing.profileId || existing.profile_id || DEFAULT_PROFILE_ID,
    profileIds: itemProfileIds(existing),
    enabled: existing.enabled !== false,
    source: "remote",
    sourceUrl,
    updateUrl: parsedMeta.updateURL || parsedMeta.downloadURL || existing.updateUrl || sourceUrl,
    autoUpdate: false,
    rawCode,
    requiredCode,
    parsedMeta,
    installedAt: existing.installedAt || now,
    updatedAt: now,
    lastUpdatedFromUrlAt: now,
    lastError: null,
    storageUsedBytes: existing.storageUsedBytes || 0
  };
}

async function showScriptInstallReviewFromUrl(value) {
  const { rawCode, sourceUrl } = await fetchScriptFromUrl(value);
  activatePanel("scripts-panel");
  state.pendingScriptInstall = buildUserscriptInstallPreview(rawCode, sourceUrl);
  setScriptEditorOpen(false);
  renderUserscriptInstallReview();
  requestAnimationFrame(() => $("script-install-review-card")?.scrollIntoView({ block: "start", behavior: "smooth" }));
  return state.pendingScriptInstall;
}

async function importScriptFromUrl() {
  await showScriptInstallReviewFromUrl($("script-source-url").value);
}

async function importScriptFromDirectUrl() {
  const input = $("script-import-url-input");
  const { rawCode, sourceUrl } = await fetchScriptFromUrl(input?.value || "");
  const script = await scriptFromRemote(rawCode, sourceUrl);
  state.scripts = [...state.scripts, script];
  state.selectedScriptId = null;
  state.pendingScriptInstall = null;
  await setStorage({ fp_scripts: state.scripts });
  await registerUserscripts();
  renderUserscriptInstallReview();
  renderScripts();
  renderProfiles();
  renderStatus();
  if (input) input.value = "";
  toast("Userscript imported", "success");
  return script;
}

async function prepareInstallScriptFromUrl(url) {
  try {
    await showScriptInstallReviewFromUrl(url);
  } catch (err) {
    toast("Failed to load script: " + (err.message || String(err)));
  } finally {
    history.replaceState(null, "", location.pathname);
  }
}

function uniqueProfileName(baseName) {
  const base = String(baseName || "Imported Pack").trim() || "Imported Pack";
  const existing = new Set([{ name: "Global" }, ...state.profiles].map((profile) => String(profile.name || "").toLowerCase()));
  if (!existing.has(base.toLowerCase())) return base;
  let index = 2;
  while (existing.has(`${base} ${index}`.toLowerCase())) index += 1;
  return `${base} ${index}`;
}

function promptPortablePackProfileName(pack) {
  const sourceName = String(pack?.source?.profileName || "").trim();
  const fallback = uniqueProfileName(sourceName ? `${sourceName} Import` : "Imported Pack");
  const value = window.prompt("New profile name for this imported pack", fallback);
  const trimmed = String(value || "").trim();
  if (!trimmed) throw new Error("Import cancelled");
  return uniqueProfileName(trimmed);
}

function portablePackCounts(pack) {
  const captchaCount = Object.entries(pack.captchaSelectors || {}).reduce((count, [domain, config]) => (
    count + captchaRowsForConfig(domain, config).length
  ), 0);
  return {
    rules: normalizeArray(pack.rules).length,
    scripts: normalizeArray(pack.scripts).length,
    captcha: captchaCount
  };
}

function timestampedBackupFilename(date = new Date()) {
  const pad = (value) => String(value).padStart(2, "0");
  const dd = pad(date.getDate());
  const mm = pad(date.getMonth() + 1);
  const yy = pad(date.getFullYear() % 100);
  const hh = pad(date.getHours());
  const min = pad(date.getMinutes());
  return `eazyfill-${dd}-${mm}-${yy}-${hh}-${min}-backup.eazyfill`;
}

function importedRule(rule, profileId, now) {
  const copy = cloneJson(rule, {});
  delete copy.server_rule_id;
  delete copy.remoteId;
  return {
    ...copy,
    id: makeId("rule"),
    profileId,
    profileIds: [profileId],
    importedAt: now,
    updatedAt: now
  };
}

function importedScript(script, profileId, now) {
  const copy = cloneJson(script, {});
  return {
    ...copy,
    id: makeId("script"),
    profileId,
    profileIds: [profileId],
    enabled: false,
    storageUsedBytes: 0,
    lastError: null,
    importedAt: now,
    updatedAt: now
  };
}

function importedCaptchaSelectors(packSelectors, profileId, now) {
  const next = { ...(state.captchaSelectors || {}) };
  let imported = 0;
  for (const [rawDomain, config] of Object.entries(packSelectors || {})) {
    const domain = normalizeDomain(config?.domain || rawDomain) || String(rawDomain || "").trim().toLowerCase();
    if (!domain) continue;
    const currentConfig = next[domain] || { domain };
    const routes = captchaRouteMapForConfig(domain, currentConfig);
    for (const route of captchaRowsForConfig(domain, config)) {
      const routeId = makeId("captcha");
      routes[routeId] = {
        ...cloneJson(route, {}),
        id: routeId,
        routeId,
        profileId,
        profileIds: [profileId],
        proposalId: "",
        proposal_id: "",
        importedAt: now,
        updatedAt: now
      };
      imported += 1;
    }
    writeCaptchaDomainConfig(next, domain, routes, currentConfig.activeFieldName);
  }
  return { selectors: next, imported };
}

async function exportBackup() {
  requirePortablePackAccess("export");
  const bytes = await encryptPortablePackPayload(portablePackPayload());
  downloadBlob(timestampedBackupFilename(), new Blob([bytes], { type: "application/octet-stream" }));
}

async function restoreBackup(file) {
  if (!file) return;
  requirePortablePackAccess("import");
  const pack = await parsePortablePack(await readFileBytes(file));
  const counts = portablePackCounts(pack);
  if (!counts.rules && !counts.scripts && !counts.captcha) {
    throw new Error("Portable pack does not contain any automations");
  }
  const now = Date.now();
  const profileId = makeId("profile");
  const profileNameValue = promptPortablePackProfileName(pack);
  const profile = {
    id: profileId,
    name: profileNameValue,
    values: {},
    createdAt: now,
    importedAt: now
  };
  const captchaImport = importedCaptchaSelectors(pack.captchaSelectors, profileId, now);

  state.profiles = [...state.profiles, profile];
  state.rules = [...state.rules, ...normalizeArray(pack.rules).map((rule) => importedRule(rule, profileId, now))];
  state.scripts = [...state.scripts, ...normalizeArray(pack.scripts).map((script) => importedScript(script, profileId, now))];
  state.captchaSelectors = captchaImport.selectors;
  state.settings = {
    ...state.settings,
    activeProfileId: profileId
  };
  state.syncMeta = {
    ...state.syncMeta,
    lastLocalImportAt: now
  };
  await setStorage({
    fp_profiles: state.profiles,
    fp_rules: state.rules,
    fp_scripts: state.scripts,
    fp_captcha_selectors: state.captchaSelectors,
    fp_settings: state.settings,
    fp_sync_meta: state.syncMeta
  });
  await registerUserscripts().catch(() => null);
  await sendMessage({ type: "CAPTCHA_CONFIG_UPDATED" }).catch(() => null);
  renderStatus();
  renderSettings();
  renderRules();
  renderProfiles();
  renderScripts();
  renderCaptchaConfigs();
  activatePanel("profiles-panel");
  toast(`Imported ${counts.rules} rules, ${counts.scripts} scripts, ${captchaImport.imported} CAPTCHA routes`, "success");
}

async function refreshCredits() {
  const response = await sendMessage({ type: "CREDIT_REFRESH" });
  if (!response.ok) throw new Error(response.error || "Credit refresh failed");
  if (response.credits) state.credits = response.credits;
  renderStatus();
}

async function loadBillingData() {
  const plansResponse = await sendMessage({ type: "BILLING_PLANS" });
  if (!plansResponse.ok) throw new Error(plansResponse.error || "Plan refresh failed");
  state.plans = Array.isArray(plansResponse.plans) ? plansResponse.plans : [];
  state.paymentProviders = Array.isArray(plansResponse.payment_providers)
    ? plansResponse.payment_providers
    : Array.isArray(plansResponse.paymentProviders)
      ? plansResponse.paymentProviders
      : [];
  state.creditPacks = Array.isArray(plansResponse.credit_packs)
    ? plansResponse.credit_packs
    : Array.isArray(plansResponse.creditPacks)
      ? plansResponse.creditPacks
      : Array.isArray(plansResponse.addons)
        ? plansResponse.addons
        : [];

  const historyResponse = await sendMessage({ type: "BILLING_HISTORY" });
  state.payments = historyResponse.ok && Array.isArray(historyResponse.items) ? historyResponse.items : [];

  const usageResponse = await sendMessage({ type: "CREDIT_HISTORY", limit: 12 });
  state.usageHistory = usageResponse.ok && Array.isArray(usageResponse.items) ? usageResponse.items : [];
  renderBilling();
}

async function createBillingOrder(plan) {
  if (!isAuthenticated()) {
    focusAccountSignup();
    throw new Error("Sign in before choosing a plan.");
  }
  const provider = preferredBillingProvider(plan);
  const payload = {
    provider
  };
  if (plan.id || plan.plan_id) {
    payload.plan_id = Number(plan.id || plan.plan_id);
  } else {
    payload.plan_code = plan.code;
  }
  if (!payload.plan_id && !payload.plan_code) {
    throw new Error("Backend billing item is missing a plan id or code");
  }
  const response = await sendMessage({
    type: "BILLING_CREATE_ORDER",
    payload
  });
  if (!response.ok) throw new Error(response.error || "Order creation failed");
  if (provider === "razorpay") {
    const orderId = response.order?.id || response.payment?.provider_order_id || "";
    const checkoutUrl = response.checkout_url || response.checkoutUrl || response.order?.checkout_url || "";
    if (checkoutUrl && openExternalBillingUrl(checkoutUrl)) {
      toast("Razorpay checkout opened", "success");
    } else if (checkoutUrl) {
      toast("Order created. Allow popups to open Razorpay checkout.", "warning");
    } else {
      toast(orderId ? `Razorpay order created: ${orderId}` : "Razorpay order created", "success");
    }
  }
  await loadBillingData();
}

async function verifyBillingPayment(payload) {
  const response = await sendMessage({
    type: "BILLING_VERIFY_PAYMENT",
    payload
  });
  if (!response.ok) throw new Error(response.error || "Payment verification failed");
  await loadBillingData();
  return response;
}

async function runSync(type) {
  const response = await sendMessage({ type });
  if (!response.ok) throw new Error(response.error || "Sync request failed");
  if (response.meta) state.syncMeta = response.meta;
  else if (response.sync) {
    state.syncMeta = {
      ...state.syncMeta,
      version: response.sync.sync_version || state.syncMeta.version || 0,
      blobSizeBytes: response.sync.blob_size_bytes || 0,
      blobHash: response.sync.blob_hash || state.syncMeta.blobHash || "",
      lastSyncAt: response.sync.updated_at || state.syncMeta.lastSyncAt || null
    };
  }
  if (type === "SYNC_PULL" && response.found) await loadState();
  else renderStatus();
}

const SELECTOR_PICK_TIMEOUT_MS = 30000;

async function beginSelectorPick(targetField) {
  await setStorage({ fp_last_selector_pick: null });
  const response = await sendMessage({ type: "PICK_ELEMENT_CURRENT", targetField });
  if (!response.ok) throw new Error(response.error || "Selector picker unavailable");
  toast("Waiting for a selection. Press Esc to cancel.");
  return Date.now();
}

async function waitForSelectorPick(targetField) {
  const started = await beginSelectorPick(targetField);
  while (Date.now() - started < SELECTOR_PICK_TIMEOUT_MS) {
    await new Promise((resolve) => setTimeout(resolve, 500));
    const data = await getStorage(["fp_last_selector_pick"]);
    const pick = data.fp_last_selector_pick || {};
    if (pick.cancelled && pick.targetField === targetField) {
      const timedOut = Date.now() - started >= SELECTOR_PICK_TIMEOUT_MS - 1000;
      return { status: timedOut ? "timed-out" : "cancelled" };
    }
    if (pick.targetField === targetField && pick.selector?.primary) {
      return { status: "selected", pick };
    }
  }
  return { status: "timed-out" };
}

function reportSelectorResult(result) {
  if (result.status === "cancelled") toast("Selector selection cancelled.");
  if (result.status === "timed-out") toast("Selector picker timed out.");
}

async function pickSelector() {
  const result = await waitForSelectorPick("selector");
  if (result.status !== "selected") {
    reportSelectorResult(result);
    return;
  }

  const steps = readRuleSteps();
  let step = [...steps].reverse().find((item) => !item.selector?.primary);
  if (!step) {
    step = { action: "set_value", selector: { primary: "" }, value: "", required: false, label: "" };
    steps.push(step);
  }
  step.selector = { ...result.pick.selector };
  step.label = step.label || result.pick.selector.label || "";
  renderRuleSteps(steps);
  toast(`Selected ${result.pick.selector.primary}`);
}

async function pickCaptchaSelector(targetField) {
  const result = await waitForSelectorPick(targetField);
  if (result.status !== "selected") {
    reportSelectorResult(result);
    return;
  }
  const pick = result.pick;
  if (targetField === "captcha-source") $("captcha-source-selector").value = pick.selector.primary;
  if (targetField === "captcha-target") $("captcha-target-selector").value = pick.selector.primary;
  if (pick.domain && !$("captcha-domain").value) $("captcha-domain").value = normalizeDomain(pick.domain);
  toast(targetField === "captcha-source" ? "Source selected." : "Target selected.");
}

async function logout() {
  const response = await sendMessage({ type: "LOGOUT" });
  if (!response.ok) throw new Error(response.error || "Sign out failed");
  await loadState();
}

function activatePanel(panelId) {
  const resolvedPanelId = panelIdFor(panelId);
  const targetPanel = $(resolvedPanelId) ? resolvedPanelId : "overview-panel";
  for (const button of document.querySelectorAll(".nav-item")) {
    button.classList.toggle("active", button.dataset.panel === targetPanel);
  }
  for (const panel of document.querySelectorAll(".panel")) {
    panel.classList.toggle("active", panel.id === targetPanel);
  }
  $("panel-title").textContent = $(targetPanel)?.dataset.title || "Overview";
  const activeButton = document.querySelector(`.nav-item[data-panel="${targetPanel}"]`);
  if ($("panel-eyebrow")) {
    $("panel-eyebrow").textContent = activeButton?.dataset.category || "Dashboard";
  }
}

async function loadState() {
  const data = await getStorage();
  const storedSettings = data.fp_settings || {};
  const captchaSelectors = data.fp_captcha_selectors && typeof data.fp_captcha_selectors === "object"
    ? data.fp_captcha_selectors
    : {};
  const legacyCaptchaBehavior = Object.values(captchaSelectors).find((config) => (
    config
    && (
      config.fillDelayMs !== undefined
      || config.delayMs !== undefined
      || config.fill_delay_ms !== undefined
      || config.humanTyping !== undefined
      || config.human_typing !== undefined
    )
  )) || {};
  state.auth = data.fp_auth || {};
  state.settings = {
    ...DEFAULT_SETTINGS,
    ...storedSettings,
    ...(!Object.prototype.hasOwnProperty.call(storedSettings, "captchaFillDelayMs")
      ? {
          captchaFillDelayMs: normalizeCaptchaDelay(
            legacyCaptchaBehavior.fillDelayMs
            ?? legacyCaptchaBehavior.delayMs
            ?? legacyCaptchaBehavior.fill_delay_ms
            ?? DEFAULT_SETTINGS.captchaFillDelayMs
          )
        }
      : {}),
    ...(!Object.prototype.hasOwnProperty.call(storedSettings, "captchaHumanTyping")
      ? {
          captchaHumanTyping: legacyCaptchaBehavior.humanTyping !== undefined
            ? legacyCaptchaBehavior.humanTyping === true
            : legacyCaptchaBehavior.human_typing !== undefined
              ? legacyCaptchaBehavior.human_typing === true
              : DEFAULT_SETTINGS.captchaHumanTyping
        }
      : {})
  };
  state.credits = data.fp_credits || state.auth.credits || {};
  state.rules = Array.isArray(data.fp_rules) ? data.fp_rules : [];
  state.scripts = Array.isArray(data.fp_scripts) ? data.fp_scripts : [];
  state.profiles = Array.isArray(data.fp_profiles) ? data.fp_profiles : [];
  state.captchaSelectors = captchaSelectors;
  state.syncMeta = data.fp_sync_meta || {};
  updateTheme();
  renderStatus();
  renderSettings();
  renderRules();
  renderProfiles();
  renderScripts();
  renderCaptchaConfigs();
  renderBilling();
  await refreshUserscriptStatus().catch(() => null);
  await loadBillingData().catch(() => null);

  const params = new URLSearchParams(location.search);
  const installUrl = params.get("installUserScript");
  if (installUrl) {
    prepareInstallScriptFromUrl(installUrl);
  }
  const tab = params.get("tab");
  if (tab) {
    activatePanel(tab);
  }
}

function bind() {
  const activePanelId = document.querySelector(".nav-item.active")?.dataset.panel
    || document.querySelector(".panel.active")?.id
    || "rules-panel";
  activatePanel(activePanelId);

  for (const button of document.querySelectorAll(".nav-item")) {
    button.addEventListener("click", () => activatePanel(button.dataset.panel));
  }
  for (const button of document.querySelectorAll("[data-jump]")) {
    button.addEventListener("click", () => activatePanel(button.dataset.jump));
    button.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return;
      event.preventDefault();
      activatePanel(button.dataset.jump);
    });
  }

  $("refresh-btn").addEventListener("click", () => handle(loadState, "Refreshed"));
  const saveAllBtn = $("save-all-btn");
  if (saveAllBtn) saveAllBtn.addEventListener("click", () => handle(saveSettings, "Saved"));
  $("settings-save-btn").addEventListener("click", () => handle(saveSettings, "Settings saved"));
  $("setting-theme").addEventListener("change", () => handle(saveSettings, "Theme saved"));
  for (const id of ["setting-captcha", "setting-autofill", "setting-userscripts", "setting-sync"]) {
    const el = $(id);
    if (el) el.addEventListener("change", () => handle(saveSettings, "Settings saved"));
  }

  $("rule-new-btn").addEventListener("click", () => selectRule(null));
  $("rule-save-btn").addEventListener("click", () => handle(saveRule, "Rule saved"));
  $("rule-delete-btn").addEventListener("click", () => handle(deleteRule, "Rule deleted"));

  const ruleBackBtn = $("rule-back-btn");
  if (ruleBackBtn) {
    ruleBackBtn.addEventListener("click", () => {
      setHidden("rules-editor-view", true);
      setHidden("rules-list-view", false);
    });
  }
  const ruleAddStepBtn = $("rule-add-step-btn");
  if (ruleAddStepBtn) {
    ruleAddStepBtn.addEventListener("click", () => {
      const steps = readRuleSteps();
      steps.push({ action: "set_value", selector: { primary: "" }, value: "", required: false, label: "" });
      renderRuleSteps(steps);
    });
  }

  $("rule-search").addEventListener("input", (event) => {
    state.ruleSearch = event.target.value;
    renderRules();
  });
  $("rule-status-filter").addEventListener("change", (event) => {
    state.ruleStatusFilter = event.target.value;
    renderRules();
  });
  $("rule-select-all").addEventListener("change", (event) => setAllVisibleRulesSelected(event.target.checked));
  $("rule-enable-selected-btn").addEventListener("click", () => handle(() => setSelectedRulesEnabled(true), "Rules enabled"));
  $("rule-disable-selected-btn").addEventListener("click", () => handle(() => setSelectedRulesEnabled(false), "Rules paused"));
  $("rule-delete-selected-btn").addEventListener("click", () => handle(deleteSelectedRules, "Rules deleted"));
  $("pick-selector-btn")?.addEventListener("click", () => handle(pickSelector));
  $("profile-new-btn").addEventListener("click", () => selectProfile(null));
  $("profile-save-btn").addEventListener("click", () => handle(saveProfile, "Profile saved"));
  $("profile-delete-btn").addEventListener("click", () => handle(deleteProfile, "Profile deleted"));
  $("active-profile-id")?.addEventListener("change", (event) => handle(() => setActiveProfile(event.target.value), "Profile activated"));
  $("profile-item-select-all")?.addEventListener("change", (event) => setAllVisibleProfileItemsSelected(event.target.checked));
  $("profile-clone-selected-btn")?.addEventListener("click", () => handle(() => cloneSelectedProfileItems(), "Selected items cloned"));
  $("profile-remove-selected-btn")?.addEventListener("click", () => handle(removeSelectedProfileItems, "Selected items removed"));

  $("script-new-btn").addEventListener("click", () => openLocalScriptEditor(null));
  $("script-update-all-btn")?.addEventListener("click", () => handle(updateRemoteScriptsForActiveProfile));
  $("script-import-direct-btn")?.addEventListener("click", () => handle(importScriptFromDirectUrl));
  $("script-import-url-input")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") handle(importScriptFromDirectUrl);
  });
  $("script-install-confirm-btn")?.addEventListener("click", () => handle(installPendingUserscript, "Userscript installed"));
  $("script-install-cancel-btn")?.addEventListener("click", clearPendingUserscriptInstall);
  for (const id of ["script-name", "script-version", "script-match", "script-source-url", "script-enabled"]) {
    $(id)?.addEventListener("input", () => {
      renderScriptMetaPreview();
      if (id === "script-name") {
        setText("script-editor-title", $("script-name").value || "<New userscript>");
      }
    });
    $(id)?.addEventListener("change", () => {
      renderScriptMetaPreview();
      if (id === "script-name") {
        setText("script-editor-title", $("script-name").value || "<New userscript>");
      }
    });
  }
  $("script-save-btn").addEventListener("click", () => handle(saveScript, "Script saved"));
  $("script-import-url-btn").addEventListener("click", () => handle(importScriptFromUrl));
  $("script-discard-btn")?.addEventListener("click", () => closeScriptEditor());
  $("script-editor-close-btn")?.addEventListener("click", () => closeScriptEditor());
  $("captcha-save-behavior-btn").addEventListener("click", () => handle(saveSettings, "CAPTCHA behavior saved"));
  $("captcha-save-config-btn").addEventListener("click", () => handle(saveCaptchaConfig, "CAPTCHA config saved"));
  $("captcha-new-route-btn")?.addEventListener("click", () => resetCaptchaEditor());
  $("captcha-pick-source-btn").addEventListener("click", () => handle(() => pickCaptchaSelector("captcha-source")));
  $("captcha-pick-target-btn").addEventListener("click", () => handle(() => pickCaptchaSelector("captcha-target")));
  $("captcha-search")?.addEventListener("input", (event) => {
    state.captchaSearch = event.target.value;
    renderCaptchaConfigs();
  });
  $("billing-refresh-btn").addEventListener("click", () => handle(loadBillingData, "Billing refreshed"));
  $("sync-refresh-btn").addEventListener("click", () => handle(() => runSync("SYNC_STATUS"), "Sync refreshed"));
  $("sync-push-btn").addEventListener("click", () => handle(() => runSync("SYNC_PUSH"), "Sync pushed"));
  $("sync-pull-btn").addEventListener("click", () => handle(() => runSync("SYNC_PULL"), "Sync pulled"));
  $("sync-delete-btn").addEventListener("click", () => handle(() => runSync("SYNC_DELETE"), "Cloud copy deleted"));
  $("backup-export-btn").addEventListener("click", () => handle(exportBackup, "Portable pack exported"));
  $("backup-restore-btn").addEventListener("click", () => $("backup-restore-file").click());
  $("backup-restore-file").addEventListener("change", (event) => {
    const file = event.target.files?.[0];
    handle(() => restoreBackup(file));
    event.target.value = "";
  });
  $("logout-btn").addEventListener("click", () => handle(logout, "Signed out"));

  // Theme switcher toggle button click
  $("theme-toggle-btn")?.addEventListener("click", () => handle(toggleTheme));

  // Userscript editor settings listeners
  $("script-font-size")?.addEventListener("change", (e) => {
    const size = e.target.value;
    const editorContainer = $("script-editor-container");
    if (editorContainer) {
      editorContainer.style.setProperty("--script-editor-font-size", size);
      if (scriptEditor) scriptEditor.requestMeasure();
    }
  });

  $("script-fullscreen-btn")?.addEventListener("click", () => {
    const card = $("script-editor-card");
    if (card) {
      card.classList.toggle("userscript-fullscreen-active");
      if (scriptEditor) scriptEditor.requestMeasure();
      const isFull = card.classList.contains("userscript-fullscreen-active");
      toast(isFull ? "Fullscreen mode enabled. Press ESC or click icon to exit." : "Fullscreen mode disabled.", "info");
    }
  });

  // Global window listeners for Command Palette and Fullscreen escape
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      const card = $("script-editor-card");
      if (card && card.classList.contains("userscript-fullscreen-active")) {
        card.classList.remove("userscript-fullscreen-active");
        if (scriptEditor) scriptEditor.requestMeasure();
        toast("Fullscreen mode disabled.", "info");
      }
    }
  });

  // Account login and registration bindings
  $("options-send-otp-btn")?.addEventListener("click", () => handle(optionsSendOtp));
  $("options-verify-otp-btn")?.addEventListener("click", () => handle(optionsVerifyOtp));
  $("options-signup-identifier")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") handle(optionsSendOtp);
  });
  $("options-signup-name")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") handle(optionsSendOtp);
  });
  $("options-signup-otp")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") handle(optionsVerifyOtp);
  });
  setOptionsAuthStep("email");

  // Command palette initialization
  initCommandPalette();
}

let otpChallengeId = "";
let optionsAuthStep = "email";

function optionsAuthErrorCode(response = {}) {
  const detail = response.detail || response.data?.detail || response.errorDetail || null;
  if (typeof detail === "object" && detail?.error) return String(detail.error);
  return String(response.code || response.error_code || response.errorCode || "");
}

function setDomHidden(element, hidden) {
  if (!element) return;
  element.hidden = !!hidden;
  element.style.display = hidden ? "none" : "";
}

function setOptionsAuthStep(step) {
  const next = ["email", "name", "otp"].includes(step) ? step : "email";
  optionsAuthStep = next;
  const nameRow = $("options-signup-name-row");
  const otpRow = $("options-signup-otp-row");
  const sendButton = $("options-send-otp-btn");
  const verifyButton = $("options-verify-otp-btn");
  const emailInput = $("options-signup-identifier");
  const nameInput = $("options-signup-name");
  const otpInput = $("options-signup-otp");

  setDomHidden(nameRow, next !== "name");
  setDomHidden(otpRow, next !== "otp");
  if (sendButton) {
    setDomHidden(sendButton, next === "otp");
    sendButton.disabled = false;
  }
  if (verifyButton) {
    setDomHidden(verifyButton, next !== "otp");
    verifyButton.disabled = next !== "otp";
  }
  if (emailInput) emailInput.readOnly = next === "otp";
  if (nameInput) nameInput.disabled = next !== "name";
  if (otpInput) otpInput.disabled = next !== "otp";
}

async function optionsSendOtp() {
  const name = optionsAuthStep === "name" ? ($("options-signup-name")?.value.trim() || "") : "";
  const identifier = $("options-signup-identifier")?.value.trim() || "";
  const messageNode = $("options-signup-message");
  if (!identifier) {
    setInlineMessage(messageNode, "Enter your email.", "error");
    $("options-signup-identifier")?.focus();
    return;
  }
  if (!identifier.includes("@")) {
    setInlineMessage(messageNode, "Enter a valid email address.", "error");
    $("options-signup-identifier")?.focus();
    return;
  }
  if (optionsAuthStep === "name" && !name) {
    setInlineMessage(messageNode, "Enter your name to create the account.", "error");
    $("options-signup-name")?.focus();
    return;
  }
  const button = $("options-send-otp-btn");
  if (button) button.disabled = true;
  setInlineMessage(messageNode, optionsAuthStep === "name" ? "Creating account..." : "Checking email...", "neutral");
  const response = await sendMessage({
    type: "REGISTER_ACCOUNT",
    payload: { identifier, name, planCode: "free" }
  });
  if (button) button.disabled = false;
  if (!response.ok) {
    if (optionsAuthErrorCode(response) === "name_required" || /name/i.test(response.error || "")) {
      setOptionsAuthStep("name");
      setInlineMessage(messageNode, "Enter your name to create the account.", "neutral");
      $("options-signup-name")?.focus();
      return;
    }
    const message = response.error || "Could not send OTP.";
    setInlineMessage(messageNode, message, "error");
    return;
  }
  if (response.next_step === "profile" || response.nextStep === "profile" || response.profile_required) {
    setOptionsAuthStep("name");
    setInlineMessage(messageNode, "Enter your name to create the account.", "neutral");
    $("options-signup-name")?.focus();
    return;
  }
  otpChallengeId = response.challenge_id || response.challengeId || response.challenge?.id || "";
  if (!otpChallengeId) {
    setInlineMessage(messageNode, "Could not start verification. Try again.", "error");
    return;
  }
  setOptionsAuthStep("otp");
  const devOtp = response.dev_otp ? ` Code: ${response.dev_otp}` : "";
  setInlineMessage(messageNode, `Code sent. Check your email.${devOtp}`, "success");
  toast("Verification code sent", "success");
}

async function optionsVerifyOtp() {
  const otp = $("options-signup-otp")?.value.trim() || "";
  const messageNode = $("options-signup-message");
  if (!otpChallengeId || !otp) {
    setInlineMessage(messageNode, "Enter the OTP.", "error");
    return;
  }
  const button = $("options-verify-otp-btn");
  if (button) button.disabled = true;
  setInlineMessage(messageNode, "Verifying code...", "neutral");
  const response = await sendMessage({
    type: "VERIFY_OTP",
    payload: {
      challengeId: otpChallengeId,
      otp,
      deviceName: "EazyFill Options Page"
    }
  });
  if (button) button.disabled = false;
  if (!response.ok) {
    setInlineMessage(messageNode, response.error || "OTP verification failed.", "error");
    return;
  }
  otpChallengeId = "";
  const otpInput = $("options-signup-otp");
  if (otpInput) {
    otpInput.value = "";
    otpInput.disabled = true;
  }
  setOptionsAuthStep("email");
  setInlineMessage(messageNode, "Account verified and connected!", "success");
  toast("Account verified and connected!", "success");
  await loadState();
}

function initCommandPalette() {
  const overlay = $("cmd-overlay");
  const input = $("cmd-input");
  const resultsContainer = $("cmd-results");
  const openBtn = $("cmd-palette-btn");

  if (!overlay || !input || !resultsContainer) return;

  const commands = [
    { id: "nav-overview", title: "Go to Overview", desc: "View your dashboard and stats", category: "Navigation", icon: "OV", action: () => activatePanel("overview-panel") },
    { id: "nav-autofill", title: "Go to Autofill", desc: "View private summaries and add rules", category: "Navigation", icon: "AF", action: () => activatePanel("rules-panel") },
    { id: "nav-profiles", title: "Go to Profiles", desc: "Manage profile configurations", category: "Navigation", icon: "PR", action: () => activatePanel("profiles-panel") },
    { id: "nav-userscripts", title: "Go to Userscripts", desc: "Add scripts; saved code stays hidden", category: "Navigation", icon: "US", action: () => activatePanel("scripts-panel") },
    { id: "nav-captcha", title: "Go to CAPTCHA", desc: "Configure CAPTCHA auto-solving selectors", category: "Navigation", icon: "CA", action: () => activatePanel("captcha-panel") },
    { id: "nav-settings", title: "Go to Settings", desc: "Edit core system preferences", category: "Navigation", icon: "SE", action: () => activatePanel("settings-panel") },
    { id: "nav-account", title: "Go to Account & Plan", desc: "Create an account, view credits, or upgrade", category: "Navigation", icon: "AC", action: () => activatePanel("account-panel") },
    { id: "nav-sync", title: "Go to Sync", desc: "Push, pull, or delete cloud backups", category: "Navigation", icon: "SY", action: () => activatePanel("sync-panel") },
    { id: "act-new-rule", title: "New Autofill Rule", desc: "Open the editor to create a rule", category: "Actions", icon: "NR", action: () => { activatePanel("rules-panel"); selectRule(null); } },
    { id: "act-new-script", title: "New Userscript", desc: "Create a new local userscript", category: "Actions", icon: "NS", action: () => { activatePanel("scripts-panel"); $("script-new-btn")?.click(); } },
    { id: "act-new-profile", title: "New Profile", desc: "Create a new profile template", category: "Actions", icon: "NP", action: () => { activatePanel("profiles-panel"); selectProfile(null); } },
    { id: "act-refresh", title: "Refresh All Data", desc: "Reload storage and billing metrics", category: "Actions", icon: "RF", action: () => handle(loadState, "Refreshed") },
    { id: "toggle-theme", title: "Toggle Dark/Light Theme", desc: "Switch between dark and light modes", category: "Settings", icon: "TH", action: () => toggleTheme() },
    { id: "toggle-captcha", title: "Toggle CAPTCHA Auto-solving", desc: "Enable or disable auto-solving globally", category: "Settings", icon: "TC", action: () => { const el = $("setting-captcha"); if (el) { el.checked = !el.checked; el.dispatchEvent(new Event("change")); } } },
    { id: "toggle-autofill", title: "Toggle Autofill Engine", desc: "Enable or disable autofill globally", category: "Settings", icon: "TA", action: () => { const el = $("setting-autofill"); if (el) { el.checked = !el.checked; el.dispatchEvent(new Event("change")); } } },
    { id: "toggle-userscripts", title: "Toggle Userscripts Manager", desc: "Enable or disable script execution", category: "Settings", icon: "TU", action: () => { const el = $("setting-userscripts"); if (el) { el.checked = !el.checked; el.dispatchEvent(new Event("change")); } } }
  ];

  let selectedIndex = 0;
  let filteredCommands = [];

  function openPalette() {
    setHidden(overlay, false);
    input.value = "";
    input.focus();
    renderResults();
  }

  function closePalette() {
    setHidden(overlay, true);
  }

  function renderResults() {
    const query = input.value.trim().toLowerCase();

    filteredCommands = commands.filter(cmd =>
      cmd.title.toLowerCase().includes(query) ||
      cmd.desc.toLowerCase().includes(query) ||
      cmd.category.toLowerCase().includes(query)
    );

    resultsContainer.replaceChildren();
    selectedIndex = Math.min(selectedIndex, Math.max(0, filteredCommands.length - 1));

    if (filteredCommands.length === 0) {
      const empty = document.createElement("div");
      empty.className = "cmd-empty";
      empty.textContent = "No commands found.";
      resultsContainer.append(empty);
      return;
    }

    let currentCategory = "";
    filteredCommands.forEach((cmd, idx) => {
      if (cmd.category !== currentCategory) {
        currentCategory = cmd.category;
        const groupHeader = document.createElement("div");
        groupHeader.className = "cmd-group-title";
        groupHeader.textContent = currentCategory;
        resultsContainer.appendChild(groupHeader);
      }

      const item = document.createElement("div");
      item.className = "cmd-item" + (idx === selectedIndex ? " selected" : "");
      const left = document.createElement("div");
      left.className = "cmd-item-left";
      const icon = document.createElement("span");
      icon.className = "cmd-item-icon";
      icon.textContent = cmd.icon || "*";
      const info = document.createElement("div");
      info.className = "cmd-item-info";
      const title = document.createElement("span");
      title.className = "cmd-item-title";
      title.textContent = cmd.title;
      const desc = document.createElement("span");
      desc.className = "cmd-item-desc";
      desc.textContent = cmd.desc;
      info.append(title, desc);
      left.append(icon, info);
      const shortcut = document.createElement("span");
      shortcut.className = "cmd-item-shortcut";
      shortcut.textContent = "Enter";
      item.append(left, shortcut);

      item.addEventListener("click", () => {
        cmd.action();
        closePalette();
      });

      item.addEventListener("mouseenter", () => {
        selectedIndex = idx;
        renderResults();
      });

      resultsContainer.appendChild(item);
    });

    const selectedEl = resultsContainer.querySelector(".cmd-item.selected");
    if (selectedEl) {
      selectedEl.scrollIntoView({ block: "nearest" });
    }
  }

  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      selectedIndex = (selectedIndex + 1) % filteredCommands.length;
      renderResults();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      selectedIndex = (selectedIndex - 1 + filteredCommands.length) % filteredCommands.length;
      renderResults();
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (filteredCommands[selectedIndex]) {
        filteredCommands[selectedIndex].action();
        closePalette();
      }
    } else if (e.key === "Escape") {
      e.preventDefault();
      closePalette();
    }
  });

  input.addEventListener("input", () => {
    selectedIndex = 0;
    renderResults();
  });

  window.addEventListener("keydown", (e) => {
    if (e.key === "k" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      if (overlay.classList.contains("is-hidden")) {
        openPalette();
      } else {
        closePalette();
      }
    }
  });

  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closePalette();
  });

  if (openBtn) {
    openBtn.addEventListener("click", openPalette);
  }
}

async function handle(task, successMessage = "") {
  try {
    await task();
    if (successMessage) toast(successMessage, "success");
  } catch (error) {
    toast(error.message || String(error), "error");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  initCodeMirror();
  bind();
  handle(loadState);
});
