import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const extensionRoot = path.join(repoRoot, "extension");
const snapshotDir = process.env.EAZYFILL_UI_SNAPSHOT_DIR
  ? path.resolve(process.env.EAZYFILL_UI_SNAPSHOT_DIR)
  : "";
const extensionManifest = JSON.parse(fs.readFileSync(path.join(extensionRoot, "manifest.json"), "utf8"));
assert.ok(extensionManifest.permissions.includes("webNavigation"));
assert.ok(extensionManifest.permissions.includes("downloads"));
assert.ok(extensionManifest.content_scripts.some((script) => (
  script.matches?.includes("*://*/*.user.js*")
  && script.js?.includes("content/userscript-installer.js")
)));
const serviceWorkerSource = fs.readFileSync(path.join(extensionRoot, "background", "service-worker.js"), "utf8");
assert.match(serviceWorkerSource, /installUserscriptNavigationHandler\(\);/);
assert.match(serviceWorkerSource, /installUserScript=/);
const popupHtml = fs.readFileSync(path.join(extensionRoot, "popup", "popup.html"), "utf8");
assert.match(popupHtml, /<html[^>]+data-theme="light"/);
assert.match(popupHtml, /id="brand-logo"[^>]+src="\.\.\/brand\/logo-dark\.png"/);
assert.match(popupHtml, /class="theme-icon sun-icon is-hidden"/);
assert.match(popupHtml, /class="theme-icon moon-icon"/);
const contentTypes = {
  ".css": "text/css",
  ".html": "text/html",
  ".js": "text/javascript",
  ".svg": "image/svg+xml"
};

function chromeExecutable() {
  const candidates = [
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe"
  ];
  const executable = candidates.find((candidate) => fs.existsSync(candidate));
  if (!executable) throw new Error("Chrome or Edge executable not found");
  return executable;
}

async function captureSnapshot(page, name) {
  if (!snapshotDir) return;
  fs.mkdirSync(snapshotDir, { recursive: true });
  await page.screenshot({
    path: path.join(snapshotDir, `${name}.png`),
    fullPage: true
  });
}

function startServer() {
  const server = http.createServer((request, response) => {
    const pathname = new URL(request.url, "http://127.0.0.1").pathname;
    const relativePath = pathname.replace(/^\/+/, "");
    const filePath = path.resolve(extensionRoot, relativePath);
    if (!filePath.startsWith(extensionRoot) || !fs.existsSync(filePath) || fs.statSync(filePath).isDirectory()) {
      response.writeHead(404);
      response.end("Not found");
      return;
    }
    response.writeHead(200, { "Content-Type": contentTypes[path.extname(filePath)] || "application/octet-stream" });
    fs.createReadStream(filePath).pipe(response);
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve(server));
  });
}

