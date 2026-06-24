import assert from "node:assert/strict";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const extensionRoot = path.join(repoRoot, "extension");

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

function startServer() {
  const server = http.createServer((_request, response) => {
    response.writeHead(200, { "Content-Type": "text/html" });
    response.end(`<!doctype html>
      <html>
        <body>
          <label>Name <input id="name" name="name"></label>
          <label>Legacy <input id="legacy" name="legacy"></label>
          <canvas id="captchaText" width="120" height="42"></canvas>
          <label>CAPTCHA <input id="captchaAnswer"></label>
          <script>
            const canvas = document.querySelector("#captchaText");
            const context = canvas.getContext("2d");
            context.fillStyle = "#ffffff";
            context.fillRect(0, 0, canvas.width, canvas.height);
            context.fillStyle = "#111827";
            context.font = "24px sans-serif";
            context.fillText("AB12", 24, 28);
          </script>
        </body>
      </html>`);
  });
  return new Promise((resolve) => {
    server.listen(0, "127.0.0.1", () => resolve(server));
  });
}

async function addContentScript(page, relativePath) {
  await page.addScriptTag({ path: path.join(extensionRoot, relativePath) });
}

const server = await startServer();
const baseUrl = `http://127.0.0.1:${server.address().port}`;
const browser = await chromium.launch({ executablePath: chromeExecutable(), headless: true });

