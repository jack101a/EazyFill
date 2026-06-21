import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

const localStore = new Map();
const sessionStore = new Map();
let registeredScripts = [];
let worldConfiguration = null;
let userScriptListener = null;

function storageArea(store) {
  return {
    async get(keys) {
      if (keys === null) return Object.fromEntries(store);
      const requested = Array.isArray(keys) ? keys : [keys];
      return Object.fromEntries(requested.filter((key) => store.has(key)).map((key) => [key, store.get(key)]));
    },
    async set(values) {
      for (const [key, value] of Object.entries(values || {})) store.set(key, value);
    },
    async remove(keys) {
      for (const key of Array.isArray(keys) ? keys : [keys]) store.delete(key);
    }
  };
}

globalThis.chrome = {
  runtime: {
    id: "eazyfill-test-extension",
    lastError: null,
    onUserScriptMessage: {
      addListener(listener) {
        userScriptListener = listener;
      }
    }
  },
  storage: {
    local: storageArea(localStore),
    session: storageArea(sessionStore),
    onChanged: { addListener() {} }
  },
  userScripts: {
    async configureWorld(configuration) {
      worldConfiguration = configuration;
    },
    async getScripts(filter) {
      return filter?.ids
        ? registeredScripts.filter((script) => filter.ids.includes(script.id))
        : registeredScripts;
    },
    async unregister({ ids } = {}) {
      registeredScripts = ids
        ? registeredScripts.filter((script) => !ids.includes(script.id))
        : [];
    },
    async register(scripts) {
      registeredScripts.push(...scripts);
    }
  },
  tabs: {
    query(_query, callback) {
      callback([]);
    },
    sendMessage() {},
    create(_details, callback) {
      callback({ id: 1 });
    }
  },
  notifications: { create() {} },
  downloads: {
    download(_details, callback) {
      callback(1);
    }
  }
};

const root = path.resolve(import.meta.dirname, "..");
const protectedStorageUrl = pathToFileURL(path.join(root, "extension/background/protected-storage.js"));
const managerUrl = pathToFileURL(path.join(root, "extension/background/userscript-manager.js"));
const protectedStorage = await import(protectedStorageUrl);
const manager = await import(managerUrl);

const rawCode = `// ==UserScript==
// @name Security test
// @match https://example.com/*
// @include https://example.com/app/*
// @exclude https://example.com/private/*
// @grant GM_xmlhttpRequest
// ==/UserScript==
GM_log("loaded");`;
const script = await manager.normalizeUserscript(rawCode, { id: "security-test", enabled: true });

await chrome.storage.local.set({ fp_settings: { userscriptsEnabled: true } });
await protectedStorage.setProtectedValues({ fp_scripts: [script] });

const registrationResult = await manager.registerStoredUserscripts();
assert.equal(registrationResult.count, 1);
assert.deepEqual(worldConfiguration, { messaging: true });
assert.equal(typeof userScriptListener, "function");

const registration = registeredScripts[0];
assert.equal(registration.id, "eazyfill:security-test");
assert.ok(registration.includeGlobs.includes("https://example.com/app/*"));
assert.ok(registration.excludeGlobs.includes("*://*netbanking*/*"));
assert.ok(registration.excludeMatches.includes("*://paypal.com/*"));
assert.doesNotMatch(registration.js[0].code, /window\.postMessage/);
assert.match(registration.js[0].code, /chrome\.runtime\.sendMessage/);

const bootstrapMatch = registration.js[0].code.match(/const __bootstrapCapability = "([a-f0-9]+)"/);
assert.ok(bootstrapMatch);
const bootstrapCapability = bootstrapMatch[1];
const sender = {
  id: chrome.runtime.id,
  documentId: "document-1",
  frameId: 0,
  url: "https://example.com/app/page",
  tab: { id: 11, url: "https://example.com/app/page" }
};

const wrongBootstrap = await manager.handleGMCall({
  action: "bridgeInit",
  requestId: "init-wrong",
  scriptId: script.id,
  bootstrapCapability: "wrong"
}, sender);
assert.equal(wrongBootstrap.code, "INVALID_CAPABILITY");

const initialized = await manager.handleGMCall({
  action: "bridgeInit",
  requestId: "init-ok",
  scriptId: script.id,
  bootstrapCapability
}, sender);
assert.equal(initialized.ok, true);
assert.match(initialized.capability, /^[a-f0-9]{64}$/);

const unsupported = await manager.handleGMCall({
  action: "launchMissiles",
  requestId: "unsupported",
  scriptId: script.id,
  capability: initialized.capability
}, sender);
assert.equal(unsupported.code, "INVALID_REQUEST");

const missingKey = await manager.handleGMCall({
  action: "getValue",
  requestId: "missing-key",
  scriptId: script.id,
  capability: initialized.capability
}, sender);
assert.equal(missingKey.code, "INVALID_REQUEST");

const deniedConnect = await manager.handleGMCall({
  action: "xmlhttpRequest",
  requestId: "xhr",
  scriptId: script.id,
  capability: initialized.capability,
  details: { method: "GET", url: "https://api.example.net/data", xhrId: "xhr-1" }
}, sender);
assert.match(deniedConnect.error, /@connect blocked/);
assert.equal(await manager.__securityTest.isUserscriptConnectAllowed(
  { parsedMeta: { connects: ["api.example.net"] } },
  "https://api.example.net/data",
  sender.url
), true);
assert.equal(await manager.__securityTest.isUserscriptConnectAllowed(
  { parsedMeta: { connects: ["self"] } },
  "https://example.com/api",
  sender.url
), true);
assert.equal(await manager.__securityTest.isUserscriptConnectAllowed(
  { parsedMeta: { connects: [] } },
  "https://example.com/api",
  sender.url
), false);

const mismatchedUrl = await manager.handleGMCall({
  action: "bridgeInit",
  requestId: "wrong-url",
  scriptId: script.id,
  bootstrapCapability
}, { ...sender, documentId: "document-2", url: "https://other.example/page" });
assert.equal(mismatchedUrl.code, "URL_MISMATCH");

const highRisk = await manager.handleGMCall({
  action: "bridgeInit",
  requestId: "high-risk",
  scriptId: script.id,
  bootstrapCapability
}, { ...sender, documentId: "document-3", url: "https://secure.paypal.com/" });
assert.equal(highRisk.code, "EXCLUDED_HOST");

const restartedManager = await import(`${managerUrl.href}?service-worker-restart=1`);
const recoveredAfterRestart = await restartedManager.handleGMCall({
  action: "bridgeInit",
  requestId: "restart-init",
  scriptId: script.id,
  bootstrapCapability
}, { ...sender, documentId: "document-after-restart" });
assert.equal(recoveredAfterRestart.ok, true);

await chrome.storage.local.set({ fp_settings: { userscriptsEnabled: false } });
const disabledResult = await manager.registerStoredUserscripts();
assert.equal(disabledResult.count, 0);
assert.equal(disabledResult.disabled, true);
assert.equal(registeredScripts.length, 0);

const engineSource = fs.readFileSync(path.join(root, "extension/userscripts/engine.js"), "utf8");
assert.doesNotMatch(engineSource, /GM_API_CALL|window\.postMessage|gm-shim/);

console.log("EAZ-SEC-001 focused security tests passed");
