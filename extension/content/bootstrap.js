// EazyFill content bootstrap. Feature modules are added in Sprint 2.
(function () {
  "use strict";

  if (window.__EAZYFILL_CONTENT_BOOTSTRAPPED__) return;
  window.__EAZYFILL_CONTENT_BOOTSTRAPPED__ = true;

  const blockedHosts = [
    "paypal.com",
    "stripe.com",
    "razorpay.com",
    "paytm.com",
    "phonepe.com",
    "hdfcbank.com",
    "icicibank.com",
    "axisbank.com",
    "kotak.com",
    "sbi.co.in",
    "onlinesbi.sbi"
  ];

  function isExcludedHost() {
    const host = String(location.hostname || "").replace(/^www\./, "").toLowerCase();
    return host.endsWith(".bank.in")
      || host.includes("netbanking")
      || blockedHosts.some((domain) => host === domain || host.endsWith(`.${domain}`));
  }

  if (!/^https?:$/i.test(location.protocol) || isExcludedHost()) return;

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message?.type !== "EAZYFILL_PING") return false;
    sendResponse({ ok: true, url: location.href });
    return false;
  });

  chrome.runtime.sendMessage({
    type: "GET_EXTENSION_STORAGE",
    keys: ["fp_settings"]
  }).catch(() => {});
})();
