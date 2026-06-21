import { getExtensionStorage, setExtensionStorage } from "./protected-storage.js";

const DEFAULT_CREDITS = {
  captcha: {
    usedToday: 0,
    dailyLimit: 0,
    remaining: 0,
    resetsAt: null,
    solveCost: 0
  },
  autofill: {
    executionsToday: 0
  }
};

function normalizeCredits(raw = {}) {
  const captcha = raw.captcha || raw;
  return {
    captcha: {
      usedToday: captcha.usedToday ?? captcha.used_today ?? 0,
      dailyLimit: captcha.dailyLimit ?? captcha.daily_limit ?? captcha.captcha_daily_limit ?? 0,
      remaining: captcha.remaining ?? captcha.captcha_remaining_today ?? 0,
      resetsAt: captcha.resetsAt || captcha.resets_at || null,
      meterEventType: captcha.meterEventType || captcha.meter_event_type || "captcha.solve.image",
      solveCost: captcha.solveCost ?? captcha.solve_cost ?? captcha.unit_cost ?? 0
    },
    autofill: {
      executionsToday: raw.autofill?.executionsToday ?? raw.autofill?.executions_today ?? 0,
      rulesCount: raw.autofill?.rules_count ?? undefined,
      rulesLimit: raw.autofill?.rules_limit ?? undefined
    },
    scripts: raw.scripts || {}
  };
}

export function createCreditManager({ apiClient } = {}) {
  async function getCredits() {
    const data = await getExtensionStorage(["fp_credits"]);
    return { ok: true, credits: normalizeCredits(data.fp_credits || DEFAULT_CREDITS) };
  }

  async function refreshCredits() {
    if (!apiClient) return getCredits();
    const response = await apiClient.get("/v2/credits/balance");
    const credits = normalizeCredits(response);
    await setExtensionStorage({ fp_credits: credits });
    return { ok: true, credits };
  }

  async function assertCaptchaAvailable() {
    const current = await getCredits();
    const remaining = current.credits?.captcha?.remaining;
    const solveCost = Number(current.credits?.captcha?.solveCost || 0);
    if (remaining !== undefined && solveCost > 0 && remaining < solveCost) {
      const error = new Error("Daily CAPTCHA limit reached");
      error.code = "daily_quota_exceeded";
      throw error;
    }
    return true;
  }

  async function consumeLocalCaptchaCredit(amount = 0) {
    if (!Number(amount || 0)) return getCredits();
    const current = await getCredits();
    const captcha = current.credits.captcha || {};
    const used = Number(captcha.usedToday || 0) + Number(amount || 0);
    const remaining = Math.max(0, Number(captcha.remaining ?? captcha.dailyLimit ?? 0) - Number(amount || 0));
    const next = {
      ...current.credits,
      captcha: {
        ...captcha,
        usedToday: used,
        remaining
      }
    };
    await setExtensionStorage({ fp_credits: next });
    return { ok: true, credits: next };
  }

  async function recordAutofillExecution(amount = 1) {
    const current = await getCredits();
    const next = {
      ...current.credits,
      autofill: {
        ...(current.credits.autofill || {}),
        executionsToday: Number(current.credits.autofill?.executionsToday || 0) + Number(amount || 1)
      }
    };
    await setExtensionStorage({ fp_credits: next });
    return { ok: true, credits: next };
  }

  return {
    assertCaptchaAvailable,
    consumeLocalCaptchaCredit,
    getCredits,
    recordAutofillExecution,
    refreshCredits
  };
}
