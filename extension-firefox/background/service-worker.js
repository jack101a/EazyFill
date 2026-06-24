import { getExtensionStorage, hydrateProtectedCache, setExtensionStorage } from "./protected-storage.js";
import { createApiClient } from "./api-client.js";
import { createAuthManager } from "./auth-manager.js";
import { createCaptchaHandler } from "./captcha-handler.js";
import { createCreditManager } from "./credit-manager.js";
import { createSyncManager } from "./sync-manager.js";
import { installMessageHub, registerCoreMessageHandlers } from "./messaging-hub.js";
import { registerStoredUserscripts } from "./userscript-manager.js";
import { DEFAULT_API_BASE_URL } from "../lib/app-config.js";

const apiClient = createApiClient();
const authManager = createAuthManager({ apiClient });
const creditManager = createCreditManager({ apiClient });
const captchaHandler = createCaptchaHandler({ apiClient, creditManager });
const syncManager = createSyncManager({ apiClient });
const AUTO_SYNC_KEYS = new Set([
  "fp_rules",
  "fp_scripts",
  "fp_profiles",
  "fp_protected:fp_rules",
  "fp_protected:fp_scripts",
  "fp_protected:fp_profiles",
  "fp_captcha_selectors",
  "fp_settings"
]);
let autoSyncTimer = null;
let autoSyncRunning = false;
const LEGACY_API_BASE_URL = "https://eazyfill.app";
const DEFAULT_CAPTCHA_BEHAVIOR = {
  captchaFillDelayMs: 200,
  captchaHumanTyping: true,
  captchaLearningConsent: true
};

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

async function autoSyncEligible() {
  const data = await getExtensionStorage(["fp_auth", "fp_settings"]);
  const auth = data.fp_auth || {};
  const settings = data.fp_settings || {};
  return !!String(auth.sessionToken || "").trim()
    && auth.valid !== false
    && settings.syncEnabled === true
    && planAllowsSync(auth.plan);
}

async function runAutoSync(reason = "scheduled") {
  if (autoSyncRunning) return;
  autoSyncRunning = true;
  try {
    if (!await autoSyncEligible()) return;
    await syncManager.push();
  } catch (error) {
    const data = await getExtensionStorage(["fp_sync_meta"]).catch(() => ({}));
    await setExtensionStorage({
      fp_sync_meta: {
        ...(data.fp_sync_meta || {}),
        lastAutoSyncAt: Date.now(),
        lastAutoSyncReason: reason,
        lastAutoSyncError: error?.message || String(error || "Sync failed")
      }
    }).catch(() => null);
    console.debug("[EazyFill] Auto sync skipped:", error?.message || error);
  } finally {
    autoSyncRunning = false;
  }
}

function scheduleAutoSync(reason = "local_change", delayMs = 45000) {
  if (autoSyncTimer) clearTimeout(autoSyncTimer);
  autoSyncTimer = setTimeout(() => {
    autoSyncTimer = null;
    runAutoSync(reason).catch((error) => console.debug("[EazyFill] Auto sync failed:", error));
  }, delayMs);
}

function isUserscriptInstallUrl(url = "") {
  return /^https?:\/\//i.test(url) && /\.user\.js(?:$|[?#])/i.test(url);
}

function userscriptInstallOptionsUrl(url) {
  return chrome.runtime.getURL("options/options.html") + "?installUserScript=" + encodeURIComponent(url);
}

function installUserscriptNavigationHandler() {
  if (!chrome.webNavigation?.onCommitted || !chrome.tabs?.update) return;
  chrome.webNavigation.onCommitted.addListener((details) => {
    if (details.frameId !== 0 || !isUserscriptInstallUrl(details.url)) return;
    chrome.tabs.update(details.tabId, { url: userscriptInstallOptionsUrl(details.url) });
  }, {
    url: [{ schemes: ["http"] }, { schemes: ["https"] }]
  });
}