try {
  const page = await browser.newPage();
  await page.addInitScript(() => {
    const listeners = [];
    const sentMessages = [];
    const route = {
      id: "127.0.0.1",
      domain: "127.0.0.1",
      sourceSelector: "#captchaText",
      targetSelector: "#captchaAnswer",
      taskType: "text",
      autoSolve: false
    };

    function responseFor(message) {
      if (message.type === "GET_EXTENSION_STORAGE") {
        const host = location.hostname;
        return {
          ok: true,
          data: {
            fp_settings: {
              extensionEnabled: true,
              captchaEnabled: true,
              autofillEnabled: true,
              activeProfileId: "default",
              captchaFillDelayMs: 120,
              captchaHumanTyping: true
            },
            fp_captcha_selectors: { "127.0.0.1": route },
            fp_profiles: [{ id: "default", name: "Global", values: {} }],
            fp_rules: [{
              id: "rule-name",
              name: "Fill test name",
              enabled: true,
              site: { matchMode: "domainPath", pattern: `${host}/`, path: "/" },
              ruleType: "instant",
              profileId: "default",
              profileIds: ["default"],
              execution: { mode: "instant", delayMs: 0, waitTimeoutMs: 1000, runOnce: true },
              steps: [{
                order: 1,
                action: "set_value",
                selector: "#name",
                value: "Grace Hopper",
                required: true
              }]
            }, {
              id: "rule-legacy-action",
              name: "Fill legacy action",
              enabled: true,
              site: { matchMode: "domainPath", pattern: `${host}/`, path: "/" },
              ruleType: "instant",
              profileId: "default",
              profileIds: ["default"],
              execution: { mode: "instant", delayMs: 0, waitTimeoutMs: 1000, runOnce: true },
              actions: [{
                order: 1,
                type: "fill",
                target_selector: "#legacy",
                default_value: "Legacy Value",
                required: true
              }]
            }]
          }
        };
      }
      if (message.type === "GET_RUNTIME_PLAN_LIMITS") {
        return {
          ok: true,
          authenticated: true,
          features: { autofill: true, userscripts: true },
          limits: { rules: 20, scripts: 10 }
        };
      }
      if (message.type === "CAPTCHA_SOLVE_REQUEST") {
        return { ok: true, result: "AB12" };
      }
      if (message.type === "RECORDER_SAVE_RULE") {
        return { ok: true, rule: message.rule };
      }
      return { ok: true };
    }

    globalThis.__sentMessages = sentMessages;
    globalThis.__dispatchRuntimeMessage = (message) => new Promise((resolve) => {
      for (const listener of listeners) {
        let responded = false;
        const keepPort = listener(message, {}, (response) => {
          responded = true;
          resolve(response);
        });
        if (responded || keepPort === true) return;
      }
      resolve({ ok: false, error: `Unhandled content message: ${message.type}` });
    });

    globalThis.chrome = {
      runtime: {
        lastError: null,
        onMessage: {
          addListener(listener) {
            listeners.push(listener);
          }
        },
        sendMessage(message, callback) {
          sentMessages.push(message);
          const response = responseFor(message);
          if (callback) callback(response);
          return Promise.resolve(response);
        }
      }
    };
  });

  await page.goto(baseUrl);
  await addContentScript(page, "lib/selector-builder.js");
  await addContentScript(page, "content/excluded-hosts.js");
  await addContentScript(page, "content/captcha-filler.js");
  await addContentScript(page, "content/captcha-detector.js");
  await addContentScript(page, "content/autofill-engine.js");
  await addContentScript(page, "content/selector-overlay.js");
  await addContentScript(page, "content/recorder-panel.js");
  await addContentScript(page, "content/recorder-engine.js");

  await page.waitForFunction(() => (
    document.querySelector("#name")?.value === "Grace Hopper"
    && document.querySelector("#legacy")?.value === "Legacy Value"
  ));
  await page.waitForFunction(() => globalThis.__sentMessages.some((message) => (
    message.type === "AUTOFILL_AUTO_EXECUTED"
    && message.succeededSteps === 2
  )));

  await page.evaluate(() => {
    globalThis.__captchaInputEvents = [];
    const target = document.querySelector("#captchaAnswer");
    target.addEventListener("input", () => {
      globalThis.__captchaInputEvents.push({ value: target.value, at: performance.now() });
    });
  });

  const solveStarted = Date.now();
  const solveResult = await page.evaluate(() => globalThis.__dispatchRuntimeMessage({ type: "CAPTCHA_SOLVE_NOW" }));
  const solveElapsed = Date.now() - solveStarted;
  assert.equal(solveResult.ok, true);
  assert.equal(solveResult.filled.ok, true);
  assert.equal(solveResult.filled.humanTyping, true);
  assert.equal(solveResult.filled.fillDelayMs, 120);
  assert.ok(solveElapsed >= 100, `CAPTCHA fill delay was too short: ${solveElapsed} ms`);
  assert.equal(await page.locator("#captchaAnswer").inputValue(), "AB12");
  const inputEvents = await page.evaluate(() => globalThis.__captchaInputEvents);
  assert.ok(inputEvents.length >= 5, `Expected clear plus typed input events, received ${inputEvents.length}`);
  assert.deepEqual(inputEvents.slice(-4).map((event) => event.value), ["A", "AB", "AB1", "AB12"]);

  await page.locator("#name").fill("");
  await page.locator("#legacy").fill("");
  const runOnceResult = await page.evaluate(() => globalThis.__dispatchRuntimeMessage({ type: "AUTOFILL_EXECUTE_NOW" }));
  assert.equal(runOnceResult.ok, true);
  assert.equal(await page.locator("#name").inputValue(), "");
  assert.equal(await page.locator("#legacy").inputValue(), "");

  const autofillResult = await page.evaluate(() => globalThis.__dispatchRuntimeMessage({
    type: "AUTOFILL_EXECUTE_NOW",
    force: true
  }));
  assert.equal(autofillResult.ok, true);
  assert.equal(autofillResult.matchedRules, 2);
  assert.equal(autofillResult.executedRules, 2);
  assert.equal(autofillResult.succeededSteps, 2);
  assert.equal(await page.locator("#name").inputValue(), "Grace Hopper");
  assert.equal(await page.locator("#legacy").inputValue(), "Legacy Value");

  const recorderStart = await page.evaluate(() => globalThis.__dispatchRuntimeMessage({ type: "START_RECORDING" }));
  assert.equal(recorderStart.ok, true);
  await page.locator("#name").fill("Ada Lovelace");
  await page.locator('#eazyfill-recorder-panel [data-action="save"]').click();
  await page.waitForFunction(() => globalThis.__sentMessages.some((message) => message.type === "RECORDER_SAVE_RULE"));
  const recordedRule = await page.evaluate(() => (
    globalThis.__sentMessages.find((message) => message.type === "RECORDER_SAVE_RULE")?.rule
  ));
  assert.equal(recordedRule.profileId, "default");
  assert.equal(recordedRule.site.matchMode, "domainPath");
  assert.equal(recordedRule.site.pattern, "127.0.0.1/");
  assert.ok(recordedRule.steps.some((step) => step.selector?.primary === "#name" && step.value === "Ada Lovelace"));

  const pickerStart = await page.evaluate(() => globalThis.__dispatchRuntimeMessage({
    type: "PICK_ELEMENT",
    targetField: "captcha-source"
  }));
  assert.equal(pickerStart.ok, true);
  await page.locator("#captchaText").hover();
  await page.locator("#captchaText").click();
  await page.waitForFunction(() => globalThis.__sentMessages.some((message) => message.type === "SELECTOR_PICKED"));
  const picked = await page.evaluate(() => (
    globalThis.__sentMessages.find((message) => message.type === "SELECTOR_PICKED")
  ));
  assert.equal(picked.targetField, "captcha-source");
  assert.equal(picked.selector.primary, "#captchaText");

  console.log("EAZ content workflows passed: CAPTCHA delay/typing, autofill, recorder, and selector picker");
} finally {
  await browser.close();
  server.close();
}
