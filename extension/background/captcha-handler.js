import { setExtensionStorage } from "./protected-storage.js";

async function activeTab() {
  const activeTabs = await chrome.tabs.query({ active: true, currentWindow: true });
  const activeSupported = activeTabs.find((tab) => tab?.id && /^https?:/i.test(tab.url || ""));
  if (activeSupported) return activeSupported;
  const tabs = await chrome.tabs.query({ currentWindow: true });
  return tabs.find((tab) => tab?.id && /^https?:/i.test(tab.url || "")) || null;
}

function sendTabMessage(tabId, message) {
  return new Promise((resolve) => {
    chrome.tabs.sendMessage(tabId, message, (response) => {
      if (chrome.runtime.lastError) {
        resolve({ ok: false, error: chrome.runtime.lastError.message });
        return;
      }
      resolve(response || { ok: false, error: "No response from page" });
    });
  });
}

function solveBodyFromMessage(message) {
  return {
    type: "image",
    payload_base64: message.payloadBase64 || "",
    domain: message.domain || "",
    field_name: message.fieldName || message.field_name || message.selectorId || message.selector_id || "",
    source_selector: message.sourceSelector || message.source_selector || "",
    target_selector: message.targetSelector || message.target_selector || "",
    metadata: {
      ...(message.metadata || {}),
      selectorId: message.selectorId || message.selector_id || "",
      fieldName: message.fieldName || message.field_name || "",
      sourceSelector: message.sourceSelector || message.source_selector || "",
      targetSelector: message.targetSelector || message.target_selector || ""
    }
  };
}

export function createCaptchaHandler({ apiClient, creditManager } = {}) {
  async function solveRequest(message) {
    const body = solveBodyFromMessage(message);
    if (!body.payload_base64) {
      throw new Error("CAPTCHA payload is empty");
    }

    if (creditManager?.assertCaptchaAvailable) {
      await creditManager.assertCaptchaAvailable();
    }

    const response = await apiClient.post("/v2/captcha/solve", body);
    const creditsUsed = response.credits_used ?? response.credits_charged ?? 0;
    const captchaCredits = {
      captcha: {
        usedToday: response.used_today ?? response.credits_used_today ?? undefined,
        remaining: response.credits_remaining ?? response.remaining ?? undefined,
        dailyLimit: response.daily_limit ?? undefined,
        resetsAt: response.resets_at || null,
        meterEventType: response.meter_event_type || "captcha.solve.image",
        solveCost: response.credit_unit_cost ?? creditsUsed
      }
    };
    if (captchaCredits.captcha.remaining !== undefined || captchaCredits.captcha.usedToday !== undefined) {
      const current = creditManager?.getCredits ? await creditManager.getCredits() : { credits: {} };
      await setExtensionStorage({
        fp_credits: {
          ...(current.credits || {}),
          captcha: {
            ...((current.credits || {}).captcha || {}),
            ...captchaCredits.captcha
          }
        }
      });
    } else if (creditManager?.refreshCredits) {
      await creditManager.refreshCredits();
    }

    return {
      ok: true,
      result: response.result,
      confidence: response.confidence,
      processingMs: response.processing_ms,
      creditsUsed,
      creditsRemaining: response.credits_remaining ?? response.remaining
    };
  }

  async function solveCurrentTab(message = {}) {
    const tab = await activeTab();
    if (!tab?.id || !/^https?:/i.test(tab.url || "")) {
      throw new Error("No supported active tab");
    }
    return sendTabMessage(tab.id, {
      type: "CAPTCHA_SOLVE_NOW",
      config: message.config || null
    });
  }

  async function pickElement(message = {}) {
    const tab = await activeTab();
    if (!tab?.id || !/^https?:/i.test(tab.url || "")) {
      throw new Error("No supported active tab");
    }
    return sendTabMessage(tab.id, {
      type: "PICK_ELEMENT",
      targetField: message.targetField || "source"
    });
  }

  return {
    pickElement,
    solveCurrentTab,
    solveRequest
  };
}
