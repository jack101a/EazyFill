import { getExtensionStorage, removeProtectedValues, setExtensionStorage } from "./protected-storage.js";

function hasCredential(auth = {}) {
  return !!String(auth.sessionToken || auth.session_token || "").trim();
}

function authSnapshot(auth = {}) {
  const authenticated = hasCredential(auth) && auth.valid !== false;
  return {
    authenticated,
    valid: auth.valid !== false && hasCredential(auth),
    keyPrefix: "Session",
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

function planAllowsSync(plan) {
  if (!plan || typeof plan !== "object") return false;
  if (plan.features && Object.prototype.hasOwnProperty.call(plan.features, "cloud_sync")) {
    return plan.features.cloud_sync === true;
  }
  if (plan.allowed_services && Object.prototype.hasOwnProperty.call(plan.allowed_services, "sync")) {
    return plan.allowed_services.sync === true;
  }
  return false;
}

async function applyPlanGatedSettings(plan) {
  const data = await getExtensionStorage(["fp_settings"]).catch(() => ({}));
  await setExtensionStorage({
    fp_settings: {
      ...(data.fp_settings || {}),
      syncEnabled: planAllowsSync(plan)
    }
  });
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
    const auth = {
      keyPrefix: "Session",
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
    await applyPlanGatedSettings(auth.plan);
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
      await applyPlanGatedSettings(nextAuth.plan);
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
    verifyOtp
  };
}