async function installChromeMock(page, mode) {
  await page.addInitScript(({ mockMode }) => {
    const localScriptCode = `// ==UserScript==
// @name         Local Helper
// @namespace    eazyfill.local
// @version      1.0.0
// @match        https://example.com/*
// @grant        none
// ==/UserScript==

(function () {
  "use strict";
})();
`;
    const remoteScriptCode = `// ==UserScript==
// @name         Remote Helper
// @namespace    eazyfill.remote
// @version      2.0.0
// @match        https://example.com/*
// @grant        GM_download
// @require      https://cdn.example.test/helper.js
// @connect      api.example.test
// ==/UserScript==

(function () {
  "use strict";
})();
`;
    const extensionStorage = {
      fp_settings: {
        activeProfileId: "work",
        captchaEnabled: true,
        autofillEnabled: true,
        userscriptsEnabled: true,
        seenWelcome: true,
        theme: "dark"
      },
      fp_rules: [{
        id: "rule_login",
        name: "Saved Login",
        domain: "example.com",
        profileId: "work",
        enabled: true,
        steps: [{
          order: 1,
          label: "Email",
          action: "set_value",
          selector: { primary: "#email", css: "#email" },
          value: "{{email}}"
        }]
      }],
      fp_profiles: [{
        id: "work",
        name: "Work",
        values: { email: "work@example.com" }
      }],
      fp_scripts: [{
        id: "local-script",
        name: "Local Helper",
        version: "1.0.0",
        profileId: "work",
        enabled: true,
        source: "local",
        rawCode: localScriptCode,
        parsedMeta: {
          name: "Local Helper",
          version: "1.0.0",
          matches: ["https://example.com/*"],
          includes: [],
          grants: ["none"],
          runAt: "document-idle",
          tags: ["Migrated"]
        }
      }, {
        id: "remote-script",
        name: "Remote Helper",
        version: "2.0.0",
        profileId: "work",
        enabled: true,
        source: "remote",
        sourceUrl: "https://cdn.example.test/remote.user.js",
        updateUrl: "https://cdn.example.test/remote.user.js",
        rawCode: remoteScriptCode,
        parsedMeta: {
          name: "Remote Helper",
          version: "2.0.0",
          matches: ["https://example.com/*"],
          includes: [],
          grants: ["GM_download"],
          requires: ["https://cdn.example.test/helper.js"],
          connects: ["api.example.test"],
          runAt: "document-idle",
          tags: ["Migrated"]
        }
      }],
      fp_captcha_selectors: {}
    };
    let isAuthenticated = mockMode !== "unauthenticated";
    const availableStatus = {
      authenticated: isAuthenticated,
      activeTab: { url: "https://example.com/form", hostname: "example.com" },
      plan: { name: "Free" },
      credits: { captcha: { remaining: 5, dailyLimit: 10, usedToday: 1 } },
      settings: {
        activeProfileId: "work",
        captchaEnabled: true,
        autofillEnabled: true,
        userscriptsEnabled: true,
        seenWelcome: true,
        theme: "dark"
      },
      counts: { rules: 2, matchingRules: 0, scripts: 2, matchingScripts: 0 }
    };
    const currentStatus = () => {
      const pageScripts = (Array.isArray(extensionStorage.fp_scripts) ? extensionStorage.fp_scripts : [])
        .map((script) => ({
          id: script.id,
          name: script.name || script.parsedMeta?.name || "Untitled Script",
          version: script.version || script.parsedMeta?.version || "1.0.0",
          enabled: script.enabled !== false,
          source: script.source || "local"
        }));
      return {
        ...availableStatus,
        authenticated: isAuthenticated,
        plan: isAuthenticated ? { name: "Free" } : null,
        counts: {
          ...availableStatus.counts,
          scripts: pageScripts.filter((script) => script.enabled !== false).length,
          matchingScripts: pageScripts.filter((script) => script.enabled !== false).length
        },
        runningScripts: pageScripts
      };
    };
    const runtime = {
      lastError: null,
      openOptionsPage() {},
      getURL(pathname = "") {
        return String(pathname).replace(/^\/+/, "");
      },
      sendMessage(message, callback) {
        if (mockMode === "unavailable") {
          runtime.lastError = { message: "Could not establish connection. Receiving end does not exist." };
          callback();
          runtime.lastError = null;
          return;
        }
        if (message.type === "REGISTER_ACCOUNT") {
          callback({ ok: true, challenge_id: "challenge-test", dev_otp: "123456", delivery: "email" });
          return;
        }
        if (message.type === "VERIFY_OTP") {
          isAuthenticated = true;
          extensionStorage.fp_auth = {
            apiKey: "fp_created",
            valid: true,
            user: { email: "user@gmail.com" },
            plan: { name: "Free" },
            credits: { captcha: { remaining: 5, dailyLimit: 10, usedToday: 1 } },
            device: { status: "active" }
          };
          callback({ ok: true, auth: { authenticated: true } });
          return;
        }
        if (message.type === "SET_EXTENSION_STORAGE") {
          Object.assign(extensionStorage, message.values || {});
          callback({ ok: true });
          return;
        }
        const responses = {
          GET_STATUS: { ok: true, status: currentStatus() },
          GET_EXTENSION_STORAGE: { ok: true, data: extensionStorage },
          USERSCRIPTS_STATUS: { ok: true, available: false, error: "Allow User Scripts" },
          BILLING_PLANS: {
            ok: true,
            plans: [{
              id: 1,
              code: "free",
              name: "Free",
              price: { amount: 0, currency: "INR" },
              duration_days: 30,
              limits: { captcha_daily_limit: 100, max_devices: 1 },
              features: { autofill: true, userscripts: true, captcha: true, cloud_sync: false }
            }, {
              id: 2,
              code: "pro",
              name: "Pro",
              price: { amount: 49900, currency: "INR" },
              duration_days: 30,
              limits: { captcha_daily_limit: 1000, max_devices: 3 },
              features: { autofill: true, userscripts: true, captcha: true, cloud_sync: true, priority_solving: true }
            }],
            payment_providers: [{ code: "razorpay", name: "Razorpay", available: true }]
          },
          BILLING_HISTORY: { ok: true, items: [] },
          CREDIT_HISTORY: { ok: true, items: [] }
        };
        callback(responses[message.type] || { ok: true });
      }
    };
    globalThis.__openedExtensionTabs = [];
    globalThis.__runtimeMessages = [];
    globalThis.chrome = {
      runtime,
      tabs: {
        create({ url }) {
          globalThis.__openedExtensionTabs.push(url);
        }
      }
    };
    const originalSendMessage = runtime.sendMessage.bind(runtime);
    runtime.sendMessage = (message, callback) => {
      globalThis.__runtimeMessages.push(message);
      return originalSendMessage(message, callback);
    };
  }, { mockMode: mode });
}

