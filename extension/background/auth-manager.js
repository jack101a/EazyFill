import { getExtensionStorage, removeProtectedValues, setExtensionStorage } from "./protected-storage.js";

function sanitizeApiKey(apiKey) {
  return String(apiKey || "").trim();
}

function keyPrefix(apiKey) {
  const clean = sanitizeApiKey(apiKey);
  if (!clean) return "";
  return clean.length <= 12 ? clean : `${clean.slice(0, 8)}...${clean.slice(-4)}`;
}

function authSnapshot(auth = {}) {
  return {
    authenticated: !!auth.apiKey && auth.valid !== false,
    valid: auth.valid !== false && !!auth.apiKey,
    keyPrefix: auth.keyPrefix || keyPrefix(auth.apiKey),
    user: auth.user || null,
    plan: auth.plan || null,
    credits: auth.credits || null,
    device: auth.device || null,
    syncSecret: auth.syncSecret || "",
    lastVerifiedAt: auth.lastVerifiedAt || null,
    lastError: auth.lastError || ""
  };
}

export function createAuthManager({ apiClient }) {
  async function getAuthRecord() {
    const data = await getExtensionStorage(["fp_auth"]);
    return data.fp_auth || {};
  }

  async function getAuthStatus() {
    return { ok: true, auth: authSnapshot(await getAuthRecord()) };
  }

  async function verifyApiKey(apiKey) {
    const response = await apiClient.post("/v2/auth/verify-key", { api_key: apiKey }, { retry: false, skipAuth: true });
    return normalizeVerification(response);
  }

  function normalizeVerification(response) {
    return {
      valid: response.valid !== false,
      user: {
        id: response.user_id || response.user?.id || null,
        name: response.user?.name || "",
        email: response.user?.email || "",
        mobile: response.user?.mobile || ""
      },
      plan: response.plan || null,
      credits: response.credits || null,
      device: response.device || null,
      syncSecret: response.sync_secret || response.syncSecret || "",
      keyInfo: response.key_info || null
    };
  }

  async function saveApiKey(apiKey, options = {}) {
    const clean = sanitizeApiKey(apiKey);
    if (!clean) throw new Error("API key is required");
    if (!clean.startsWith("fp_") && options.allowLegacyPrefix !== true) {
      throw new Error("EazyFill API keys must start with fp_");
    }

    let verification = null;
    if (options.verify !== false) {
      verification = await verifyApiKey(clean);
      if (!verification.valid) throw new Error("API key verification failed");
    }

    const auth = {
      apiKey: clean,
      keyPrefix: keyPrefix(clean),
      valid: verification ? verification.valid : true,
      user: verification?.user || null,
      plan: verification?.plan || null,
      credits: verification?.credits || null,
      device: verification?.device || null,
      syncSecret: verification?.syncSecret || "",
      keyInfo: verification?.keyInfo || null,
      lastVerifiedAt: verification ? Date.now() : null,
      lastError: ""
    };
    await setExtensionStorage({ fp_auth: auth });
    if (verification?.credits) await setExtensionStorage({ fp_credits: verification.credits });
    return { ok: true, auth: authSnapshot(auth) };
  }

  async function registerAccount(payload = {}) {
    const response = await apiClient.post("/v2/auth/register", {
      identifier: payload.identifier || "",
      email: payload.email || "",
      mobile: payload.mobile || "",
      name: payload.name || "",
      plan_code: payload.planCode || payload.plan_code || "free"
    }, { retry: false, skipAuth: true });
    return { ok: true, ...response };
  }

  async function verifyOtp(payload = {}) {
    const response = await apiClient.post("/v2/auth/verify-otp", {
      challenge_id: payload.challengeId || payload.challenge_id || "",
      otp: payload.otp || "",
      device_name: payload.deviceName || payload.device_name || "EazyFill Extension"
    }, { retry: false, skipAuth: true });
    const apiKey = sanitizeApiKey(response.api_key);
    if (!apiKey) throw new Error("OTP verified but no API key was returned");
    const verification = normalizeVerification(response);
    const auth = {
      apiKey,
      keyPrefix: keyPrefix(apiKey),
      valid: verification.valid,
      user: verification.user,
      plan: verification.plan,
      credits: verification.credits,
      device: verification.device,
      syncSecret: verification.syncSecret,
      keyInfo: verification.keyInfo,
      lastVerifiedAt: Date.now(),
      lastError: ""
    };
    await setExtensionStorage({ fp_auth: auth });
    if (verification.credits) await setExtensionStorage({ fp_credits: verification.credits });
    return { ok: true, auth: authSnapshot(auth) };
  }

  async function refreshCachedStatus() {
    const auth = await getAuthRecord();
    if (!auth.apiKey) return { ok: true, auth: authSnapshot(auth) };
    try {
      const response = await apiClient.post("/v2/auth/refresh", {}, { retry: false });
      const verification = normalizeVerification(response);
      const nextAuth = {
        ...auth,
        valid: verification.valid,
        user: verification.user,
        plan: verification.plan,
        credits: verification.credits,
        device: verification.device,
        syncSecret: verification.syncSecret || auth.syncSecret || "",
        keyInfo: verification.keyInfo,
        lastVerifiedAt: Date.now(),
        lastError: ""
      };
      await setExtensionStorage({ fp_auth: nextAuth });
      if (verification.credits) await setExtensionStorage({ fp_credits: verification.credits });
      return { ok: true, auth: authSnapshot(nextAuth) };
    } catch (error) {
      const invalidKey = error.status === 401 || error.status === 403 || error.data?.valid === false;
      const nextAuth = {
        ...auth,
        valid: invalidKey ? false : auth.valid !== false,
        lastError: error.message || String(error),
        lastVerifiedAt: Date.now()
      };
      await setExtensionStorage({ fp_auth: nextAuth });
      return { ok: false, error: nextAuth.lastError, auth: authSnapshot(nextAuth) };
    }
  }

  async function logout() {
    await removeProtectedValues(["fp_auth"]);
    await chrome.storage.local.remove(["fp_credits"]);
    return { ok: true, auth: authSnapshot({}) };
  }

  return {
    getAuthStatus,
    logout,
    refreshCachedStatus,
    registerAccount,
    saveApiKey,
    verifyApiKey,
    verifyOtp
  };
}
