(function () {
  "use strict";

  if (window.__EAZYFILL_GM_SHIM_READY__) return;
  window.__EAZYFILL_GM_SHIM_READY__ = true;

  const GM_REQUEST = "EAZYFILL_GM_REQUEST";
  const GM_RESPONSE = "EAZYFILL_GM_RESPONSE";
  const GM_VALUE_CHANGED = "EAZYFILL_GM_VALUE_CHANGED";

  const callbacks = {};
  const valueListeners = {};

  function request(action, payload, scriptId) {
    const requestId = Math.random().toString(36).slice(2);
    window.postMessage({ type: GM_REQUEST, action, requestId, scriptId, ...payload }, "*");
    return new Promise((resolve, reject) => {
      callbacks[requestId] = { resolve, reject };
      setTimeout(() => {
        if (callbacks[requestId]) {
          delete callbacks[requestId];
          reject(new Error("GM request timed out"));
        }
      }, 30000);
    });
  }

  window.addEventListener("message", (event) => {
    if (event.source !== window || event.data?.type !== GM_RESPONSE) return;
    const callback = callbacks[event.data.requestId];
    if (!callback) return;
    delete callbacks[event.data.requestId];
    if (event.data.error) callback.reject(new Error(event.data.error));
    else callback.resolve(event.data);
  });

  window.addEventListener("message", (event) => {
    if (event.source !== window || event.data?.type !== GM_VALUE_CHANGED) return;
    const scriptId = event.data.scriptId || "global";
    const hooks = valueListeners[scriptId] || {};
    const oldStore = event.data.oldValue || {};
    const newStore = event.data.newValue || {};
    const keys = new Set([...Object.keys(oldStore), ...Object.keys(newStore)]);
    keys.forEach((key) => {
      Object.values(hooks[key] || {}).forEach((fn) => {
        try {
          fn(key, oldStore[key], newStore[key], true);
        } catch (error) {
          console.error(error);
        }
      });
    });
  });

  window.__createEazyFillGMApi = function createEazyFillGMApi(scriptId, info) {
    const addStyle = (css) => {
      const style = document.createElement("style");
      style.textContent = String(css || "");
      (document.head || document.documentElement).appendChild(style);
      return style;
    };

    const addElement = (parent, tag, attrs) => {
      let targetParent = parent;
      let targetTag = tag;
      let targetAttrs = attrs;
      if (typeof targetParent === "string") {
        targetAttrs = targetTag;
        targetTag = targetParent;
        targetParent = document.head || document.documentElement;
      }
      const element = document.createElement(String(targetTag || "div"));
      Object.entries(targetAttrs || {}).forEach(([name, value]) => {
        if (name === "textContent") element.textContent = value;
        else if (name === "innerHTML") element.innerHTML = value;
        else element.setAttribute(name, value);
      });
      (targetParent || document.head || document.documentElement).appendChild(element);
      return element;
    };

    const addValueChangeListener = (key, fn) => {
      if (typeof fn !== "function") return "";
      const id = Math.random().toString(36).slice(2);
      const bucket = valueListeners[scriptId] = valueListeners[scriptId] || {};
      const hooks = bucket[key] = bucket[key] || {};
      hooks[id] = fn;
      request("addValueChangeListener", { key, listenerId: id }, scriptId).catch(() => {});
      return id;
    };

    const removeValueChangeListener = (listenerId) => {
      Object.values(valueListeners[scriptId] || {}).forEach((hooks) => delete hooks[listenerId]);
      request("removeValueChangeListener", { listenerId }, scriptId).catch(() => {});
    };

    return {
      info: info || {},
      addStyle,
      addElement,
      getValue: (key, defaultValue) => request("getValue", { key, defaultValue }, scriptId).then((response) => response.value),
      setValue: (key, value) => request("setValue", { key, value }, scriptId).then((response) => response.ok),
      deleteValue: (key) => request("deleteValue", { key }, scriptId).then((response) => response.ok),
      listValues: () => request("listValues", {}, scriptId).then((response) => response.values || []),
      addValueChangeListener,
      removeValueChangeListener,
      notification: (details) => request("notification", { details }, scriptId).catch(() => ({ ok: false })),
      openInTab: (url, opts) => request("openInTab", { details: { ...(opts || {}), url } }, scriptId),
      download: (details, name) => request("download", { details: typeof details === "string" ? { url: details, name } : details }, scriptId),
      registerMenuCommand: (text, callback, opts) => {
        const id = opts?.id || Math.random().toString(36).slice(2);
        request("registerMenuCommand", { details: { id, text } }, scriptId).catch(() => {});
        return id;
      },
      unregisterMenuCommand: (id) => request("unregisterMenuCommand", { details: { id } }, scriptId).catch(() => {}),
      log: (...args) => request("log", { details: { args } }, scriptId).catch(() => console.log(...args)),
      setClipboard: (text) => navigator.clipboard?.writeText
        ? navigator.clipboard.writeText(String(text || ""))
        : Promise.reject(new Error("clipboard unavailable")),
      xmlhttpRequest: (details) => {
        const xhrId = Math.random().toString(36).slice(2);
        let aborted = false;
        const fire = (name, payload) => {
          try {
            const fn = details && details[`on${name}`];
            if (typeof fn === "function") fn(payload);
          } catch (error) {
            console.error("[EazyFill GM_xmlhttpRequest callback]", error);
          }
        };
        const safe = {
          method: details?.method || "GET",
          url: details?.url || "",
          headers: details?.headers || {},
          data: details?.data ?? null,
          timeout: Number(details?.timeout || 0) || 0,
          responseType: details?.responseType || "",
          anonymous: !!details?.anonymous,
          xhrId
        };
        fire("loadstart", { readyState: 1, responseText: "", response: null });
        fire("readystatechange", { readyState: 1, responseText: "", response: null });
        request("xmlhttpRequest", { details: safe }, scriptId)
          .then((response) => {
            if (aborted || response.aborted) {
              fire("abort", { readyState: 4, error: response.error || "aborted" });
            } else if (response.timedOut) {
              fire("timeout", { readyState: 4, error: response.error || "timeout" });
            } else if (response.error) {
              fire("error", { readyState: 4, error: response.error });
            } else if (response.response) {
              fire("readystatechange", response.response);
              fire("progress", { ...response.response, lengthComputable: false, loaded: String(response.response.responseText || "").length, total: 0 });
              fire("load", response.response);
            }
            fire("loadend", response.response || { readyState: 4, error: response.error });
          })
          .catch((error) => {
            fire(aborted ? "abort" : "error", { readyState: 4, error: error.message });
            fire("loadend", { readyState: 4, error: error.message });
          });
        return {
          abort() {
            aborted = true;
            request("xmlhttpAbort", { details: { xhrId } }, scriptId).catch(() => {});
          }
        };
      }
    };
  };

  const globalApi = () => window.__createEazyFillGMApi("global");
  window.GM_addStyle = window.GM_addStyle || ((css) => globalApi().addStyle(css));
  window.GM_addElement = window.GM_addElement || ((parent, tag, attrs) => globalApi().addElement(parent, tag, attrs));
  window.GM_getValue = window.GM_getValue || ((key, fallback) => globalApi().getValue(key, fallback));
  window.GM_setValue = window.GM_setValue || ((key, value) => globalApi().setValue(key, value));
  window.GM_deleteValue = window.GM_deleteValue || ((key) => globalApi().deleteValue(key));
  window.GM_listValues = window.GM_listValues || (() => globalApi().listValues());
  window.GM_addValueChangeListener = window.GM_addValueChangeListener || ((key, fn) => globalApi().addValueChangeListener(key, fn));
  window.GM_removeValueChangeListener = window.GM_removeValueChangeListener || ((id) => globalApi().removeValueChangeListener(id));
  window.GM_xmlhttpRequest = window.GM_xmlhttpRequest || ((details) => globalApi().xmlhttpRequest(details));
  window.GM_notification = window.GM_notification || ((details) => globalApi().notification(details));
  window.GM_setClipboard = window.GM_setClipboard || ((text) => globalApi().setClipboard(text));
  window.GM_openInTab = window.GM_openInTab || ((url, opts) => globalApi().openInTab(url, opts));
  window.GM_download = window.GM_download || ((details, name) => globalApi().download(details, name));
  window.GM_registerMenuCommand = window.GM_registerMenuCommand || ((text, cb, opts) => globalApi().registerMenuCommand(text, cb, opts));
  window.GM_unregisterMenuCommand = window.GM_unregisterMenuCommand || ((id) => globalApi().unregisterMenuCommand(id));
  window.GM_log = window.GM_log || ((...args) => globalApi().log(...args));
  window.GM = window.GM || globalApi();
})();
