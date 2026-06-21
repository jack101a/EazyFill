// EazyFill userscripts execute in the browser-managed USER_SCRIPT world.
// Privileged GM calls use runtime.onUserScriptMessage and never cross page context.
(function () {
  "use strict";

  if (window.__EAZYFILL_USERSCRIPT_BRIDGE_READY__) return;
  window.__EAZYFILL_USERSCRIPT_BRIDGE_READY__ = true;
})();
