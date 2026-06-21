// EazyFill userscript scheduling and SPA rerun helpers.
(function () {
  "use strict";

  if (window.UserscriptRuntime) return;

  const executed = new Set();
  let watcherInstalled = false;

  function stableScriptId(scriptData) {
    return String(scriptData.id || scriptData.name || "unknown");
  }

  function executionKey(scriptData, url) {
    const frameKey = window.top === window.self ? "top" : location.pathname;
    return `${stableScriptId(scriptData)}|${frameKey}|${url}`;
  }

  function makeExecutionId(scriptData, url) {
    let hash = 0;
    const raw = `${executionKey(scriptData, url)}|${scriptData.version || ""}`;
    for (let i = 0; i < raw.length; i += 1) {
      hash = ((hash << 5) - hash + raw.charCodeAt(i)) | 0;
    }
    return `${stableScriptId(scriptData)}@${Math.abs(hash)}`;
  }

  function schedule(scriptData, execute, url, reason) {
    const key = executionKey(scriptData, url);
    if (executed.has(key)) return false;
    executed.add(key);

    const meta = scriptData.parsedMeta || {};
    const runAt = meta.runAt || "document-idle";
    const payload = {
      ...scriptData,
      executionId: makeExecutionId(scriptData, url),
      runReason: reason || "load"
    };
    const run = () => execute(payload);

    if (reason === "spa" || runAt === "document-start") {
      run();
    } else if (runAt === "document-end") {
      if (document.readyState === "interactive" || document.readyState === "complete") {
        run();
      } else {
        document.addEventListener("DOMContentLoaded", run, { once: true });
      }
    } else if (document.readyState === "complete") {
      run();
    } else {
      window.addEventListener("load", () => setTimeout(run, 0), { once: true });
    }
    return true;
  }

  function runMatchingScripts(options) {
    const scripts = Array.isArray(options.scripts) ? options.scripts : [];
    const url = options.url || location.href;
    const shouldRun = options.shouldRun;
    const execute = options.execute;
    const reason = options.reason || "load";
    const frameInfo = { isTop: window.top === window.self };
    let count = 0;

    for (const scriptData of scripts) {
      try {
        if (shouldRun(scriptData, url, frameInfo) && schedule(scriptData, execute, url, reason)) {
          count += 1;
        }
      } catch (error) {
        console.warn("[EazyFill Userscript Runtime] Match/schedule failed:", scriptData?.name || scriptData?.id, error);
      }
    }
    return count;
  }

  function installSpaWatcher(onChange) {
    if (watcherInstalled) return;
    watcherInstalled = true;
    let lastUrl = location.href;
    let timer = null;

    const check = () => {
      const nextUrl = location.href;
      if (nextUrl === lastUrl) return;
      lastUrl = nextUrl;
      clearTimeout(timer);
      timer = setTimeout(() => onChange(nextUrl), 50);
    };

    window.addEventListener("popstate", check, true);
    window.addEventListener("hashchange", check, true);
    setInterval(check, 500);
  }

  window.UserscriptRuntime = {
    installSpaWatcher,
    runMatchingScripts,
    _test: { makeExecutionId }
  };
})();