const server = await startServer();
const baseUrl = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ executablePath: chromeExecutable(), headless: true });

try {
  const optionsPage = await browser.newPage();
  const optionsPageErrors = [];
  optionsPage.on("pageerror", (error) => optionsPageErrors.push(error.message));
  optionsPage.on("console", (message) => {
    if (message.type() === "error") optionsPageErrors.push(message.text());
  });
  await installChromeMock(optionsPage, "available");
  await optionsPage.goto(`${baseUrl}/options/options.html`);
  await optionsPage.waitForSelector("#overview-panel.active");
  await optionsPage.waitForFunction(() => document.querySelector("#connection-label")?.textContent !== "Checking status")
    .catch((error) => {
      throw new Error(`${error.message}\nOptions page errors: ${optionsPageErrors.join(" | ") || "none"}`);
    });
  assert.equal(await optionsPage.locator("#panel-title").innerText(), "Overview");
  await captureSnapshot(optionsPage, "options-overview");
  assert.equal(await optionsPage.locator('.nav-item[data-panel="billing-panel"]').count(), 0);
  await optionsPage.locator('.nav-item[data-panel="account-panel"]').click();
  await optionsPage.waitForSelector("#account-panel.active");
  assert.equal(await optionsPage.locator("#panel-title").innerText(), "Account & Plan");
  assert.equal(await optionsPage.locator("#options-send-otp-btn").innerText(), "Continue with Email");
  assert.equal(await optionsPage.locator("#options-api-key").count(), 0);
  await optionsPage.waitForFunction(() => document.querySelectorAll("#plans-grid .plan-card").length >= 2);
  assert.equal(await optionsPage.locator("#credit-packs-surface").isHidden(), true);
  assert.equal(await optionsPage.getByRole("button", { name: "Sign In First" }).count(), 2);
  await optionsPage.getByRole("button", { name: "Sign In First" }).nth(1).click();
  await optionsPage.waitForFunction(() => document.activeElement?.id === "options-signup-identifier");
  assert.equal(await optionsPage.evaluate(() => globalThis.__runtimeMessages.some((message) => message.type === "BILLING_CREATE_ORDER")), false);
  await optionsPage.locator('.nav-item[data-panel="profiles-panel"]').click();
  await optionsPage.waitForSelector("#profiles-panel.active");
  assert.equal(await optionsPage.locator("#active-profile-id").inputValue(), "work");
  assert.match(await optionsPage.locator("#active-profile-summary").innerText(), /1 rules \| 2 scripts \| 0 CAPTCHA routes/);
  assert.equal(await optionsPage.locator("#profile-values").count(), 0);
  assert.equal(await optionsPage.locator("#profile-items-surface").isHidden(), true);
  await optionsPage.locator('#profiles-table tr[data-id="work"]').getByRole("button", { name: "Edit" }).click();
  await optionsPage.waitForSelector("#profile-items-surface:not(.is-hidden)");
  assert.equal(await optionsPage.locator("#profile-items-title").innerText(), "Work Automations");
  assert.equal(await optionsPage.locator("#profile-items-table").getByText("Autofill Rules").count(), 1);
  assert.equal(await optionsPage.locator("#profile-items-table").getByText("Userscripts").count(), 1);
  assert.equal(await optionsPage.locator("#profile-items-table").getByText("Saved Login").count(), 1);
  assert.equal(await optionsPage.locator("#profile-items-table").getByText("Local Helper").count(), 1);
  assert.equal(await optionsPage.locator("#profile-items-table").getByText("#email").count(), 0);
  assert.equal(await optionsPage.locator("#profile-items-table").getByRole("button", { name: "Clone" }).count(), 3);
  await optionsPage.locator("#profile-item-select-all").check();
  assert.equal(await optionsPage.locator("#profile-items-selection-summary").innerText(), "3 selected");
  assert.equal(await optionsPage.locator("#profile-clone-selected-btn").isDisabled(), false);
  assert.equal(await optionsPage.locator("#profile-bulk-clone-target").inputValue(), "default");
  await optionsPage.locator("#profile-clone-selected-btn").click();
  await optionsPage.waitForFunction(() => (
    globalThis.__runtimeMessages.some((message) => (
      message.type === "SET_EXTENSION_STORAGE"
      && message.values?.fp_rules?.[0]?.profileIds?.includes("default")
      && message.values?.fp_scripts?.every((script) => script.profileIds?.includes("default"))
    ))
  ));
  await optionsPage.locator('.nav-item[data-panel="rules-panel"]').click();
  await optionsPage.waitForSelector("#rules-panel.active");
  assert.equal(await optionsPage.locator("#panel-title").innerText(), "Autofill");
  const savedRuleRow = optionsPage.locator('#rules-table tr[data-id="rule_login"]');
  await savedRuleRow.waitFor();
  await savedRuleRow.getByRole("button", { name: "Edit" }).click();
  await optionsPage.waitForSelector("#rules-editor-view:not(.is-hidden)");
  assert.equal(await optionsPage.locator("#rule-name").inputValue(), "Saved Login");
  assert.equal(await optionsPage.locator("#rule-profile-id").inputValue(), "work");
  await optionsPage.locator("#rule-back-btn").click();
  await optionsPage.locator('.nav-item[data-panel="scripts-panel"]').click();
  await optionsPage.waitForSelector("#scripts-panel.active");
  await captureSnapshot(optionsPage, "options-userscripts");
  assert.equal(await optionsPage.locator("#script-editor-card").isHidden(), true);
  assert.equal(await optionsPage.locator("#script-register-btn").count(), 0);
  const localScriptRow = optionsPage.locator('#scripts-table tr[data-id="local-script"]');
  const remoteScriptRow = optionsPage.locator('#scripts-table tr[data-id="remote-script"]');
  assert.equal(await localScriptRow.getByRole("button", { name: "Edit" }).count(), 1);
  assert.equal(await remoteScriptRow.getByRole("button", { name: "Refresh" }).count(), 1);
  assert.equal(await remoteScriptRow.getByRole("button", { name: "Edit" }).count(), 0);
  assert.equal(await optionsPage.locator(".userscripts-scroll").evaluate((node) => node.scrollWidth <= node.clientWidth + 1), true);
  assert.equal(await remoteScriptRow.locator(".script-display-name").getAttribute("href"), "https://cdn.example.test/remote.user.js");
  assert.equal(await remoteScriptRow.locator("td").nth(4).getAttribute("title"), "Matches:\n- https://example.com/*");
  assert.deepEqual(await remoteScriptRow.locator(".script-feature-chips .admin-chip").allInnerTexts(), ["GM", "Require 1", "Connect 1", "Download"]);
  assert.equal(await remoteScriptRow.locator(".script-feature-chips").evaluate((node) => getComputedStyle(node).flexDirection), "column");
  assert.equal(await optionsPage.locator("#scripts-table").getByText("Migrated").count(), 0);
  assert.equal(await optionsPage.locator("#script-import-url-input").count(), 1);
  assert.equal(await optionsPage.locator("#script-import-direct-btn").count(), 1);
  await optionsPage.route("https://greasyfork.org/scripts/12345/code/youtube-downloader.user.js", (route) => route.fulfill({
    status: 200,
    contentType: "text/javascript",
    headers: { "access-control-allow-origin": "*" },
    body: `// ==UserScript==
// @name:vi      GreasyFork Downloader Localized
// @name         GreasyFork Downloader
// @namespace    eazyfill.test
// @version      1.2.3
// @description:vi Localized description
// @description  Default description
// @include      *://*.youtube.com/**
// @grant        GM_download
// @require      https://cdn.example.test/helper.js
// ==/UserScript==

window.__greasyForkImport = true;
`
  }));
  await optionsPage.route("https://cdn.example.test/helper.js", (route) => route.fulfill({
    status: 200,
    contentType: "text/javascript",
    headers: { "access-control-allow-origin": "*" },
    body: "window.__requiredHelperLoaded = true;"
  }));
  await optionsPage.locator("#script-import-url-input").fill("https://greasyfork.org/en/scripts/12345-youtube-downloader");
  await optionsPage.locator("#script-import-direct-btn").click();
  await optionsPage.waitForFunction(() => (
    globalThis.__runtimeMessages
      .filter((message) => message.type === "SET_EXTENSION_STORAGE")
      .flatMap((message) => message.values?.fp_scripts || [])
      .some((script) => script.name === "GreasyFork Downloader")
  ));
  const importedScript = await optionsPage.evaluate(() => (
    globalThis.__runtimeMessages
      .filter((message) => message.type === "SET_EXTENSION_STORAGE")
      .flatMap((message) => message.values?.fp_scripts || [])
      .find((script) => script.name === "GreasyFork Downloader")
  ));
  assert.equal(importedScript.sourceUrl, "https://greasyfork.org/scripts/12345/code/youtube-downloader.user.js");
  assert.match(importedScript.requiredCode, /requiredHelperLoaded/);
  assert.equal(importedScript.parsedMeta.description, "Default description");
  assert.deepEqual(importedScript.parsedMeta.matches, []);
  assert.deepEqual(importedScript.parsedMeta.includes, ["*://*.youtube.com/**"]);
  assert.deepEqual(importedScript.profileIds, ["default"]);
  await localScriptRow.getByRole("button", { name: "Edit" }).click();
  await optionsPage.waitForSelector("#script-editor-card:not(.is-hidden)");
  await optionsPage.waitForSelector("#script-editor-container .cm-editor");
  assert.equal(await optionsPage.locator("#script-name").inputValue(), "Local Helper");
  assert.equal(await optionsPage.locator("#script-version").inputValue(), "1.0.0");
  const scriptEditorBox = await optionsPage.locator("#script-editor-container").boundingBox();
  assert.ok(scriptEditorBox.height >= 500);
  await optionsPage.locator("#script-font-size").selectOption("18px");
  const scriptEditorFontSize = await optionsPage.locator("#script-editor-container .cm-scroller").evaluate((node) => getComputedStyle(node).fontSize);
  assert.equal(scriptEditorFontSize, "18px");
  await optionsPage.evaluate(() => {
    const code = `// ==UserScript==
// @name         Metadata Sync Test
// @namespace    eazyfill.local
// @version      9.8.7
// @match        https://metadata.example/*
// @grant        none
// ==/UserScript==

(function () {})();
`;
    window.scriptEditor.dispatch({
      changes: { from: 0, to: window.scriptEditor.state.doc.length, insert: code }
    });
  });
  await optionsPage.waitForFunction(() => (
    document.querySelector("#script-name")?.value === "Metadata Sync Test"
    && document.querySelector("#script-version")?.value === "9.8.7"
    && document.querySelector("#script-match")?.value === "https://metadata.example/*"
  ));
  await optionsPage.locator("#script-discard-btn").click();
  assert.equal(await optionsPage.locator("#script-editor-card").isHidden(), true);
  await optionsPage.locator("#script-new-btn").click();
  assert.equal(await optionsPage.locator("#script-editor-card").isVisible(), true);
  await optionsPage.locator("#script-editor-close-btn").click();
  assert.equal(await optionsPage.locator("#script-editor-card").isHidden(), true);
  await optionsPage.locator('.nav-item[data-panel="captcha-panel"]').click();
  assert.equal(await optionsPage.locator("#captcha-fill-delay").inputValue(), "200");
  assert.equal(await optionsPage.locator("#captcha-human-typing").isChecked(), true);
  assert.equal(await optionsPage.locator("#captcha-learning-consent").isChecked(), true);
  assert.equal(await optionsPage.locator("#captcha-refresh-btn").count(), 0);
  await optionsPage.locator("#captcha-fill-delay").fill("450");
  await optionsPage.evaluate(() => {
    const input = document.querySelector("#captcha-human-typing");
    input.checked = true;
    input.dispatchEvent(new Event("change", { bubbles: true }));
    const consent = document.querySelector("#captcha-learning-consent");
    consent.checked = true;
    consent.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await optionsPage.locator("#captcha-save-behavior-btn").click();
  await optionsPage.waitForFunction(() => /CAPTCHA behavior saved/i.test(document.querySelector("#toast")?.textContent || ""));
  const globalCaptchaSettings = await optionsPage.evaluate(() => (
    globalThis.__runtimeMessages
      .filter((message) => message.type === "SET_EXTENSION_STORAGE")
      .map((message) => message.values?.fp_settings)
      .find((settings) => settings?.captchaFillDelayMs === 450)
  ));
  assert.equal(globalCaptchaSettings.captchaFillDelayMs, 450);
  assert.equal(globalCaptchaSettings.captchaHumanTyping, true);
  assert.equal(globalCaptchaSettings.captchaLearningConsent, true);
  await optionsPage.locator("#captcha-domain").fill("Example.com");
  await optionsPage.locator("#captcha-field-name").fill("login_captcha");
  await optionsPage.locator("#captcha-source-selector").fill("#captchaText");
  await optionsPage.locator("#captcha-target-selector").fill("#captchaAnswer");
  await optionsPage.evaluate(() => {
    const input = document.querySelector("#captcha-auto-solve");
    input.checked = true;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await optionsPage.locator("#captcha-save-config-btn").click();
  await optionsPage.waitForFunction(() => globalThis.__runtimeMessages.some((message) => message.values?.fp_captcha_selectors?.["example.com"]));
  const firstRouteSaveCount = await optionsPage.evaluate(() => (
    globalThis.__runtimeMessages.filter((message) => message.values?.fp_captcha_selectors?.["example.com"]).length
  ));
  await optionsPage.locator("#captcha-save-config-btn").click();
  await optionsPage.waitForFunction((count) => (
    globalThis.__runtimeMessages.filter((message) => message.values?.fp_captcha_selectors?.["example.com"]).length > count
  ), firstRouteSaveCount);
  const captchaSelectors = await optionsPage.evaluate(() => (
    globalThis.__runtimeMessages
      .filter((message) => message.values?.fp_captcha_selectors?.["example.com"])
      .at(-1)
      .values.fp_captcha_selectors
  ));
  assert.equal(Object.keys(captchaSelectors["example.com"].routes).length, 1);
  const savedCaptchaRoute = Object.values(captchaSelectors["example.com"].routes)[0];
  assert.equal(savedCaptchaRoute.fieldName, "login_captcha");
  assert.equal(savedCaptchaRoute.profileId, "default");
  assert.deepEqual(savedCaptchaRoute.profileIds, ["default"]);

  const popupPage = await browser.newPage();
  await installChromeMock(popupPage, "available");
  await popupPage.goto(`${baseUrl}/popup/popup.html`);
  await popupPage.waitForSelector("#app-view.active");
  await captureSnapshot(popupPage, "popup-authenticated");
  assert.equal(await popupPage.locator("#autofill-status").innerText(), "No rules match this page");
  assert.equal(await popupPage.locator("#scripts-status").innerText(), "2 EazyFill matches");
  assert.equal(await popupPage.locator("#account-summary").count(), 0);
  assert.equal(await popupPage.locator("#simple-autofill-btn").isDisabled(), true);
  assert.equal(await popupPage.locator("#simple-solve-captcha-btn").isDisabled(), false);
  assert.equal(await popupPage.locator("#auth-view").count(), 0);
  assert.equal(await popupPage.locator(".account-card").count(), 0);
  assert.equal(await popupPage.locator("#account-link-copy").innerText(), "Manage account and sync");
  await popupPage.locator('[data-module-toggle="scripts"]').click();
  assert.equal(await popupPage.locator("#popup-scripts-summary").count(), 0);
  assert.equal(await popupPage.locator("#popup-scripts-open").count(), 0);
  assert.equal(await popupPage.locator("#new-script").count(), 0);
  assert.equal(await popupPage.locator("#popup-scripts-list").getByText("Local Helper").count(), 1);
  assert.equal(await popupPage.locator("#popup-scripts-list").getByText("Remote Helper").count(), 1);
  const localPopupScript = popupPage.locator(".popup-script-item").filter({ hasText: "Local Helper" });
  await localPopupScript.locator("label.switch").click();
  await popupPage.waitForFunction(() => (
    globalThis.__runtimeMessages.some((message) => message.type === "USERSCRIPTS_REGISTER")
    && globalThis.__runtimeMessages
      .filter((message) => message.type === "SET_EXTENSION_STORAGE")
      .some((message) => (
        (message.values?.fp_scripts || []).some((script) => script.id === "local-script" && script.enabled === false)
      ))
  ));
  await popupPage.locator("#account-link").click();
  assert.deepEqual(await popupPage.evaluate(() => globalThis.__openedExtensionTabs), [
    "options/options.html?tab=account-panel"
  ]);
  await popupPage.locator('[data-module-toggle="captcha"]').click();
  await popupPage.evaluate(() => {
    document.querySelector("#popup-captcha-source").value = "#captchaText";
    document.querySelector("#popup-captcha-target").value = "#captchaAnswer";
  });
  assert.equal(await popupPage.locator("#popup-captcha-delay").count(), 0);
  assert.equal(await popupPage.locator("#popup-captcha-human-typing").count(), 0);
  await popupPage.locator("#configure-captcha").click();
  await popupPage.waitForFunction(() => /Route saved/i.test(document.querySelector("#alert")?.textContent || ""));
  const popupCaptchaRoute = await popupPage.evaluate(() => (
    globalThis.__runtimeMessages
      .filter((message) => message.type === "SET_EXTENSION_STORAGE")
      .map((message) => message.values?.fp_captcha_selectors?.["example.com"])
      .find(Boolean)
  ));
  assert.equal(Object.hasOwn(popupCaptchaRoute, "fillDelayMs"), false);
  assert.equal(Object.hasOwn(popupCaptchaRoute, "humanTyping"), false);
  const popupSavedRoute = Object.values(popupCaptchaRoute.routes)[0];
  assert.equal(popupSavedRoute.profileId, "default");
  assert.deepEqual(popupSavedRoute.profileIds, ["default"]);
  assert.equal(await popupPage.locator("#power-toggle").getAttribute("aria-pressed"), "true");
  await popupPage.locator("#power-toggle").click();
  await popupPage.waitForFunction(() => document.getElementById("power-toggle")?.getAttribute("aria-pressed") === "false");
  assert.equal(await popupPage.locator("#captcha-status").innerText(), "Extension off");
  assert.equal(await popupPage.locator("#simple-solve-captcha-btn").isDisabled(), true);

  const unauthPopupPage = await browser.newPage();
  await installChromeMock(unauthPopupPage, "unauthenticated");
  await unauthPopupPage.goto(`${baseUrl}/popup/popup.html`);
  await unauthPopupPage.waitForSelector("#app-view.active");
  await captureSnapshot(unauthPopupPage, "popup-login");
  assert.equal(await unauthPopupPage.locator("#account-link-copy").innerText(), "Sign in or create account");
  await unauthPopupPage.locator("#account-link").click();
  await unauthPopupPage.waitForSelector("#popup-auth-panel:not([hidden])");
  assert.equal(await unauthPopupPage.locator("#advanced-app-controls").isHidden(), true);
  assert.equal(await unauthPopupPage.locator("#credit-progress-container").isHidden(), true);
  assert.equal(await unauthPopupPage.locator(".auth-step").count(), 0);
  assert.equal(await unauthPopupPage.evaluate(() => {
    const codeInput = document.querySelector("#popup-auth-otp");
    const verifyButton = document.querySelector("#popup-verify-otp");
    return !!(codeInput.compareDocumentPosition(verifyButton) & Node.DOCUMENT_POSITION_FOLLOWING);
  }), true);
  assert.deepEqual(await unauthPopupPage.evaluate(() => globalThis.__openedExtensionTabs), []);
  await unauthPopupPage.locator("#popup-auth-email").fill("user@mailinator.com");
  await unauthPopupPage.locator("#popup-send-otp").click();
  await unauthPopupPage.waitForFunction(() => /Temporary email/i.test(document.querySelector("#popup-auth-message")?.textContent || ""));
  assert.equal(await unauthPopupPage.evaluate(() => globalThis.__runtimeMessages.some((message) => message.type === "REGISTER_ACCOUNT")), false);
  await unauthPopupPage.locator("#popup-auth-email").fill("user@gmail.com");
  await unauthPopupPage.locator("#popup-send-otp").click();
  await unauthPopupPage.waitForFunction(() => /Code sent/i.test(document.querySelector("#popup-auth-message")?.textContent || ""));
  assert.equal(await unauthPopupPage.locator("#popup-verify-otp").isDisabled(), false);
  await unauthPopupPage.locator("#popup-auth-otp").fill("123456");
  await unauthPopupPage.locator("#popup-verify-otp").click();
  await unauthPopupPage.waitForFunction(() => document.querySelector("#account-link-copy")?.textContent === "Manage account and sync");
  assert.equal(await unauthPopupPage.evaluate(() => globalThis.__runtimeMessages.some((message) => message.type === "VERIFY_OTP")), true);
  assert.deepEqual(await unauthPopupPage.evaluate(() => globalThis.__openedExtensionTabs), []);

  const unavailablePage = await browser.newPage();
  await installChromeMock(unavailablePage, "unavailable");
  await unavailablePage.goto(`${baseUrl}/popup/popup.html`);
  await unavailablePage.waitForSelector("#unavailable-view.active");
  assert.equal(await unavailablePage.locator("#account-summary").count(), 0);

  console.log("EAZ-UI-001 focused UI smoke passed");
} finally {
  await browser.close();
  server.close();
}
