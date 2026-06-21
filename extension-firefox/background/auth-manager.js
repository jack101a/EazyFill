import { getExtensionStorage, removeProtectedValues, setExtensionStorage } from "./protected-storage.js";

function sanitizeApiKey(apiKey) {
  return String(apiKey || "").trim();
}

function keyPrefix(apiKey) {
  const clean = sanitizeApiKey(apiKey);
  if (!clean) return "";
  return clean.length <= 12 ? clean : `${clean.slice(0, 8)}...${clean.slice(-4)}`;
}

function hasCredential(auth = {}) {
  return !!String(auth.sessionToken || auth.apiKey || "").trim();
}

function authSnapshot(auth = {}) {
  const authenticated = hasCredential(auth) && auth.valid !== false;
  return {
    authenticated,
    valid: auth.valid !== false && hasCredential(auth),
    keyPrefix: auth.keyPrefix || (auth.apiKey ? keyPrefix(auth.apiKey) : "Session"),
    user: auth.user || null,
    plan: auth.plan || null,
    credits: auth.credits || null,
    device: auth.device || null,
    session: auth.session || null,
    sessionToken: auth.sessionToken || "",
    syncSecret: auth.syncSecret || "",
    lastVerifiedAt: auth.lastVerifiedAt || null,
    lastError: auth.lastError || ""
  };
}

async function disableAccountGatedState() {
  const data = await getExtensionStorage(["fp_settings"]).catch(() => ({}));
  await setExtensionStorage({
    fp_settings: {
      ...(data.fp_settings || {}),
      syncEnabled: false
    }
  });
  await chrome.storage.local.remove(["fp_credits", "fp_sync_meta"]);
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
      session: response.session || null,
      sessionToken: response.session_token || response.sessionToken || "",
      syncSecret: response.sync_secret || response.syncSecret || "",
      keyInfo: response.key_info || null
    };
  }

  async function saveApiKey(apiKey, options = {}) {
    const clean = sanitizeApiKey(apiKey);
    if (!clean) throw new Error("Sign in is required");
    if (!clean.startsWith("fp_") && options.allowLegacyPrefix !== true) {
      throw new Error("This EazyFill sign-in token is not supported");
    }

    let verification = null;
    if (options.verify !== false) {
      verification = await verifyApiKey(clean);
      if (!verification.valid) throw new Error("Could not verify this EazyFill session");
    }

    const auth = {
      apiKey: clean,
      keyPrefix: keyPrefix(clean),
      valid: verification ? verification.valid : true,
      user: verification?.user || null,
      plan: verification?.plan || null,
      credits: verification?.credits || null,
      device: verification?.device || null,
      session: verification?.session || null,
      sessionToken: verification?.sessionToken || "",
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
    const email = payload.email || payload.identifier || "";
    const hasName = String(payload.name || "").trim().length > 0;
    const endpoint = hasName ? "/v2/account/profile" : "/v2/account/start";
    const response = await apiClient.post(endpoint, {
      identifier: email,
      email,
      name: payload.name || "",
      plan_code: payload.planCode || payload.plan_code || "free"
    }, { retry: false, skipAuth: true });
    return { ok: true, ...response };
  }

  async function verifyOtp(payload = {}) {
    const response = await apiClient.post("/v2/account/verify", {
      challenge_id: payload.challengeId || payload.challenge_id || "",
      otp: payload.otp || "",
      device_name: payload.deviceName || payload.device_name || "EazyFill Extension"
    }, { retry: false, skipAuth: true });
    const verification = normalizeVerification(response);
    if (!verification.sessionToken) throw new Error("OTP verified but sign-in could not be completed");
    const apiKey = sanitizeApiKey(response.api_key);
    const auth = {
      apiKey,
      keyPrefix: apiKey ? keyPrefix(apiKey) : "Session",
      valid: verification.valid,
      user: verification.user,
      plan: verification.plan,
      credits: verification.credits,
      device: verification.device,
      session: verification.session,
      sessionToken: verification.sessionToken,
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
    if (!hasCredential(auth)) return { ok: true, auth: authSnapshot(auth) };
    try {
      const response = await apiClient.post("/v2/account/refresh", {}, { retry: false });
      const verification = normalizeVerification(response);
      const nextAuth = {
        ...auth,
        valid: verification.valid,
        user: verification.user,
        plan: verification.plan,
        credits: verification.credits,
        device: verification.device,
        session: verification.session || auth.session || null,
        sessionToken: verification.sessionToken || auth.sessionToken || "",
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
      if (invalidKey) {
        await removeProtectedValues(["fp_auth"]);
        await disableAccountGatedState();
        return { ok: false, error: error.message || String(error), auth: authSnapshot({}) };
      }
      const nextAuth = {
        ...auth,
        valid: auth.valid !== false,
        lastError: error.message || String(error),
        lastVerifiedAt: Date.now()
      };
      await setExtensionStorage({ fp_auth: nextAuth });
      return { ok: false, error: nextAuth.lastError, auth: authSnapshot(nextAuth) };
    }
  }

  async function logout() {
    await apiClient.post("/v2/account/logout", {}, { retry: false }).catch(() => null);
    await removeProtectedValues(["fp_auth"]);
    await disableAccountGatedState();
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
