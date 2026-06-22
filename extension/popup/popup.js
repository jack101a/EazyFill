"use strict";

const DEFAULT_SETTINGS = {
  extensionEnabled: true,
  activeProfileId: "default",
  captchaEnabled: true,
  captchaFillDelayMs: 200,
  captchaHumanTyping: true,
  captchaLearningConsent: true,
  autofillEnabled: true,
  userscriptsEnabled: true,
  syncEnabled: false,
  apiBaseUrl: "https://eazyfill.app",
  theme: "light",
  seenWelcome: false
};

const state = {
  status: null,
  settings: { ...DEFAULT_SETTINGS },
  busyButtonId: null,
  authChallengeId: "",
  authEmail: "",
  authStep: "email"
};

const BUTTON_LABELS = {
  "simple-solve-captcha-btn": "Autosolve Captcha",
  "simple-autofill-btn": "Autofill Rules",
  "record-rule": "Record",
  "popup-send-otp": "Continue",
  "popup-verify-otp": "Verify"
};

const SUPPORTED_AUTH_EMAIL_DOMAINS = new Set([
  "gmail.com",
  "googlemail.com",
  "hotmail.com",
  "outlook.com",
  "live.com",
  "msn.com",
  "proton.me",
  "protonmail.com",
  "pm.me",
  "rediffmail.com",
  "rediff.com",
  "yahoo.com",
  "ymail.com",
  "rocketmail.com",
  "icloud.com",
  "me.com",
  "mac.com",
  "aol.com",
  "zoho.com",
  "zohomail.com",
  "fastmail.com",
  "hey.com",
  "mail.com",
  "gmx.com",
  "gmx.net",
  "tutanota.com",
  "tuta.io"
]);

const BLOCKED_AUTH_EMAIL_DOMAINS = new Set([
  "10minutemail.com",
  "20minutemail.com",
  "anonaddy.com",
  "dispostable.com",
  "emailondeck.com",
  "fakeinbox.com",
  "getnada.com",
  "guerrillamail.com",
  "grr.la",
  "maildrop.cc",
  "mailinator.com",
  "mintemail.com",
  "moakt.com",
  "mytemp.email",
  "sharklasers.com",
  "temp-mail.org",
  "tempmail.com",
  "throwawaymail.com",
  "trashmail.com",
  "yopmail.com"
]);

