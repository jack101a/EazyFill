import assert from "node:assert/strict";
import {
  base64ToBytes,
  bytesToBase64,
  decryptSyncPayload,
  encryptSyncPayload
} from "../extension/lib/crypto-utils.js";

async function oldDeviceScopedEnvelope(payload, { apiKey, deviceId }) {
  const saltBytes = new Uint8Array(16);
  crypto.getRandomValues(saltBytes);
  const ivBytes = new Uint8Array(12);
  crypto.getRandomValues(ivBytes);
  const salt = bytesToBase64(saltBytes);
  const material = await crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(`${apiKey}\n${deviceId}`),
    "HKDF",
    false,
    ["deriveKey"]
  );
  const key = await crypto.subtle.deriveKey(
    {
      name: "HKDF",
      salt: base64ToBytes(salt),
      info: new TextEncoder().encode("eazyfill sync blob v1"),
      hash: "SHA-256"
    },
    material,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"]
  );
  const ciphertext = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv: ivBytes },
    key,
    new TextEncoder().encode(JSON.stringify(payload))
  );
  return {
    v: 1,
    alg: "AES-GCM-HKDF-SHA256",
    salt,
    iv: bytesToBase64(ivBytes),
    ciphertext: bytesToBase64(new Uint8Array(ciphertext))
  };
}

const syncSecret = "account-sync-secret";
const payload = {
  v: 1,
  rules: [{ id: "rule-1", domain: "example.com" }],
  scripts: [{ id: "script-1", name: "Local script" }],
  settings: { syncEnabled: true }
};

const envelope = await encryptSyncPayload(payload, {
  sessionToken: "efs_device_a",
  syncSecret,
  deviceId: "device-a"
});
assert.equal(envelope.v, 2);
assert.equal(envelope.alg, "AES-GCM-HKDF-SHA256-USER");
assert.deepEqual(
  await decryptSyncPayload(envelope, {
    sessionToken: "efs_device_b",
    syncSecret,
    deviceId: "device-b"
  }),
  payload,
  "new sync blobs must decrypt on a different device with the same account sync secret"
);

await assert.rejects(
  () => decryptSyncPayload(envelope, { sessionToken: "efs_device_b", deviceId: "device-b" }),
  /decrypt|operation|failed/i,
  "new sync blobs should not decrypt with another device API key alone"
);

const apiKey = "fp_test_shared_key";
const oldEnvelope = await oldDeviceScopedEnvelope(payload, { apiKey, deviceId: "device-a" });
assert.deepEqual(
  await decryptSyncPayload(oldEnvelope, { legacyApiKey: apiKey, deviceId: "device-a" }),
  payload,
  "old same-device blobs should remain recoverable"
);

await assert.rejects(
  () => decryptSyncPayload(oldEnvelope, { legacyApiKey: apiKey, deviceId: "device-b" }),
  /decrypt|operation|failed/i,
  "old device-scoped blobs should not pretend to support cross-device restore"
);

console.log("sync crypto compatibility ok");
