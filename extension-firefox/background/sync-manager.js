import { getExtensionStorage, setExtensionStorage } from "./protected-storage.js";
import { decryptSyncPayload, encryptSyncPayload, jsonFromBase64, jsonToBase64, sha256Base64Payload } from "../lib/crypto-utils.js";

const SYNC_KEYS = ["fp_rules", "fp_scripts", "fp_settings", "fp_profiles", "fp_captcha_selectors", "fp_sync_meta"];

async function getDeviceId() {
  const data = await chrome.storage.local.get(["fp_device_id"]);
  if (data.fp_device_id) return data.fp_device_id;
  const deviceId = crypto.randomUUID ? crypto.randomUUID() : `device_${Date.now()}_${Math.random().toString(36).slice(2)}`;
  await chrome.storage.local.set({ fp_device_id: deviceId });
  return deviceId;
}

function requireAuth(auth) {
  const apiKey = String(auth?.apiKey || "").trim();
  if (!apiKey) throw new Error("Connect EazyFill before syncing");
  return apiKey;
}

function requireSyncSecret(auth) {
  const syncSecret = String(auth?.syncSecret || "").trim();
  if (!syncSecret) throw new Error("Sign in again before syncing");
  return syncSecret;
}

function nextVersion(meta = {}) {
  return Math.max(1, Number(meta.version || 0) + 1);
}

function scrubSettings(settings = {}) {
  const { apiKey, ...safeSettings } = settings || {};
  return safeSettings;
}

export function createSyncManager({ apiClient }) {
  async function buildEncryptedUpload() {
    const data = await getExtensionStorage(["fp_auth", ...SYNC_KEYS]);
    const apiKey = requireAuth(data.fp_auth);
    const syncSecret = requireSyncSecret(data.fp_auth);
    const deviceId = await getDeviceId();
    const syncVersion = nextVersion(data.fp_sync_meta);
    const payload = {
      v: 1,
      exportedAt: new Date().toISOString(),
      rules: Array.isArray(data.fp_rules) ? data.fp_rules : [],
      scripts: Array.isArray(data.fp_scripts) ? data.fp_scripts : [],
      profiles: Array.isArray(data.fp_profiles) ? data.fp_profiles : [],
      captchaSelectors: data.fp_captcha_selectors && typeof data.fp_captcha_selectors === "object" ? data.fp_captcha_selectors : {},
      settings: scrubSettings(data.fp_settings || {}),
      syncVersion
    };
    const envelope = await encryptSyncPayload(payload, { apiKey, syncSecret, deviceId });
    const encryptedBlob = jsonToBase64(envelope);
    return {
      deviceId,
      syncVersion,
      encryptedBlob,
      blobHash: await sha256Base64Payload(encryptedBlob)
    };
  }

  async function push() {
    const upload = await buildEncryptedUpload();
    const response = await apiClient.post("/v2/sync/push", {
      device_id: upload.deviceId,
      sync_version: upload.syncVersion,
      encrypted_blob: upload.encryptedBlob,
      blob_hash: upload.blobHash
    });
    const meta = {
      version: response.sync_version || upload.syncVersion,
      lastSyncAt: Date.now(),
      lastDirection: "push",
      blobSizeBytes: response.blob_size_bytes || 0,
      blobHash: response.blob_hash || upload.blobHash
    };
    await setExtensionStorage({ fp_sync_meta: meta });
    return { ok: true, sync: response, meta };
  }

  async function pull() {
    const data = await getExtensionStorage(["fp_auth"]);
    const apiKey = requireAuth(data.fp_auth);
    const syncSecret = requireSyncSecret(data.fp_auth);
    const deviceId = await getDeviceId();
    const response = await apiClient.get("/v2/sync/pull");
    if (!response.found) return { ok: true, found: false };

    const envelope = jsonFromBase64(response.encrypted_blob);
    const payload = await decryptSyncPayload(envelope, { apiKey, syncSecret, deviceId });
    const updates = {
      fp_rules: Array.isArray(payload.rules) ? payload.rules : [],
      fp_scripts: Array.isArray(payload.scripts) ? payload.scripts : [],
      fp_profiles: Array.isArray(payload.profiles) ? payload.profiles : [],
      fp_captcha_selectors: payload.captchaSelectors && typeof payload.captchaSelectors === "object" ? payload.captchaSelectors : {},
      fp_settings: payload.settings || {},
      fp_sync_meta: {
        version: response.sync_version || payload.syncVersion || 1,
        lastSyncAt: Date.now(),
        lastDirection: "pull",
        blobSizeBytes: response.blob_size_bytes || 0,
        blobHash: response.blob_hash || ""
      }
    };
    await setExtensionStorage(updates);
    return { ok: true, found: true, sync: response, meta: updates.fp_sync_meta };
  }

  async function status() {
    const response = await apiClient.get("/v2/sync/status");
    return { ok: true, sync: response };
  }

  async function deleteCloudCopy() {
    const response = await apiClient.delete("/v2/sync/delete");
    const data = await getExtensionStorage(["fp_sync_meta"]);
    await setExtensionStorage({
      fp_sync_meta: {
        ...(data.fp_sync_meta || {}),
        lastSyncAt: Date.now(),
        lastDirection: "delete",
        blobSizeBytes: 0
      }
    });
    return { ok: true, sync: response };
  }

  return {
    push,
    pull,
    status,
    deleteCloudCopy
  };
}