function $(id) {
  return document.getElementById(id);
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

async function getStorage(keys) {
  const response = await sendMessage({ type: "GET_EXTENSION_STORAGE", keys });
  if (!response.ok) throw new Error(response.error || "Could not read extension storage");
  return response.data || {};
}

async function setStorage(values) {
  const response = await sendMessage({ type: "SET_EXTENSION_STORAGE", values });
  if (!response.ok) throw new Error(response.error || "Could not save extension storage");
  return response;
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

function activeDomain() {
  return normalizeDomain(state.status?.activeTab?.hostname || state.status?.activeTab?.url || "");
}

function activeProfileId() {
  return String(state.settings.activeProfileId || "default").trim() || "default";
}

function routeProfileIds(route = {}) {
  const ids = Array.isArray(route.profileIds)
    ? route.profileIds
    : Array.isArray(route.profile_ids)
      ? route.profile_ids
      : [route.profileId || route.profile_id || "default"];
  return [...new Set(ids.map((id) => String(id || "default").trim() || "default"))];
}

function withActiveRouteProfile(route = {}) {
  const profileId = "default";
  const existingIds = (Array.isArray(route.profileIds) || Array.isArray(route.profile_ids) || route.profileId || route.profile_id)
    ? routeProfileIds(route)
    : [];
  const ids = new Set(existingIds);
  ids.add(profileId);
  return {
    ...route,
    profileId,
    profileIds: [...ids]
  };
}

async function stableCaptchaFieldName(domain, sourceSelector, targetSelector) {
  const raw = `${domain}|${sourceSelector}|${targetSelector}`;
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

function captchaRoutesForDomain(rawSelectors, domain) {
  const entry = rawSelectors?.[domain];
  if (!entry || typeof entry !== "object") return {};
  if (entry.routes && typeof entry.routes === "object") return entry.routes;
  const fieldName = entry.fieldName || entry.field_name || entry.id || domain;
  return {
    [fieldName]: {
      ...entry,
      fieldName,
      id: fieldName
    }
  };
}

function setView(authenticated, seenWelcome, unavailable = false) {
  const showUnavailable = unavailable;
  const showApp = !showUnavailable;

  $("unavailable-view").classList.toggle("active", showUnavailable);
  $("welcome-view")?.classList.toggle("active", false);
  $("app-view").classList.toggle("active", showApp);
}

function isExtensionEnabled(settings = state.settings) {
  return settings.extensionEnabled !== false;
}

function isServiceUnavailable(error) {
  return /receiving end does not exist|message port closed|context invalidated|no response/i.test(String(error || ""));
}

function setDisabled(id, disabled) {
  const element = $(id);
  if (element) element.disabled = !!disabled;
}

function showServiceUnavailable() {
  state.status = null;
  state.busyButtonId = null;
  if ($("account-summary")) $("account-summary").textContent = "Extension unavailable";
  $("credit-progress-container").hidden = true;
  $("unavailable-message").textContent = "EazyFill's background service is not responding. Retry in a moment.";
  setView(false, true, true);
}

function setAlert(message, tone = "warning") {
  const alert = $("alert");
  if (!message) {
    alert.hidden = true;
    alert.textContent = "";
    return;
  }
  alert.hidden = false;
  alert.textContent = message;
  alert.dataset.tone = tone;
}

function setAuthMessage(message, tone = "neutral") {
  const node = $("popup-auth-message");
  if (!node) return;
  node.textContent = message || "";
  if (message) node.dataset.tone = tone;
  else delete node.dataset.tone;
}

function authErrorCode(response = {}) {
  const detail = response.detail || response.data?.detail || response.errorDetail || null;
  if (typeof detail === "object" && detail?.error) return String(detail.error);
  return String(response.code || response.error_code || response.errorCode || "");
}

function setDomHidden(element, hidden) {
  if (!element) return;
  element.hidden = !!hidden;
  element.style.display = hidden ? "none" : "";
}

function setPopupAuthStep(step) {
  const next = ["email", "name", "otp"].includes(step) ? step : "email";
  state.authStep = next;
  const panel = $("popup-auth-panel");
  if (panel) panel.dataset.step = next;
  const nameRow = $("popup-auth-name-row");
  const otpRow = $("popup-auth-otp-row");
  const sendButton = $("popup-send-otp");
  const verifyButton = $("popup-verify-otp");
  const emailInput = $("popup-auth-email");
  const nameInput = $("popup-auth-name");
  const otpInput = $("popup-auth-otp");

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

function resetPopupAuthFlow({ keepEmail = true } = {}) {
  state.authChallengeId = "";
  state.authEmail = "";
  const emailInput = $("popup-auth-email");
  const nameInput = $("popup-auth-name");
  const otpInput = $("popup-auth-otp");
  if (!keepEmail && emailInput) emailInput.value = "";
  if (nameInput) nameInput.value = "";
  if (otpInput) otpInput.value = "";
  setPopupAuthStep("email");
  setAuthMessage("");
}

function setPopupAuthVisible(visible) {
  const panel = $("popup-auth-panel");
  if (!panel) return;
  panel.hidden = !visible;
  document.documentElement.dataset.authPanel = visible ? "open" : "closed";
  if (visible && !state.authChallengeId) setPopupAuthStep(state.authStep || "email");
  if (!visible) resetPopupAuthFlow();
  if (visible) {
    requestAnimationFrame(() => {
      const focusTarget = state.authStep === "otp"
        ? $("popup-auth-otp")
        : state.authStep === "name"
          ? $("popup-auth-name")
          : $("popup-auth-email");
      focusTarget?.focus();
    });
  }
}

function cleanAuthEmail(value) {
  return String(value || "").trim().toLowerCase();
}

function authEmailDomain(email) {
  const clean = cleanAuthEmail(email);
  const atIndex = clean.lastIndexOf("@");
  if (atIndex <= 0 || atIndex === clean.length - 1) return "";
  return clean.slice(atIndex + 1).replace(/\.+$/, "");
}

function authEmailValidationMessage(email) {
  const domain = authEmailDomain(email);
  if (!domain) return "Enter a valid email address.";
  if (BLOCKED_AUTH_EMAIL_DOMAINS.has(domain)) return "Temporary email addresses are not supported.";
  if (!SUPPORTED_AUTH_EMAIL_DOMAINS.has(domain)) {
    return "Use Gmail, Outlook, Hotmail, Proton Mail, Rediffmail, Yahoo, iCloud, Zoho, Fastmail, or another supported provider.";
  }
  return "";
}

function setLoading(button, loading, label) {
  button.disabled = loading;
  button.classList.toggle("loading", loading);
  const labelNode = button.querySelector?.("[data-button-label]");
  if (!button.dataset.defaultLabel) {
    button.dataset.defaultLabel = labelNode ? labelNode.textContent : button.textContent;
  }
  const nextLabel = loading ? label : (BUTTON_LABELS[button.id] || button.dataset.defaultLabel || button.textContent);
  if (labelNode) {
    labelNode.textContent = nextLabel;
    return;
  }
  button.textContent = nextLabel;
}

function applyTheme(theme) {
  const next = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  const logo = $("brand-logo");
  if (logo) {
    logo.src = next === "light" ? "../brand/logo-dark.png" : "../brand/logo-light.png";
  }
  const toggle = $("theme-toggle");
  if (toggle) {
    const isLight = next === "light";
    const sunIcon = toggle.querySelector(".sun-icon");
    const moonIcon = toggle.querySelector(".moon-icon");
    toggle.dataset.mode = next;
    toggle.setAttribute("aria-label", next === "light" ? "Switch to dark theme" : "Switch to light theme");
    toggle.setAttribute("title", next === "light" ? "Dark theme" : "Light theme");
    sunIcon?.classList.toggle("is-hidden", isLight);
    moonIcon?.classList.toggle("is-hidden", !isLight);
  }
  state.settings.theme = next;
}

function applyPowerState(enabled) {
  const button = $("power-toggle");
  if (!button) return;
  button.classList.toggle("is-off", !enabled);
  button.setAttribute("aria-pressed", enabled ? "true" : "false");
  button.setAttribute("aria-label", enabled ? "Turn extension off" : "Turn extension on");
  button.setAttribute("title", enabled ? "Turn extension off" : "Turn extension on");
}

function formatCredits(credits) {
  const captcha = credits?.captcha || credits;
  const remaining = captcha?.remaining ?? captcha?.captcha_remaining_today;
  const limit = captcha?.dailyLimit ?? captcha?.daily_limit ?? captcha?.captcha_daily_limit;
  if (remaining === undefined || limit === undefined) return "credits unavailable";
  return `${remaining}/${limit} credits`;
}

function captchaCredits(credits) {
  const captcha = credits?.captcha || credits || {};
  return {
    remaining: captcha.remaining ?? captcha.remainingToday ?? captcha.captcha_remaining_today,
    used: captcha.usedToday ?? captcha.used_today ?? captcha.captcha_used_today ?? 0,
    limit: captcha.dailyLimit ?? captcha.daily_limit ?? captcha.captcha_daily_limit
  };
}

function setActionStates(status) {
  const counts = status?.counts || {};
  const credits = captchaCredits(status?.credits);
  const extensionEnabled = isExtensionEnabled();
  const authenticated = !!status?.authenticated;
  const runtime = status?.runtime || {};
  const captchaEnabled = extensionEnabled && authenticated && state.settings.captchaEnabled !== false;
  const autofillEnabled = extensionEnabled && authenticated && runtime.autofillAllowed !== false && state.settings.autofillEnabled !== false;
  const supportedPage = !!status?.activeTab;
  const matchingRules = counts.matchingRules == null
    ? (supportedPage ? Number(counts.activeRules || 0) : 0)
    : Number(counts.matchingRules || 0);
  const quotaReached = Number(credits.remaining ?? 1) <= 0;
  const busy = state.busyButtonId;

  setDisabled("record-rule", !!busy || !supportedPage || !autofillEnabled);
  setDisabled("configure-captcha", !!busy || !captchaEnabled || !supportedPage);
  setDisabled("popup-captcha-source-pick", !!busy || !captchaEnabled || !supportedPage);
  setDisabled("popup-captcha-target-pick", !!busy || !captchaEnabled || !supportedPage);
  setDisabled("simple-solve-captcha-btn", !!busy || !captchaEnabled);
  setDisabled("simple-autofill-btn", !!busy || !supportedPage || !autofillEnabled || matchingRules === 0);
  setDisabled("manage-scripts", !!busy || !extensionEnabled || !authenticated);
}

function renderPopupScripts(status = {}) {
  const list = $("popup-scripts-list");
  if (!list) return;
  const scripts = Array.isArray(status.runningScripts) ? status.runningScripts : [];
  list.textContent = "";
  if (!scripts.length) {
    const item = document.createElement("div");
    item.className = "popup-script-item muted";
    const text = document.createElement("div");
    text.className = "popup-script-empty";
    const savedCount = Number(status.counts?.scripts || 0);
    text.textContent = !status.authenticated
      ? savedCount ? `${savedCount} saved. Sign in to run.` : "Sign in to run userscripts."
      : savedCount ? "No userscripts running on this page." : "No userscripts saved.";
    item.append(text);
    list.append(item);
    return;
  }
  for (const script of scripts) {
    const item = document.createElement("div");
    item.className = "popup-script-item";
    const copy = document.createElement("div");
    const name = document.createElement("div");
    name.className = "popup-script-name";
    name.textContent = script.name || "Untitled Script";
    copy.append(name);
    const switchLabel = document.createElement("label");
    switchLabel.className = "switch";
    switchLabel.setAttribute("aria-label", `${script.enabled === false ? "Enable" : "Disable"} ${script.name || "userscript"}`);
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = script.enabled !== false;
    input.addEventListener("change", () => togglePopupScript(script.id, input.checked));
    const slider = document.createElement("span");
    switchLabel.append(input, slider);
    item.append(switchLabel, copy);
    list.append(item);
  }
}

function renderStatus(status) {
  state.status = status || {};
  state.settings = { ...DEFAULT_SETTINGS, ...(status?.settings || {}) };
  applyTheme(state.settings.theme);
  const extensionEnabled = isExtensionEnabled();
  applyPowerState(extensionEnabled);
  document.documentElement.dataset.extensionPower = extensionEnabled ? "on" : "off";

  const authenticated = !!status?.authenticated;
  const seenWelcome = !!state.settings.seenWelcome;
  setView(authenticated, seenWelcome);

  const planName = status.plan?.name || status.plan?.code || "Free";
  if ($("account-summary")) {
    $("account-summary").textContent = !extensionEnabled
      ? "Extension paused"
      : authenticated
      ? `${planName} plan, ${formatCredits(status.credits)}`
      : "Free mode";
  }
  if ($("account-link-copy")) {
    $("account-link-copy").textContent = authenticated
      ? "Manage account and sync"
      : "Sign in / Sign up";
  }

  $("credit-progress-container").hidden = false;
  const credits = captchaCredits(status.credits);
  const remaining = credits.remaining ?? 0;
  const limit = credits.limit ?? 1;
  const used = Number(credits.used || 0);
  const usedPct = limit ? Math.max(0, Math.min(100, used ? (used / limit) * 100 : 100 - ((remaining / limit) * 100))) : 0;
  if ($("credit-remaining")) $("credit-remaining").textContent = String(remaining);
  if ($("credit-limit")) $("credit-limit").textContent = String(limit);
  $("credit-progress-bar").style.width = `${usedPct}%`;
  $("credit-progress-text").textContent = `${Math.round(usedPct)}% used`;

  $("toggle-captcha").checked = state.settings.captchaEnabled !== false;
  $("toggle-autofill").checked = state.settings.autofillEnabled !== false;
  $("toggle-scripts").checked = state.settings.userscriptsEnabled !== false;

  if ($("popup-toggle-sync")) {
    $("popup-toggle-sync").checked = !!state.settings.syncEnabled;
    $("popup-toggle-sync").disabled = !extensionEnabled || !status.authenticated;
    $("popup-sync-status").textContent = !extensionEnabled
      ? "Cloud Sync: Extension off"
      : !status.authenticated
      ? "Cloud Sync: Connect account"
      : state.settings.syncEnabled ? "Cloud Sync: Enabled" : "Cloud Sync: Disabled";
    $("popup-sync-push").disabled = !extensionEnabled || !status.authenticated || !state.settings.syncEnabled;
    $("popup-sync-pull").disabled = !extensionEnabled || !status.authenticated || !state.settings.syncEnabled;
  }

  const counts = status.counts || {};
  const supportedPage = !!status.activeTab;
  const runtime = status.runtime || {};
  const creditLimit = Number(credits.limit ?? 0);
  const creditsUnavailable = authenticated && creditLimit <= 0;
  const quotaReached = !creditsUnavailable && Number(credits.remaining ?? 1) <= 0;
  $("captcha-status").textContent = !extensionEnabled
    ? "Extension off"
    : !authenticated
    ? "Sign in required"
    : state.settings.captchaEnabled === false
    ? "Paused"
    : !supportedPage ? "Open a web page"
      : creditsUnavailable ? "Credits syncing"
      : quotaReached ? "Quota reached" : "Ready";
  $("autofill-status").textContent = !extensionEnabled
    ? "Extension off"
    : !authenticated
    ? counts.rules ? `${counts.rules} saved. Sign in to run.` : "Sign in required"
    : runtime.autofillAllowed === false
    ? "Not in current plan"
    : state.settings.autofillEnabled === false
    ? "Paused"
    : !supportedPage ? "Open a web page"
      : counts.matchingRules !== null && counts.matchingRules !== undefined
      ? counts.matchingRules ? `${counts.matchingRules} ready on this page` : counts.activeRules ? "No active rules match" : counts.rules ? "Saved, not active" : "No rules saved"
      : counts.activeRules ? `${counts.activeRules}/${counts.rules || counts.activeRules} active` : counts.rules ? "Saved, not active" : "No rules saved";
  $("scripts-status").textContent = !extensionEnabled
    ? "Extension off"
    : !authenticated
    ? counts.scripts ? `${counts.scripts} saved. Sign in to run.` : "Sign in required"
    : runtime.userscriptsAllowed === false
    ? "Not in current plan"
    : state.settings.userscriptsEnabled === false
    ? "Paused"
    : !supportedPage ? "Open a web page"
      : counts.matchingScripts !== null && counts.matchingScripts !== undefined
      ? counts.matchingScripts ? `${counts.matchingScripts} running on this page`
        : counts.activeScripts ? "No active scripts match" : counts.scripts ? "Saved, not active" : "No scripts saved"
      : counts.activeScripts ? `${counts.activeScripts}/${counts.scripts || counts.activeScripts} active` : counts.scripts ? "Saved, not active" : "No scripts saved";
  renderPopupScripts(status);

  document.querySelector('[data-module="captcha"]')?.classList.toggle("is-paused", !extensionEnabled || !authenticated || state.settings.captchaEnabled === false || quotaReached);
  document.querySelector('[data-module="autofill"]')?.classList.toggle("is-paused", !extensionEnabled || !authenticated || runtime.autofillAllowed === false || state.settings.autofillEnabled === false);
  document.querySelector('[data-module="scripts"]')?.classList.toggle("is-paused", !extensionEnabled || !authenticated || runtime.userscriptsAllowed === false || state.settings.userscriptsEnabled === false);
  for (const id of ["toggle-captcha", "toggle-autofill", "toggle-scripts"]) {
    const toggle = $(id);
    if (toggle) toggle.disabled = !extensionEnabled || !authenticated;
  }

  setActionStates(status);
  setAlert(!extensionEnabled
    ? "Extension is turned off. Use the power button to start it again."
    : status.authenticated && quotaReached ? "Daily CAPTCHA limit reached" : "");
}

async function refreshStatus() {
  const response = await sendMessage({ type: "GET_STATUS" });
  if (!response.ok) {
    showServiceUnavailable();
    return;
  }
  renderStatus(response.status);
}

async function sendPopupOtp() {
  const email = cleanAuthEmail($("popup-auth-email")?.value || "");
  const name = state.authStep === "name" ? ($("popup-auth-name")?.value.trim() || "") : "";
  const validationMessage = authEmailValidationMessage(email);
  if (validationMessage) {
    setAuthMessage(validationMessage, "error");
    $("popup-auth-email")?.focus();
    return;
  }
  if (state.authStep === "name" && !name) {
    setAuthMessage("Enter your name to create the account.", "error");
    $("popup-auth-name")?.focus();
    return;
  }

  const button = $("popup-send-otp");
  if (button) setLoading(button, true, "Sending");
  setAuthMessage(state.authStep === "name" ? "Creating account..." : "Checking email...");
  const response = await sendMessage({
    type: "REGISTER_ACCOUNT",
    payload: { identifier: email, name, planCode: "free" }
  });
  if (button) setLoading(button, false);
  if (!response.ok) {
    if (authErrorCode(response) === "name_required" || /name/i.test(response.error || "")) {
      setPopupAuthStep("name");
      setAuthMessage("Enter your name to create the account.", "neutral");
      $("popup-auth-name")?.focus();
      return;
    }
    const message = response.error || "Could not send verification code.";
    setAuthMessage(message, "error");
    return;
  }
  if (response.next_step === "profile" || response.nextStep === "profile" || response.profile_required) {
    state.authEmail = email;
    setPopupAuthStep("name");
    setAuthMessage("Enter your name to create the account.", "neutral");
    $("popup-auth-name")?.focus();
    return;
  }

  state.authChallengeId = response.challenge_id || response.challengeId || response.challenge?.id || "";
  if (!state.authChallengeId) {
    setAuthMessage("Could not start verification. Try again.", "error");
    return;
  }
  state.authEmail = email;
  if ($("popup-auth-email")) $("popup-auth-email").value = email;
  setPopupAuthStep("otp");
  const devOtp = response.dev_otp ? ` Code: ${response.dev_otp}` : "";
  setAuthMessage(`Code sent. Check your email.${devOtp}`, "success");
  $("popup-auth-otp")?.focus();
}

async function verifyPopupOtp() {
  const otp = $("popup-auth-otp")?.value.trim() || "";
  if (!state.authChallengeId || !otp) {
    setAuthMessage("Enter the verification code.", "error");
    return;
  }

  const button = $("popup-verify-otp");
  if (button) setLoading(button, true, "Verifying");
  setAuthMessage("Verifying code...");
  const response = await sendMessage({
    type: "VERIFY_OTP",
    payload: {
      challengeId: state.authChallengeId,
      otp,
      deviceName: "EazyFill Popup"
    }
  });
  if (button) setLoading(button, false);
  if (!response.ok) {
    setAuthMessage(response.error || "Verification failed.", "error");
    return;
  }

  state.authChallengeId = "";
  state.authEmail = "";
  if ($("popup-auth-otp")) {
    $("popup-auth-otp").value = "";
    $("popup-auth-otp").disabled = true;
  }
  setPopupAuthStep("email");
  setAuthMessage("Signed in. Sync and billing are ready.", "success");
  await refreshStatus();
  setTimeout(() => setPopupAuthVisible(false), 700);
}

async function saveSettings(patch) {
  const latestResponse = await sendMessage({ type: "GET_EXTENSION_STORAGE", keys: ["fp_settings"] });
  if (!latestResponse.ok) {
    if (isServiceUnavailable(latestResponse.error)) {
      showServiceUnavailable();
      return false;
    }
    setAlert(latestResponse.error || "Could not read settings", "error");
    return false;
  }
  state.settings = { ...DEFAULT_SETTINGS, ...(latestResponse.data?.fp_settings || {}), ...patch };
  const response = await sendMessage({
    type: "SET_EXTENSION_STORAGE",
    values: { fp_settings: state.settings }
  });
  if (!response.ok) {
    if (isServiceUnavailable(response.error)) {
      showServiceUnavailable();
      return;
    }
    setAlert(response.error || "Could not save settings", "error");
    return false;
  }
  renderStatus({ ...state.status, settings: state.settings });
  return true;
}

async function toggleExtensionPower() {
  const nextEnabled = !isExtensionEnabled();
  applyPowerState(nextEnabled);
  const saved = await saveSettings({ extensionEnabled: nextEnabled });
  if (saved) {
    setAlert(nextEnabled ? "Extension turned on." : "Extension turned off.", nextEnabled ? "success" : "warning");
  } else {
    applyPowerState(isExtensionEnabled());
  }
}

function openOptionsTab(tab = "") {
  const query = tab ? `?tab=${encodeURIComponent(tab)}` : "";
  const url = chrome.runtime.getURL(`options/options.html${query}`);
  chrome.tabs.create({ url });
}

async function togglePopupScript(scriptId, enabled) {
  if (!scriptId) return;
  const data = await getStorage(["fp_scripts"]);
  const scripts = Array.isArray(data.fp_scripts) ? data.fp_scripts : [];
  const nextScripts = scripts.map((script) => (
    String(script?.id || "") === String(scriptId)
      ? { ...script, enabled: enabled === true, updatedAt: Date.now() }
      : script
  ));
  await setStorage({ fp_scripts: nextScripts });
  await sendMessage({ type: "USERSCRIPTS_REGISTER" }).catch(() => null);
  await refreshStatus();
}

async function runPopupSync(actionType) {
  const button = $(actionType === "SYNC_PUSH" ? "popup-sync-push" : "popup-sync-pull");
  if (button) setLoading(button, true, actionType === "SYNC_PUSH" ? "Pushing" : "Pulling");
  const response = await sendMessage({ type: actionType });
  if (button) setLoading(button, false);
  if (!response.ok) {
    setAlert(response.error || `${actionType} failed.`, "error");
    return;
  }
  setAlert(actionType === "SYNC_PUSH" ? "Cloud push completed." : "Cloud pull completed.", "success");
  await refreshStatus();
}

async function restoreCaptchaRouteDraft() {
  try {
    const data = await getStorage(["fp_popup_captcha_route_draft", "fp_captcha_selectors"]);
    const draft = data.fp_popup_captcha_route_draft && typeof data.fp_popup_captcha_route_draft === "object"
      ? data.fp_popup_captcha_route_draft
      : {};
    const domain = normalizeDomain(draft.domain || activeDomain());
    const savedRoutes = domain ? captchaRoutesForDomain(data.fp_captcha_selectors, domain) : {};
    const saved = Object.values(savedRoutes)[0] || {};
    const source = draft.sourceSelector || saved.sourceSelector || saved.source || "";
    const target = draft.targetSelector || saved.targetSelector || saved.target || "";
    if ($("popup-captcha-source")) $("popup-captcha-source").value = source;
    if ($("popup-captcha-target")) $("popup-captcha-target").value = target;
  } catch (_) {
    // Draft restore is a convenience. The popup remains usable without it.
  }
}

async function beginCaptchaRoutePick(targetField) {
  const button = targetField === "captcha-source" ? $("popup-captcha-source-pick") : $("popup-captcha-target-pick");
  if (button) setLoading(button, true, "Pick");
  const response = await sendMessage({ type: "PICK_ELEMENT_CURRENT", targetField });
  if (button) setLoading(button, false);
  if (!response.ok) {
    if (isServiceUnavailable(response.error)) {
      showServiceUnavailable();
      return false;
    }
    setAlert(response.error || "Could not start selector picker.", "warning");
    return;
  }
  setAlert("Pick an element on the page. Press Esc to cancel.", "success");
  window.close();
}

async function saveCaptchaRoute() {
  const button = $("configure-captcha");
  const sourceSelector = $("popup-captcha-source").value.trim();
  const targetSelector = $("popup-captcha-target").value.trim();
  const domain = activeDomain();
  const learningConsent = state.settings.captchaLearningConsent === true;

  if (!domain) {
    setAlert("Open an HTTP page before saving a CAPTCHA route.", "warning");
    return;
  }
  if (!sourceSelector || !targetSelector) {
    setAlert("Pick both source and target selectors first.", "warning");
    return;
  }

  setLoading(button, true, "Saving");
  try {
    const data = await getStorage(["fp_captcha_selectors"]);
    let fieldName = await stableCaptchaFieldName(domain, sourceSelector, targetSelector);
    let routeStatus = "local_only";
    let proposalId = null;
    let sample = null;
    let lastSubmittedAt = null;
    try {
      const statusResponse = await sendMessage({
        type: "CAPTCHA_ROUTE_STATUS",
        payload: {
          domain,
          source_selector: sourceSelector,
          target_selector: targetSelector
        }
      });
      if (statusResponse.ok && statusResponse.status) {
        routeStatus = statusResponse.status;
        proposalId = statusResponse.proposal_id || null;
        fieldName = statusResponse.field_name || fieldName;
      }
    } catch (_) {
      routeStatus = "local_only";
    }
    if (learningConsent) {
      const captured = await sendMessage({
        type: "CAPTCHA_CAPTURE_ROUTE_SAMPLE",
        sourceSelector,
        targetSelector
      });
      if (captured.ok) sample = captured;
    }
    try {
      const proposal = await sendMessage({
        type: "CAPTCHA_ROUTE_PROPOSE",
        payload: {
          domain,
          source_selector: sourceSelector,
          target_selector: targetSelector,
          field_name: fieldName,
          page_url: state.status?.activeTab?.url || "",
          learning_consent: learningConsent,
          consent_version: learningConsent ? "captcha-learning-v1" : "",
          sample_payload_base64: learningConsent ? (sample?.payloadBase64 || "") : "",
          user_label: learningConsent ? (sample?.userLabel || "") : "",
          metadata: learningConsent ? (sample?.metadata || {}) : {}
        }
      });
      if (proposal.ok) {
        lastSubmittedAt = Date.now();
        routeStatus = proposal.status || proposal.data?.status || routeStatus;
        proposalId = proposal.proposal_id || proposal.data?.proposal_id || null;
        fieldName = proposal.field_name || proposal.data?.field_name || fieldName;
      }
    } catch (_) {
      routeStatus = "local_only";
    }
    const next = {
      ...(data.fp_captcha_selectors || {})
    };
    const currentRoutes = captchaRoutesForDomain(next, domain);
    const existingRoute = currentRoutes[fieldName] || {};
    const routeConfig = withActiveRouteProfile({
        ...existingRoute,
        id: fieldName,
        domain,
        fieldName,
        sourceSelector,
        targetSelector,
        taskType: "image",
        autoSolve: routeStatus === "approved",
        routeStatus,
        proposalId,
        lastSubmittedAt,
        learningConsent,
        updatedAt: Date.now()
    });
    next[domain] = {
      domain,
      activeFieldName: fieldName,
      routes: {
        ...currentRoutes,
        [fieldName]: routeConfig
      },
      updatedAt: Date.now()
    };
    await setStorage({
      fp_captcha_selectors: next,
      fp_popup_captcha_route_draft: {}
    });
    await sendMessage({ type: "CAPTCHA_CONFIG_UPDATED" });
    await refreshStatus();
    if (routeStatus === "approved") {
      setAlert(`CAPTCHA route ready for ${domain}.`, "success");
    } else if (routeStatus === "pending") {
      setAlert(`Route saved and submitted for support.`, "success");
    } else {
      setAlert(`Route saved locally. Sign in to submit it for support.`, "warning");
    }
  } catch (error) {
    setAlert(error.message || "Could not save CAPTCHA route.", "error");
  } finally {
    setLoading(button, false);
  }
}

async function softAction(type, fallbackMessage, preferredButtonId = "") {
  const buttonByType = {
    AUTOFILL_EXECUTE_CURRENT: "simple-autofill-btn",
    START_RECORDING: "record-rule"
  };
  const button = $(preferredButtonId || buttonByType[type]);
  const loadingLabel = type === "START_RECORDING" ? "Recording" : "Filling";
  state.busyButtonId = button?.id || null;
  if (button) setLoading(button, true, loadingLabel);
  setActionStates(state.status || {});
  const response = await sendMessage({ type });
  state.busyButtonId = null;
  if (button) setLoading(button, false);
  setActionStates(state.status || {});
  if (!response.ok) {
    if (isServiceUnavailable(response.error)) {
      showServiceUnavailable();
      return;
    }
    setAlert(/no matching|no supported active tab/i.test(response.error || "") ? fallbackMessage : (response.error || fallbackMessage), "warning");
    return;
  }
  if (type === "AUTOFILL_EXECUTE_CURRENT" && !response.executedRules) {
    const planLimited = Number(response.planLimitedRules || 0);
    const matched = Number(response.matchedRules || 0);
    setAlert(planLimited > 0 && matched > 0
      ? "Matching autofill rule is saved but not active in your current plan."
      : fallbackMessage, "warning");
    return;
  }
  setAlert("");
  window.close();
}

function updateAdvancedModeUI() {
  const toggle = $("toggle-advanced-mode");
  if (toggle) toggle.checked = true;

  const simple = $("simple-app-controls");
  const advanced = $("advanced-app-controls");
  if (simple) simple.hidden = true;
  if (advanced) advanced.hidden = false;
}

function setModuleExpanded(moduleName, expanded) {
  const button = document.querySelector(`[data-module-toggle="${moduleName}"]`);
  const detail = $(`${moduleName}-detail`);
  if (!button || !detail) return;
  button.setAttribute("aria-expanded", expanded ? "true" : "false");
  detail.hidden = !expanded;
}

function bindModuleDisclosures() {
  for (const button of document.querySelectorAll("[data-module-toggle]")) {
    button.addEventListener("click", () => {
      const moduleName = button.dataset.moduleToggle;
      const expanded = button.getAttribute("aria-expanded") === "true";
      setModuleExpanded(moduleName, !expanded);
    });
  }
}

function handleAccountLink() {
  if (state.status?.authenticated) {
    openOptionsTab("account-panel");
    return;
  }
  setAlert("");
  setPopupAuthVisible(true);
}

document.addEventListener("DOMContentLoaded", async () => {
  // Advanced Mode Toggle
  const toggleAdvanced = $("toggle-advanced-mode");
  if (toggleAdvanced) {
    toggleAdvanced.addEventListener("change", (e) => {
      localStorage.setItem("advancedMode", e.target.checked ? "true" : "false");
      updateAdvancedModeUI();
    });
  }
  updateAdvancedModeUI();
  bindModuleDisclosures();

  // Simple Mode Buttons
  $("simple-autofill-btn")?.addEventListener("click", () => softAction("AUTOFILL_EXECUTE_CURRENT", "No matching autofill rule found for this page.", "simple-autofill-btn"));
  $("simple-solve-captcha-btn")?.addEventListener("click", () => setModuleExpanded("captcha", true));

  // Advanced Mode Sync
  $("popup-toggle-sync")?.addEventListener("change", (e) => saveSettings({ syncEnabled: e.target.checked }));
  $("popup-sync-push")?.addEventListener("click", () => runPopupSync("SYNC_PUSH"));
  $("popup-sync-pull")?.addEventListener("click", () => runPopupSync("SYNC_PULL"));

  // Original bindings
  $("retry-status").addEventListener("click", refreshStatus);

  $("theme-toggle").addEventListener("click", async () => {
    const next = state.settings.theme === "light" ? "dark" : "light";
    applyTheme(next);
    await saveSettings({ theme: next });
  });

  $("power-toggle")?.addEventListener("click", toggleExtensionPower);

  const skipWelcome = async () => {
    await saveSettings({ seenWelcome: true });
    setView(false, true);
  };
  $("btn-get-started")?.addEventListener("click", skipWelcome);
  $("btn-enter-key")?.addEventListener("click", skipWelcome);

  $("toggle-captcha").addEventListener("change", (event) => saveSettings({ captchaEnabled: event.target.checked }));
  $("toggle-autofill").addEventListener("change", (event) => saveSettings({ autofillEnabled: event.target.checked }));
  $("toggle-scripts").addEventListener("change", (event) => saveSettings({ userscriptsEnabled: event.target.checked }));

  $("configure-captcha").addEventListener("click", saveCaptchaRoute);
  $("popup-captcha-source-pick")?.addEventListener("click", () => beginCaptchaRoutePick("captcha-source"));
  $("popup-captcha-target-pick")?.addEventListener("click", () => beginCaptchaRoutePick("captcha-target"));
  $("record-rule").addEventListener("click", () => softAction("START_RECORDING", "Open an HTTP page and try recording again.", "record-rule"));
  $("manage-scripts")?.addEventListener("click", () => setModuleExpanded("scripts", true));
  $("account-link")?.addEventListener("click", handleAccountLink);
  $("popup-auth-close")?.addEventListener("click", () => setPopupAuthVisible(false));
  $("popup-send-otp")?.addEventListener("click", sendPopupOtp);
  $("popup-verify-otp")?.addEventListener("click", verifyPopupOtp);
  $("popup-auth-email")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") sendPopupOtp();
  });
  $("popup-auth-name")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") sendPopupOtp();
  });
  $("popup-auth-otp")?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") verifyPopupOtp();
  });

  setPopupAuthStep("email");
  await refreshStatus();
  await restoreCaptchaRouteDraft();
});