async function ensureDefaults() {
  const existing = await getExtensionStorage(["fp_credits", "fp_settings"]);
  const updates = {};
  if (!existing.fp_credits) {
    updates.fp_credits = {
      captcha: {
        usedToday: 0,
        dailyLimit: 20,
        remaining: 20,
        resetsAt: null
      }
    };
  }
  const settings = existing.fp_settings || {};
  const storedApiBase = String(settings.apiBaseUrl || "").replace(/\/+$/, "");
  const nextSettings = { ...settings };
  let shouldUpdateSettings = false;
  for (const [key, value] of Object.entries(DEFAULT_CAPTCHA_BEHAVIOR)) {
    if (!Object.prototype.hasOwnProperty.call(nextSettings, key)) {
      nextSettings[key] = value;
      shouldUpdateSettings = true;
    }
  }
  if (!storedApiBase || storedApiBase === LEGACY_API_BASE_URL) {
    nextSettings.apiBaseUrl = DEFAULT_API_BASE_URL;
    shouldUpdateSettings = true;
  }
  if (shouldUpdateSettings) {
    updates.fp_settings = {
      ...nextSettings
    };
  }
  const keys = Object.keys(updates);
  if (!keys.length) return;

  const latest = await chrome.storage.local.get(keys);
  const safeUpdates = {};
  for (const key of keys) {
    if (latest[key] === undefined) safeUpdates[key] = updates[key];
  }
  if (Object.keys(safeUpdates).length) await setExtensionStorage(safeUpdates);
}

async function initialize() {
  await ensureDefaults();
  await hydrateProtectedCache();
  await authManager.refreshCachedStatus().catch(() => null);
  await registerStoredUserscripts().catch((error) => {
    console.debug("[EazyFill] Userscript registration skipped:", error.message || error);
  });
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

async function isExtensionEnabled() {
  const data = await getExtensionStorage(["fp_settings"]);
  return data.fp_settings?.extensionEnabled !== false;
}

chrome.runtime.onInstalled.addListener(() => {
  initialize().catch((error) => console.error("[EazyFill] Install initialization failed:", error));
});

chrome.runtime.onStartup.addListener(() => {
  initialize().catch((error) => console.error("[EazyFill] Startup initialization failed:", error));
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "eazyfill_auth_refresh") {
    authManager.refreshCachedStatus().catch((error) => console.debug("[EazyFill] Auth refresh failed:", error));
  } else if (alarm.name === "eazyfill_auto_sync") {
    runAutoSync("alarm").catch((error) => console.debug("[EazyFill] Auto sync failed:", error));
  }
});

chrome.storage.onChanged.addListener((changes, areaName) => {
  if (areaName !== "local") return;
  if (!Object.keys(changes || {}).some((key) => AUTO_SYNC_KEYS.has(key))) return;
  scheduleAutoSync("local_change");
});

chrome.commands.onCommand.addListener(async (command) => {
  try {
    if (!await isExtensionEnabled()) return;
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.id || !/^https?:/i.test(tab.url || "")) return;

    if (command === "start-recording") {
      await sendTabMessage(tab.id, { type: "START_RECORDING" });
    } else if (command === "fill-autofill") {
      const response = await sendTabMessage(tab.id, {
        type: "AUTOFILL_EXECUTE_NOW",
        mode: "instant",
        force: true
      });
      if (response?.ok && response?.succeededSteps && creditManager?.recordAutofillExecution) {
        creditManager.recordAutofillExecution(response.succeededSteps);
      }
    } else if (command === "solve-captcha") {
      captchaHandler.solveCurrentTab({}).catch(() => null);
    }
  } catch (error) {
    console.debug("[EazyFill] Command failed:", error);
  }
});

registerCoreMessageHandlers({ apiClient, authManager, captchaHandler, creditManager, syncManager });
installMessageHub();
installUserscriptNavigationHandler();

initialize()
  .then(() => Promise.all([
    chrome.alarms.create("eazyfill_auth_refresh", { periodInMinutes: 30 }),
    chrome.alarms.create("eazyfill_auto_sync", { periodInMinutes: 15 })
  ]))
  .catch((error) => console.error("[EazyFill] Initialization failed:", error));
