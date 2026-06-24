const fs = require("fs");
const http = require("http");
const os = require("os");
const path = require("path");
let chromium;
try {
  ({ chromium } = require("playwright"));
} catch (_) {
  ({ chromium } = require("playwright-core"));
}

const repoRoot = path.resolve(__dirname, "..");
const extensionPath = path.join(repoRoot, "extension");
const apiBaseUrl = process.env.EAZYFILL_QA_API_BASE || "http://127.0.0.1:8080";

function assertState(condition, message) {
  if (!condition) throw new Error(message);
}

function chromeExecutable() {
  if (process.env.EAZYFILL_QA_SYSTEM_CHROME !== "1") {
    const bundled = chromium.executablePath();
    if (bundled && fs.existsSync(bundled)) return bundled;
    const msPlaywrightRoot = path.join(os.homedir(), "AppData", "Local", "ms-playwright");
    if (fs.existsSync(msPlaywrightRoot)) {
      const installed = fs.readdirSync(msPlaywrightRoot)
        .filter((name) => /^chromium-\d+$/.test(name))
        .sort()
        .reverse()
        .map((name) => path.join(msPlaywrightRoot, name, "chrome-win64", "chrome.exe"))
        .find((candidate) => fs.existsSync(candidate));
      if (installed) return installed;
    }
  }
  const candidates = [
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe"
  ];
  const found = candidates.find((candidate) => fs.existsSync(candidate));
  if (!found) throw new Error("Chrome or Edge executable not found");
  return found;
}

function startFixtureServer() {
  const userscript = `// ==UserScript==
// @name         EazyFill QA Script
// @namespace    eazyfill.qa
// @version      1.0.0
// @match        __BASE__/*
// @grant        GM_getValue
// @grant        GM_setValue
// @grant        GM_xmlhttpRequest
// @grant        GM_addStyle
// @connect      127.0.0.1
// ==/UserScript==

GM_addStyle("#gm-style-target { outline: 3px solid rgb(41, 182, 168); }");
document.body.dataset.userscriptRan = "yes";
GM_setValue("qaKey", "qaValue")
  .then(() => GM_getValue("qaKey"))
  .then((value) => { document.body.dataset.gmValue = value; });
GM_xmlhttpRequest({ method: "GET", url: "__BASE__/gm-data" })
  .then((response) => { document.body.dataset.gmXhr = response.response.responseText; });
`;

  const server = http.createServer((request, response) => {
    if (request.url === "/gm-data") {
      response.writeHead(200, { "Content-Type": "text/plain" });
      response.end("gm-ok");
      return;
    }
    if (request.url === "/script.user.js") {
      const base = `http://127.0.0.1:${server.address().port}`;
      response.writeHead(200, { "Content-Type": "text/javascript" });
      response.end(userscript.replaceAll("__BASE__", base));
      return;
    }
    response.writeHead(200, { "Content-Type": "text/html" });
    response.end(`<!doctype html>
<html>
  <head><title>EazyFill QA Fixture</title></head>
  <body>
    <main>
      <h1>EazyFill QA Fixture</h1>
      <label>Name <input id="name" autocomplete="off"></label>
      <label>Email <input id="email" autocomplete="off"></label>
      <div id="captchaText">AB12</div>
      <label>Captcha <input id="captchaAnswer" autocomplete="off"></label>
      <div id="gm-style-target">GM style target</div>
    </main>
  </body>
</html>`);
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve(server));
  });
}

async function extensionMessage(page, message) {
  return await page.evaluate((payload) => new Promise((resolve) => {
    chrome.runtime.sendMessage(payload, (response) => resolve(response || { ok: false, error: "No response" }));
  }), message);
}

