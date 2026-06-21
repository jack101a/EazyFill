(function () {
  "use strict";
  if (window !== window.top) return;
  const url = location.href;
  window.stop();
  const optionsUrl = chrome.runtime.getURL("options/options.html") + "?installUserScript=" + encodeURIComponent(url);
  location.replace(optionsUrl);
})();
