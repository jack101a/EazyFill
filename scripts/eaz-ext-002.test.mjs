import assert from "node:assert/strict";
import path from "node:path";
import { pathToFileURL } from "node:url";

const localStore = new Map();
let messageListener = null;

function storageArea(store) {
  return {
    async get(keys) {
      const requested = keys === null ? [...store.keys()] : Array.isArray(keys) ? keys : [keys];
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
    getURL(pathname = "") {
      return `chrome-extension://${this.id}/${String(pathname).replace(/^\/+/, "")}`;
    },
    onMessage: {
      addListener(listener) {
        messageListener = listener;
      }
    }
  },
  storage: {
    local: storageArea(localStore),
    session: storageArea(new Map()),
    onChanged: { addListener() {} }
  },
  tabs: {
    async query() {
      return [];
    },
    sendMessage() {}
  },
  notifications: { create() {} },
  downloads: { download() {} }
};

const root = path.resolve(import.meta.dirname, "..");
const hubUrl = pathToFileURL(path.join(root, "extension/background/messaging-hub.js"));
const { installMessageHub, registerCoreMessageHandlers } = await import(hubUrl);

registerCoreMessageHandlers();
installMessageHub();
assert.equal(typeof messageListener, "function");

const optionsSender = {
  id: chrome.runtime.id,
  url: chrome.runtime.getURL("options/options.html"),
  tab: { id: 3, url: chrome.runtime.getURL("options/options.html") }
};
const popupSender = {
  id: chrome.runtime.id,
  url: chrome.runtime.getURL("popup/popup.html")
};
const contentSender = {
  id: chrome.runtime.id,
  url: "https://example.com/form",
  tab: { id: 7, url: "https://example.com/form" }
};

function send(message, sender) {
  return new Promise((resolve, reject) => {
    const handled = messageListener(message, sender, resolve);
    if (!handled) reject(new Error(`Message was not handled: ${message.type}`));
  });
}

let response = await send({
  type: "SET_EXTENSION_STORAGE",
  values: {
    fp_auth: { apiKey: "fp_test_secret" },
    fp_settings: { autofillEnabled: true },
    fp_rules: [{ id: "rule-1" }],
    fp_profiles: [{ id: "default", values: { fullName: "Ada Lovelace" } }]
  }
}, optionsSender);
assert.equal(response.ok, true);

response = await send({
  type: "GET_EXTENSION_STORAGE",
  keys: ["fp_auth", "fp_settings", "fp_rules", "fp_profiles"]
}, optionsSender);
assert.equal(response.ok, true);
assert.equal(response.data.fp_auth.apiKey, "fp_test_secret");

response = await send({
  type: "SET_EXTENSION_STORAGE",
  values: { fp_settings: { autofillEnabled: false } }
}, popupSender);
assert.equal(response.ok, true);

response = await send({
  type: "GET_EXTENSION_STORAGE",
  keys: ["fp_settings", "fp_rules", "fp_profiles", "fp_captcha_selectors"]
}, contentSender);
assert.equal(response.ok, true);
assert.equal(response.data.fp_settings.autofillEnabled, false);

response = await send({
  type: "GET_EXTENSION_STORAGE",
  keys: ["fp_settings", "fp_auth"]
}, contentSender);
assert.equal(response.ok, false);
assert.match(response.error, /sensitive storage key "fp_auth"/);
assert.equal(response.data, undefined);

for (const key of ["fp_device_id", "api_key", "payment_secret", "credit_card", "us_storage:arbitrary"]) {
  response = await send({ type: "GET_EXTENSION_STORAGE", keys: [key] }, contentSender);
  assert.equal(response.ok, false, `${key} should be denied`);
  assert.match(response.error, /sensitive storage key/);
}

response = await send({
  type: "SET_EXTENSION_STORAGE",
  values: { fp_settings: { autofillEnabled: true } }
}, contentSender);
assert.equal(response.ok, false);
assert.match(response.error, /storage key "fp_settings" is not allowed/);

response = await send({
  type: "SET_EXTENSION_STORAGE",
  values: { fp_settings: {}, arbitrary_key: "blocked" }
}, optionsSender);
assert.equal(response.ok, false);
assert.match(response.error, /storage key "arbitrary_key" is not allowed/);
assert.equal(localStore.has("arbitrary_key"), false);

response = await send({
  type: "GET_EXTENSION_STORAGE",
  keys: ["us_storage:any-script"]
}, optionsSender);
assert.equal(response.ok, false);
assert.match(response.error, /sensitive storage key "us_storage:any-script"/);

response = await send({
  type: "GET_EXTENSION_STORAGE",
  keys: ["fp_settings"]
}, {
  id: chrome.runtime.id,
  url: chrome.runtime.getURL("untrusted/page.html")
});
assert.equal(response.ok, false);
assert.match(response.error, /sender is not an EazyFill popup, options page, or content script/);

response = await send({
  type: "GET_EXTENSION_STORAGE",
  keys: ["fp_auth"]
}, {
  id: chrome.runtime.id,
  url: "file:///options/options.html",
  tab: { id: 9, url: "file:///options/options.html" }
});
assert.equal(response.ok, false);
assert.match(response.error, /sender is not an EazyFill popup, options page, or content script/);

response = await send({
  type: "GET_EXTENSION_STORAGE",
  keys: "fp_settings"
}, contentSender);
assert.equal(response.ok, false);
assert.match(response.error, /requires a non-empty keys array/);

response = await send({
  type: "SET_EXTENSION_STORAGE",
  values: ["fp_settings"]
}, optionsSender);
assert.equal(response.ok, false);
assert.match(response.error, /requires a values object/);

console.log("EAZ-EXT-002 storage ACL tests passed");
