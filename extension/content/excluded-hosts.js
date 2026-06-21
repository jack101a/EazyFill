(function () {
  "use strict";

  if (window.EazyFillExcludedHosts) return;

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

  function normalizedHost(hostname = location.hostname) {
    return String(hostname || "").replace(/^www\./, "").toLowerCase();
  }

  function isExcludedHost(hostname = location.hostname) {
    const host = normalizedHost(hostname);
    return host.endsWith(".bank.in")
      || host.includes("netbanking")
      || blockedHosts.some((domain) => host === domain || host.endsWith(`.${domain}`));
  }

  window.EazyFillExcludedHosts = {
    isExcludedHost,
    normalizedHost
  };
})();