async function main() {
  assertState(fs.existsSync(path.join(extensionPath, "manifest.json")), "extension/manifest.json missing");
  const fixture = await startFixtureServer();
  const fixtureBase = `http://127.0.0.1:${fixture.address().port}`;
  const userDataDir = fs.mkdtempSync(path.join(os.tmpdir(), "eazyfill-qa-chrome-"));
  const chromeExtensionPath = extensionPath.replace(/\\/g, "/");
  const browser = await chromium.launchPersistentContext(userDataDir, {
    executablePath: chromeExecutable(),
    headless: false,
    ignoreDefaultArgs: ["--disable-extensions", "--disable-component-extensions-with-background-pages"],
    args: [
      "--disable-component-extensions-with-background-pages",
      "--disable-features=DisableLoadExtensionCommandLineSwitch,BlockInsecurePrivateNetworkRequests,PrivateNetworkAccessSendPreflights,PrivateNetworkAccessRespectPreflightResults",
      `--unsafely-treat-insecure-origin-as-secure=${apiBaseUrl}`,
      `--disable-extensions-except=${chromeExtensionPath}`,
      `--load-extension=${chromeExtensionPath}`,
      "--no-first-run",
      "--no-default-browser-check",
      "--disable-popup-blocking"
    ]
  });

  try {
    let serviceWorker = browser.serviceWorkers().find((worker) => worker.url().endsWith("/background/service-worker.js"));
    const serviceWorkerStarted = Date.now();
    while (!serviceWorker && Date.now() - serviceWorkerStarted < 15000) {
      serviceWorker = browser.serviceWorkers().find((worker) => worker.url().endsWith("/background/service-worker.js"));
      if (serviceWorker) break;
      const remaining = 15000 - (Date.now() - serviceWorkerStarted);
      const nextWorker = await browser.waitForEvent("serviceworker", { timeout: Math.min(1000, remaining) }).catch(() => null);
      if (nextWorker?.url().endsWith("/background/service-worker.js")) serviceWorker = nextWorker;
    }
    assertState(serviceWorker, `EazyFill service worker did not load. Workers: ${browser.serviceWorkers().map((worker) => worker.url()).join(", ")}`);
    const extensionId = new URL(serviceWorker.url()).host;
    assertState(extensionId, "Could not determine extension id");
    const extensionUrl = (filePath) => `chrome-extension://${extensionId}/${filePath}`;

    const extensionPage = await browser.newPage();
    await extensionPage.goto(extensionUrl("options/options.html"));
    const settingsResponse = await extensionMessage(extensionPage, {
      type: "SET_EXTENSION_STORAGE",
      values: {
        fp_settings: {
          captchaEnabled: true,
          autofillEnabled: true,
          userscriptsEnabled: true,
          syncEnabled: true,
          theme: "dark",
          apiBaseUrl
        }
      }
    });
    assertState(settingsResponse.ok, `Failed to seed extension settings: ${settingsResponse.error || JSON.stringify(settingsResponse)}`);
    const seededSettings = await extensionMessage(extensionPage, { type: "GET_EXTENSION_STORAGE", keys: ["fp_settings"] });
    assertState(
      seededSettings.data?.fp_settings?.apiBaseUrl === apiBaseUrl,
      `Seeded API base was not persisted: ${JSON.stringify(seededSettings)}`
    );

    await extensionPage.goto(extensionUrl("options/options.html?tab=account-panel"));
    await extensionPage.waitForSelector("#account-panel.active", { timeout: 10000 });
    const welcomeSettings = await extensionMessage(extensionPage, { type: "GET_EXTENSION_STORAGE", keys: ["fp_settings"] });
    assertState(
      welcomeSettings.data?.fp_settings?.apiBaseUrl === apiBaseUrl,
      `Options account flow overwrote API base: ${JSON.stringify(welcomeSettings)}`
    );
    await extensionPage.fill("#options-signup-identifier", `eazyfill.qa+${Date.now()}@gmail.com`);
    await extensionPage.click("#options-send-otp-btn");
    await extensionPage.waitForFunction(() => {
      const message = document.querySelector("#options-signup-message")?.textContent || "";
      const className = document.querySelector("#options-signup-message")?.className || "";
      const needsName = !document.querySelector("#options-signup-name-row")?.hidden;
      return needsName || className.includes("is-success") || className.includes("is-error") || /failed|could not|unable|error/i.test(message);
    }, null, { timeout: 20000 });
    const otpState = await extensionPage.evaluate(() => ({
      message: document.querySelector("#options-signup-message")?.textContent || "",
      className: document.querySelector("#options-signup-message")?.className || "",
      sendDisabled: document.querySelector("#options-send-otp-btn")?.disabled || false
    }));
    if (!otpState.className.includes("is-success")) {
      const nameVisible = await extensionPage.locator("#options-signup-name-row").isVisible();
      assertState(nameVisible, `Email-first account lookup failed or stalled: ${JSON.stringify(otpState)}`);
      await extensionPage.fill("#options-signup-name", "EazyFill QA");
      await extensionPage.click("#options-send-otp-btn");
      await extensionPage.waitForFunction(() => {
        const message = document.querySelector("#options-signup-message")?.textContent || "";
        const className = document.querySelector("#options-signup-message")?.className || "";
        return className.includes("is-success") || /failed|could not|unable|error/i.test(message);
      }, null, { timeout: 20000 });
    }
    const finalOtpState = await extensionPage.evaluate(() => ({
      message: document.querySelector("#options-signup-message")?.textContent || "",
      className: document.querySelector("#options-signup-message")?.className || ""
    }));
    assertState(finalOtpState.className.includes("is-success"), `OTP request failed or stalled: ${JSON.stringify(finalOtpState)}`);
    const otpText = await extensionPage.locator("#options-signup-message").innerText();
    const otp = otpText.match(/Code:\s*(\d+)/)?.[1];
    assertState(otp, `OTP not shown in debug response: ${otpText}`);
    await extensionPage.fill("#options-signup-otp", otp);
    await extensionPage.click("#options-verify-otp-btn");
    await extensionPage.waitForFunction(() => {
      const signup = document.querySelector("#options-signup-message")?.textContent || "";
      const connected = !document.querySelector("#account-connected-view")?.classList.contains("is-hidden");
      return connected || signup.includes("Account verified and connected!") || /failed|error|invalid|expired|not allowed/i.test(signup);
    }, null, { timeout: 20000 });
    const verifyState = await extensionPage.evaluate(() => ({
      signup: document.querySelector("#options-signup-message")?.textContent || "",
      signupClass: document.querySelector("#options-signup-message")?.className || "",
      connected: !document.querySelector("#account-connected-view")?.classList.contains("is-hidden")
    }));
    assertState(
      verifyState.connected || verifyState.signup.includes("Account verified and connected!"),
      `OTP verify did not connect: ${JSON.stringify(verifyState)}`
    );

    const authResponse = await extensionMessage(extensionPage, { type: "GET_EXTENSION_STORAGE", keys: ["fp_auth"] });
    const sessionToken = authResponse.data?.fp_auth?.sessionToken;
    assertState(sessionToken && sessionToken.startsWith("efs_"), "Options OTP signup did not store an EazyFill session");
    assertState(!authResponse.data?.fp_auth?.apiKey, "Options OTP signup must not store a user-facing API key");

    await extensionPage.goto(extensionUrl("options/options.html"));
    const seedResponse = await extensionMessage(extensionPage, {
      type: "SET_EXTENSION_STORAGE",
      values: {
        fp_profiles: [{
          id: "default",
          name: "Default QA",
          values: { fullName: "Ada Lovelace" }
        }],
        fp_rules: [{
          id: "qa-name",
          name: "QA Name",
          domain: "127.0.0.1",
          site: { matchMode: "domain", pattern: "127.0.0.1" },
          profileId: "default",
          enabled: true,
          steps: [{
            order: 1,
            label: "Name",
            action: "set_value",
            selector: { primary: "#name" },
            value: "{@fullName}",
            required: true
          }]
        }]
      }
    });
    assertState(seedResponse.ok, `Failed to seed profiles/rules: ${seedResponse.error || JSON.stringify(seedResponse)}`);
    await extensionPage.reload();
    await extensionPage.click('[data-panel="profiles-panel"]');
    await extensionPage.waitForFunction(() => document.querySelector("#profiles-table")?.textContent.includes("Default QA"), null, { timeout: 10000 });
    await extensionPage.click('[data-panel="rules-panel"]');
    await extensionPage.waitForFunction(() => document.querySelector("#rules-panel")?.textContent.includes("QA Name"), null, { timeout: 10000 });
    const visibleRulesText = await extensionPage.textContent("#rules-panel");
    assertState(/QA Name|127\.0\.0\.1/.test(visibleRulesText || ""), "Autofill rule metadata was not visible in the options UI");
    assertState(!/Ada Lovelace/.test(visibleRulesText || ""), "Autofill rule value leaked in the options UI");

    await extensionPage.click('[data-panel="scripts-panel"]');
    await extensionPage.fill("#script-import-url-input", `${fixtureBase}/script.user.js`);
    await extensionPage.click("#script-import-direct-btn");
    await extensionPage.waitForFunction(() => document.querySelector("#scripts-table")?.textContent.includes("EazyFill QA Script"), null, { timeout: 15000 });
    const visibleScriptsText = await extensionPage.textContent("#scripts-panel");
    assertState(/EazyFill QA Script|script\.user\.js/.test(visibleScriptsText || ""), "Userscript metadata was not visible in the options UI");
    assertState(!/document\.body\.dataset|gm-ok|responseText/.test(visibleScriptsText || ""), "Userscript code leaked in the options UI");

    await extensionPage.click('[data-panel="captcha-panel"]');
    await extensionPage.fill("#captcha-domain", "127.0.0.1");
    await extensionPage.fill("#captcha-source-selector", "#captchaText");
    await extensionPage.fill("#captcha-target-selector", "#captchaAnswer");
    await extensionPage.fill("#captcha-fill-delay", "250");
    await extensionPage.evaluate(() => {
      const input = document.querySelector("#captcha-human-typing");
      input.checked = true;
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
    await extensionPage.click("#captcha-save-behavior-btn");
    await extensionPage.waitForFunction(() => /CAPTCHA behavior saved/i.test(document.querySelector("#toast")?.textContent || ""), null, { timeout: 10000 });
    const captchaSettingsStorage = await extensionMessage(extensionPage, {
      type: "GET_EXTENSION_STORAGE",
      keys: ["fp_settings"]
    });
    const savedCaptchaSettings = captchaSettingsStorage.data?.fp_settings || {};
    assertState(savedCaptchaSettings.captchaFillDelayMs === 250, `Global CAPTCHA fill delay was not saved: ${JSON.stringify(savedCaptchaSettings)}`);
    assertState(savedCaptchaSettings.captchaHumanTyping === true, `Global CAPTCHA human typing was not saved: ${JSON.stringify(savedCaptchaSettings)}`);

    await extensionPage.click("#captcha-save-config-btn");
    await extensionPage.waitForFunction(() => /CAPTCHA config saved/i.test(document.querySelector("#toast")?.textContent || ""), null, { timeout: 10000 });
    const captchaStorage = await extensionMessage(extensionPage, {
      type: "GET_EXTENSION_STORAGE",
      keys: ["fp_captcha_selectors"]
    });
    const savedCaptchaConfig = captchaStorage.data?.fp_captcha_selectors?.["127.0.0.1"];
    const savedCaptchaRoute = savedCaptchaConfig?.routes?.[savedCaptchaConfig.activeFieldName]
      || Object.values(savedCaptchaConfig?.routes || {})[0];
    assertState(savedCaptchaRoute?.sourceSelector === "#captchaText", `CAPTCHA source selector was not saved: ${JSON.stringify(savedCaptchaRoute)}`);
    assertState(!Object.hasOwn(savedCaptchaRoute || {}, "fillDelayMs"), `CAPTCHA route should not store the global fill delay: ${JSON.stringify(savedCaptchaRoute)}`);
    assertState(!Object.hasOwn(savedCaptchaRoute || {}, "humanTyping"), `CAPTCHA route should not store the global typing mode: ${JSON.stringify(savedCaptchaRoute)}`);

    const target = await browser.newPage();
    await target.goto(`${fixtureBase}/qa`);
    await target.bringToFront();
    await target.waitForLoadState("domcontentloaded");
    await target.waitForTimeout(500);

    await target.waitForFunction(
      () => document.querySelector("#name")?.value === "Ada Lovelace",
      null,
      { timeout: 8000 }
    );

    const recorderStart = await extensionMessage(extensionPage, { type: "START_RECORDING" });
    assertState(recorderStart.ok, `Autofill recorder failed to start: ${recorderStart.error || JSON.stringify(recorderStart)}`);
    await target.fill("#email", "recorded@example.com");
    await target.waitForSelector('#eazyfill-recorder-panel [data-action="save"]', { timeout: 8000 });
    await target.fill('#eazyfill-recorder-panel [data-role="name"]', "QA Recorded Rule");
    await target.click('#eazyfill-recorder-panel [data-action="save"]');
    let recordedRules = {};
    for (let i = 0; i < 20; i += 1) {
      recordedRules = await extensionMessage(extensionPage, { type: "GET_EXTENSION_STORAGE", keys: ["fp_rules"] });
      if (recordedRules.data?.fp_rules?.some((rule) => rule.name === "QA Recorded Rule")) break;
      await target.waitForTimeout(250);
    }
    const recordedRule = recordedRules.data?.fp_rules?.find((rule) => rule.name === "QA Recorded Rule");
    assertState(
      recordedRule?.steps?.some((step) => step.selector?.primary === "#email" && step.value === "recorded@example.com"),
      `Autofill recorder did not save the captured email field: ${JSON.stringify(recordedRule)}`
    );

    const pickResult = await extensionMessage(extensionPage, { type: "PICK_ELEMENT_CURRENT", targetField: "captcha-source" });
    assertState(pickResult.ok, `Selector picker failed to start: ${pickResult.error || JSON.stringify(pickResult)}`);
    await target.click("#captchaText");
    let pickStorage = {};
    for (let i = 0; i < 20; i += 1) {
      pickStorage = await extensionMessage(extensionPage, { type: "GET_EXTENSION_STORAGE", keys: ["fp_last_selector_pick"] });
      if (pickStorage.data?.fp_last_selector_pick?.selector?.primary) break;
      await target.waitForTimeout(250);
    }
    assertState(pickStorage.data?.fp_last_selector_pick?.selector?.primary, "Selector picker did not store a selected selector");

    const userscriptStatus = await extensionMessage(extensionPage, { type: "USERSCRIPTS_STATUS" });
    const userscriptChecks = [];
    if (userscriptStatus.available) {
      const registerResult = await extensionMessage(extensionPage, { type: "USERSCRIPTS_REGISTER" });
      assertState(registerResult.ok, `Userscript registration failed: ${registerResult.error || JSON.stringify(registerResult)}`);
      await target.reload();
      await target.waitForFunction(() => document.body?.dataset.userscriptRan === "yes", null, { timeout: 15000 });
      await target.waitForFunction(() => document.body?.dataset.gmValue === "qaValue", null, { timeout: 15000 });
      await target.waitForFunction(() => document.body?.dataset.gmXhr === "gm-ok", null, { timeout: 15000 });
      userscriptChecks.push("script URL import and chrome.userScripts registration");
      userscriptChecks.push("GM_getValue/GM_setValue/GM_xmlhttpRequest/GM_addStyle execution");
    } else {
      const statusText = await extensionPage.locator("#script-runtime-status").innerText().catch(() => "");
      assertState(/Allow User Scripts|userScripts|Developer mode/i.test(statusText), `Userscript setup guidance missing: ${statusText}`);
      userscriptChecks.push(`script URL import saved; chrome.userScripts gated by browser toggle (${userscriptStatus.error || "enable user scripts"})`);
    }

    await extensionPage.click('[data-panel="sync-panel"]');
    await extensionPage.click("#sync-push-btn");
    await extensionPage.waitForFunction(() => /sync|pushed|saved|complete|failed|connect/i.test(document.querySelector("#toast")?.textContent || ""), null, { timeout: 15000 });
    await extensionPage.click("#sync-pull-btn");
    await extensionPage.waitForFunction(() => /sync|pulled|restored|complete|failed|connect/i.test(document.querySelector("#toast")?.textContent || ""), null, { timeout: 15000 });

    await extensionPage.click('[data-panel="account-panel"]');
    await extensionPage.click("#billing-refresh-btn");
    await extensionPage.waitForSelector("#plans-grid", { timeout: 10000 });

    const output = {
      ok: true,
      extensionId,
      fixtureBase,
      checks: [
        "extension service worker loaded",
        "options account OTP signup against local backend",
        "options profile and rule dashboard render",
        "autofill playback with profile variable",
        "autofill recorder capture and save",
        ...userscriptChecks,
        "CAPTCHA selector save with global fill delay and human typing settings",
        "selector picker storage path",
        "encrypted sync push/pull",
        "billing plans refresh"
      ]
    };
    console.log(JSON.stringify(output, null, 2));
  } finally {
    await browser.close();
    fixture.close();
    if (process.env.EAZYFILL_QA_KEEP_PROFILE === "1") {
      console.error(`Kept Chrome QA profile: ${userDataDir}`);
    } else {
      fs.rmSync(userDataDir, { recursive: true, force: true });
    }
  }
}

main().catch((error) => {
  console.error(error.stack || error.message || String(error));
  process.exit(1);
});
