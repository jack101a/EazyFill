(function () {
  "use strict";

  if (window.EazyFillAutofillEngine) return;

  const DEFAULT_SETTINGS = {
    skipHidden: true,
    skipLocked: true,
    skipPassword: true,
    maxRetries: 3,
    retryIntervalMs: 180,
    delayMs: 100,
    waitTimeoutMs: 3000
  };

  function runtimeRuleLimit(runtime = {}) {
    if (runtime.features && runtime.features.autofill === false) return 0;
    const raw = runtime.limits ? runtime.limits.rules : undefined;
    if (raw === undefined || raw === null || raw === "") return Infinity;
    const value = Number(raw);
    return Number.isFinite(value) ? Math.max(0, Math.floor(value)) : Infinity;
  }

  function applyRuleRuntimeLimit(rules, runtime = {}) {
    const limit = runtimeRuleLimit(runtime);
    if (!Number.isFinite(limit)) return rules;
    return rules.slice(0, limit);
  }

  let running = false;
  let pageKey = "";
  let autoRunTimer = null;
  let lastAutoRunAt = 0;
  let mutationObserver = null;
  const stepCursors = new Map();
  const completedStepKeys = new Set();

  function sendMessage(message) {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage(message, (response) => {
        if (chrome.runtime.lastError) {
          resolve({ ok: false, error: chrome.runtime.lastError.message });
          return;
        }
        resolve(response || { ok: false, error: "No response" });
      });
    });
  }

  function normalizedHost(value = location.hostname) {
    return String(value || "").replace(/^www\./, "").toLowerCase();
  }

  function currentPageKey() {
    return `${location.origin}${location.pathname}${location.search}`;
  }

  function resetPageStateIfNeeded() {
    const key = currentPageKey();
    if (pageKey === key) return;
    pageKey = key;
    completedStepKeys.clear();
    stepCursors.clear();
  }

  function wildcardToRegex(pattern) {
    const escaped = String(pattern || "")
      .replace(/[|\\{}()[\]^$+?.]/g, "\\$&")
      .replace(/\*/g, ".*");
    return new RegExp(`^${escaped}$`, "i");
  }

  function stripProtocol(value) {
    return String(value || "").trim().replace(/^https?:\/\//i, "").replace(/^www\./i, "");
  }

  function stripDomain(value) {
    const raw = String(value || "").trim();
    if (!raw || raw === "*") return "*";
    try {
      return normalizedHost(new URL(raw.includes("://") ? raw : `https://${raw}`).hostname);
    } catch (_) {
      return normalizedHost(raw.split("/")[0]);
    }
  }

  function domainMatches(pattern) {
    const clean = stripDomain(pattern);
    const host = normalizedHost();
    if (!clean || clean === "*") return true;
    return host === clean || host.endsWith(`.${clean}`) || wildcardToRegex(clean).test(host);
  }

  function pathMatches(pattern) {
    const clean = String(pattern || "").trim();
    if (!clean || clean === "*") return true;
    return wildcardToRegex(clean).test(location.pathname || "/");
  }

  function urlPatternMatches(pattern) {
    const clean = String(pattern || "").trim();
    if (!clean || clean === "*") return true;
    return wildcardToRegex(clean).test(location.href);
  }

  function normalizeMatchMode(value) {
    const mode = String(value || "domain").replace(/_/g, "").toLowerCase();
    if (mode === "domainpath") return "domainPath";
    if (mode === "fullurl" || mode === "exacturl") return "fullUrl";
    if (mode === "urlprefix") return "url_prefix";
    if (mode === "urlpattern") return "url_pattern";
    if (mode === "regex") return "regex";
    if (mode === "path") return "path";
    return "domain";
  }

  function normalizeSite(rule = {}) {
    const site = rule.site || {};
    return {
      matchMode: normalizeMatchMode(site.matchMode || site.match_mode || rule.matchMode || rule.match_mode),
      pattern: site.pattern || site.domain || rule.domain || rule.host || "*",
      path: site.path || rule.path || ""
    };
  }

  function ruleMatches(rawRule) {
    const rule = normalizeRule(rawRule);
    if (!rule || rule.enabled === false) return false;
    const site = rule.site;
    const pattern = site.pattern || "*";
    if (site.matchMode === "url_prefix") return location.href.startsWith(String(pattern || ""));
    if (site.matchMode === "url_pattern") return urlPatternMatches(pattern);
    if (site.matchMode === "regex") {
      try {
        return new RegExp(String(pattern)).test(location.href);
      } catch (_) {
        return false;
      }
    }
    if (site.matchMode === "fullUrl") {
      const exact = String(pattern || "");
      return exact.includes("*") ? urlPatternMatches(exact) : location.href === exact;
    }
    if (site.matchMode === "path") return pathMatches(pattern);
    if (site.matchMode === "domainPath") {
      const clean = stripProtocol(pattern);
      const current = `${normalizedHost()}${location.pathname || "/"}`;
      if (clean.includes("*")) return wildcardToRegex(clean).test(current);
      return current === clean || current.startsWith(`${clean.replace(/\/$/, "")}/`);
    }
    return domainMatches(pattern) && pathMatches(site.path);
  }

  function num(...values) {
    for (const value of values) {
      if (value !== undefined && value !== null && value !== "") return Number(value);
    }
    return 0;
  }

  function optionalNum(...values) {
    for (const value of values) {
      if (value !== undefined && value !== null && value !== "") return Number(value);
    }
    return undefined;
  }

  function boolValue(value, fallback = false) {
    if (value === undefined || value === null) return fallback;
    if (typeof value === "boolean") return value;
    return ["1", "true", "yes", "on"].includes(String(value).toLowerCase());
  }

  function normalizeAction(action) {
    const raw = String(action || "set_value").toLowerCase();
    if (["text", "type", "fill", "input"].includes(raw)) return "set_value";
    if (["checkbox"].includes(raw)) return "checkbox";
    if (["radio"].includes(raw)) return "radio";
    if (["check", "uncheck", "select", "click", "wait", "set_value"].includes(raw)) return raw;
    return "set_value";
  }

  function firstNonEmpty(...values) {
    for (const value of values) {
      if (value !== undefined && value !== null && value !== "") return value;
    }
    return "";
  }

  function selectorFromStep(step = {}) {
    const direct = firstNonEmpty(
      step.selector,
      step.target,
      step.targetSelector,
      step.target_selector,
      step.selectorCss,
      step.selector_css,
      step.cssSelector,
      step.css_selector,
      step.css,
      step.primary
    );
    if (direct) return direct;
    const xpath = firstNonEmpty(step.xpath, step.x_path);
    if (xpath) return { strategy: "xpath", primary: xpath, xpath };
    const id = firstNonEmpty(step.elementId, step.element_id, step.inputId, step.input_id, step.id);
    if (id) return { strategy: "id", primary: `#${id}`, id, element_id: id };
    const name = firstNonEmpty(step.inputName, step.input_name, step.nameAttr, step.name_attr, step.selectorName, step.selector_name, step.name);
    if (name) return { strategy: "name", primary: `[name="${name}"]`, name };
    return "";
  }

  function valueFromStep(step = {}) {
    return step.value
      ?? step.text
      ?? step.fill
      ?? step.defaultValue
      ?? step.default_value
      ?? "";
  }

  function normalizeStep(step = {}, index = 0) {
    const runtime = step.runtime || {};
    return {
      ...step,
      order: Number(step.order || index + 1),
      action: normalizeAction(step.action || step.type),
      selector: selectorFromStep(step),
      value: valueFromStep(step),
      fieldKey: step.fieldKey || step.field_key || step.key || step.name || "",
      label: step.label || step.title || step.name || step.fieldKey || step.field_key || "",
      required: step.required !== false && runtime.required !== false,
      runtime: {
        ...runtime,
        delayMs: optionalNum(runtime.delayMs, runtime.delay_ms, step.delayMs, step.delay_ms),
        timeoutMs: optionalNum(runtime.timeoutMs, runtime.timeout_ms, step.timeoutMs, step.timeout_ms),
        verifyAfterFill: runtime.verifyAfterFill ?? runtime.verify_after_fill ?? step.verifyAfterFill ?? step.verify_after_fill
      }
    };
  }

  function ruleStepSource(rule = {}) {
    if (Array.isArray(rule.steps) && rule.steps.length) return rule.steps;
    if (Array.isArray(rule.actions) && rule.actions.length) return rule.actions;
    if (Array.isArray(rule.fields) && rule.fields.length) return rule.fields;
    return [];
  }

  function normalizeSteps(rule) {
    const steps = ruleStepSource(rule);
    if (steps.length) {
      return steps.map(normalizeStep).sort((a, b) => (a.order || 0) - (b.order || 0));
    }
    const selector = selectorFromStep(rule);
    if (selector) {
      return [normalizeStep({
        order: 1,
        action: rule.action || rule.type || "set_value",
        selector,
        value: valueFromStep(rule),
        fieldKey: rule.fieldKey || rule.name || "",
        label: rule.name || "Field",
        required: false
      }, 0)];
    }
    return [];
  }

  function normalizeExecution(rule = {}) {
    const execution = rule.execution || {};
    const ruleType = String(rule.ruleType || rule.rule_type || execution.mode || "instant").toLowerCase() === "flow" ? "flow" : "instant";
    return {
      ...execution,
      mode: ruleType,
      delayMs: num(execution.delayMs, execution.delay_ms, rule.delayMs, rule.delay_ms, DEFAULT_SETTINGS.delayMs),
      waitTimeoutMs: num(execution.waitTimeoutMs, execution.wait_timeout_ms, rule.waitTimeoutMs, rule.wait_timeout_ms, DEFAULT_SETTINGS.waitTimeoutMs),
      runOnce: boolValue(execution.runOnce ?? execution.run_once, true),
      stopOnError: boolValue(execution.stopOnError ?? execution.stop_on_error, ruleType === "flow")
    };
  }

  function normalizeRule(rule = {}) {
    const execution = normalizeExecution(rule);
    return {
      ...rule,
      id: rule.id || rule.local_rule_id || rule.server_rule_id || rule.name || "",
      enabled: rule.enabled !== false,
      ruleType: execution.mode,
      priority: Number(rule.priority ?? 100),
      site: normalizeSite(rule),
      execution,
      profileId: rule.profileId || rule.profile_id || (typeof rule.profile_scope === "string" ? rule.profile_scope : "default"),
      profileIds: Array.isArray(rule.profileIds)
        ? rule.profileIds
        : Array.isArray(rule.profile_ids)
          ? rule.profile_ids
          : [rule.profileId || rule.profile_id || (typeof rule.profile_scope === "string" ? rule.profile_scope : "default")],
      steps: normalizeSteps(rule)
    };
  }

  function isStepMode(mode) {
    return mode === "step_by_step" || mode === "step";
  }

  function pageRunKey(rule) {
    return `${currentPageKey()}::${rule.id || rule.name || "rule"}`;
  }

  function profileValues(profiles, profileId) {
    const list = Array.isArray(profiles) ? profiles : [];
    const profile = list.find((item) => String(item.id) === String(profileId))
      || list.find((item) => item.id === "default")
      || list[0]
      || {};
    return profile.values || profile.data || profile.fields || {};
  }

  function activeProfileId(settings = {}) {
    return String(settings.activeProfileId || "default").trim() || "default";
  }

  function ruleMatchesActiveProfile(rule, settings = {}) {
    const ids = Array.isArray(rule.profileIds) ? rule.profileIds : [rule.profileId || "default"];
    return ids.map((id) => String(id || "default")).includes(activeProfileId(settings));
  }

  function resolveValue(step, values) {
    const raw = step.value ?? "";
    if (typeof raw !== "string") return raw;
    return raw
      .replace(/\{\{\s*([a-zA-Z0-9_.-]+)\s*\}\}/g, (_match, key) => values[key] ?? "")
      .replace(/\{@\s*([a-zA-Z0-9_.-]+)\s*\}/g, (_match, key) => values[key] ?? "")
      .replace(/\{([a-zA-Z0-9_.-]+)\}/g, (_match, key) => values[key] ?? _match);
  }

  function findTargets(selector) {
    const builder = window.EazyFillSelectorBuilder;
    if (builder?.findBySelector) return builder.findBySelector(selector).filter((item) => item instanceof HTMLElement);
    try {
      const raw = typeof selector === "string" ? selector : selector?.primary || selector?.css;
      return raw ? Array.from(document.querySelectorAll(raw)) : [];
    } catch (_) {
      return [];
    }
  }

  function isElementVisible(element) {
    return window.EazyFillSelectorBuilder?.isElementVisible
      ? window.EazyFillSelectorBuilder.isElementVisible(element)
      : !!element?.offsetParent;
  }

  function isElementLocked(element) {
    return !!(element?.disabled || element?.readOnly || element?.getAttribute?.("aria-disabled") === "true");
  }

  function sleep(ms) {
    return new Promise((resolve) => setTimeout(resolve, Math.max(0, Number(ms || 0))));
  }

  function selectUsableTarget(targets, settings) {
    return targets.find((target) => {
      if (settings.skipHidden !== false && !isElementVisible(target)) return false;
      if (settings.skipLocked !== false && isElementLocked(target)) return false;
      return true;
    }) || targets[0] || null;
  }

  function radioForValue(element, value) {
    if (!(element instanceof HTMLInputElement) || element.type !== "radio" || !element.name) return element;
    const escapedName = window.EazyFillSelectorBuilder?.cssEscape?.(element.name) || element.name.replace(/"/g, '\\"');
    const group = Array.from(document.querySelectorAll(`input[type="radio"][name="${escapedName}"]`));
    return group.find((item) => String(item.value || "on") === String(value || "on")) || element;
  }

  async function waitForTarget(step, timeoutMs, settings) {
    const started = Date.now();
    const timeout = Math.max(0, Number(timeoutMs || 0));
    do {
      const targets = findTargets(step.selector);
      const target = selectUsableTarget(targets, settings);
      if (target) return { ok: true, element: target, matches: targets.length };
      await sleep(80);
    } while (Date.now() - started < timeout);
    return { ok: false, element: null, matches: 0 };
  }

  function dispatchEvent(element, type, options = {}) {
    element.dispatchEvent(new Event(type, { bubbles: true, cancelable: true, ...options }));
  }

  function dispatchPointerSequence(element) {
    ["pointerdown", "mousedown", "mouseup", "pointerup"].forEach((type) => dispatchEvent(element, type));
  }

  function dispatchInputEvents(element) {
    dispatchEvent(element, "input");
    dispatchEvent(element, "change");
  }

  function setNativeValue(element, value) {
    const text = String(value ?? "");
    const descriptor = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element), "value");
    if (descriptor?.set) descriptor.set.call(element, text);
    else element.value = text;
    dispatchInputEvents(element);
  }

  function setChecked(element, checked) {
    const desired = !!checked;
    if (element.checked !== desired) {
      dispatchPointerSequence(element);
      element.click();
    }
    if (element.checked !== desired) {
      const descriptor = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(element), "checked");
      if (descriptor?.set) descriptor.set.call(element, desired);
      else element.checked = desired;
    }
    dispatchInputEvents(element);
  }

  function setSelectValue(element, value) {
    const text = String(value ?? "").trim();
    const lower = text.toLowerCase();
    const option = Array.from(element.options || []).find((item) => (
      item.value === text
      || item.text.trim() === text
      || (lower.length >= 3 && item.text.trim().toLowerCase().includes(lower))
    ));
    setNativeValue(element, option ? option.value : text);
  }

  function performClick(element) {
    if (typeof element.focus === "function") element.focus();
    dispatchPointerSequence(element);
    element.click();
  }

  async function performAction(element, step, value) {
    const action = normalizeAction(step.action);
    if (action === "wait") {
      await sleep(value || step.runtime?.delayMs || DEFAULT_SETTINGS.delayMs);
      return;
    }
    if (typeof element.focus === "function") {
      element.focus();
      dispatchEvent(element, "focus");
    }
    if (action === "click") {
      performClick(element);
    } else if (action === "check") {
      setChecked(element, true);
    } else if (action === "uncheck") {
      setChecked(element, false);
    } else if (action === "checkbox") {
      setChecked(element, boolValue(value, true));
    } else if (action === "radio") {
      const radio = radioForValue(element, value);
      setChecked(radio, true);
    } else if (action === "select" && element instanceof HTMLSelectElement) {
      setSelectValue(element, value);
    } else if (element instanceof HTMLSelectElement) {
      setSelectValue(element, value);
    } else if (element instanceof HTMLInputElement && element.type === "checkbox") {
      setChecked(element, boolValue(value, true));
    } else if (element instanceof HTMLInputElement && element.type === "radio") {
      setChecked(radioForValue(element, value), true);
    } else if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) {
      setNativeValue(element, value);
    } else {
      element.textContent = String(value ?? "");
      dispatchInputEvents(element);
    }
  }

  function verifyStepValue(element, step, expected) {
    const action = normalizeAction(step.action);
    if (action === "click" || action === "wait") return true;
    if (action === "check") return !!element.checked;
    if (action === "uncheck") return !element.checked;
    if (action === "checkbox") return !!element.checked === boolValue(expected, true);
    if (action === "radio") {
      const radio = radioForValue(element, expected);
      return !!radio.checked;
    }
    if (element instanceof HTMLSelectElement) {
      const selected = element.options[element.selectedIndex];
      const target = String(expected ?? "").trim().toLowerCase();
      return String(element.value || "").trim().toLowerCase() === target
        || String(selected?.text || "").trim().toLowerCase() === target
        || (target.length >= 3 && String(selected?.text || "").trim().toLowerCase().includes(target));
    }
    if (element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement) {
      return String(element.value ?? "") === String(expected ?? "");
    }
    return true;
  }

  function stepKey(rule, step) {
    const selector = step.selector || {};
    return [
      pageRunKey(rule),
      step.order || "",
      step.fieldKey || step.field_key || "",
      step.action || "",
      String(step.value ?? ""),
      selector.strategy || "",
      selector.primary || "",
      selector.id || "",
      selector.element_id || "",
      selector.name || "",
      selector.css || "",
      selector.xpath || ""
    ].join("|");
  }

  async function executeStep(rule, step, context) {
    const key = stepKey(rule, step);
    if (rule.execution.runOnce !== false && completedStepKeys.has(key)) {
      return { ok: true, skipped: true, completed: true, action: step.action, label: step.label || "" };
    }

    const action = normalizeAction(step.action);
    const value = resolveValue(step, context.profileValues);
    if (action === "wait") {
      await sleep(value || step.runtime?.delayMs || context.delayMs);
      completedStepKeys.add(key);
      return { ok: true, action: "wait", label: step.label || "" };
    }

    const timeoutMs = num(step.runtime?.timeoutMs, step.runtime?.timeout_ms, context.waitTimeoutMs);
    const resolved = await waitForTarget(step, timeoutMs, context.settings);
    if (!resolved.ok || !resolved.element) {
      return {
        ok: false,
        skipped: !step.required,
        action,
        error: "Element not found",
        selector: step.selector,
        label: step.label || ""
      };
    }

    const element = resolved.element;
    if (context.settings.skipPassword !== false && element instanceof HTMLInputElement && element.type === "password") {
      return { ok: true, skipped: true, action, label: step.label || "", error: "Password field skipped" };
    }

    try {
      await performAction(element, step, value);
      const shouldVerify = step.runtime?.verifyAfterFill !== false && step.runtime?.verify_after_fill !== false;
      if (shouldVerify && !verifyStepValue(element, step, value)) {
        return {
          ok: false,
          skipped: !step.required,
          action,
          error: "Verification failed",
          selector: step.selector,
          label: step.label || ""
        };
      }
      completedStepKeys.add(key);
      return {
        ok: true,
        action,
        selector: step.selector,
        label: step.label || ""
      };
    } catch (error) {
      return {
        ok: false,
        skipped: !step.required,
        action,
        error: error.message || String(error),
        selector: step.selector,
        label: step.label || ""
      };
    }
  }

  async function executeRule(rule, options, profiles, settings) {
    const mode = options.mode || rule.execution.mode || "instant";
    const steps = rule.steps;
    const stepMode = isStepMode(mode);
    const cursorKey = pageRunKey(rule);
    const startIndex = stepMode ? Math.min(Number(stepCursors.get(cursorKey) || 0), Math.max(steps.length - 1, 0)) : 0;
    const limit = stepMode ? Math.min(startIndex + 1, steps.length) : steps.length;
    const context = {
      delayMs: rule.execution.delayMs,
      waitTimeoutMs: rule.execution.waitTimeoutMs,
      profileValues: profileValues(profiles, activeProfileId(settings)),
      settings
    };
    const results = [];

    for (const step of steps.slice(startIndex, limit)) {
      let result = null;
      const maxRetries = Math.max(1, Number(settings.maxRetries || DEFAULT_SETTINGS.maxRetries));
      for (let attempt = 0; attempt < maxRetries; attempt += 1) {
        result = await executeStep(rule, step, context);
        if (result.ok || result.skipped) break;
        if (attempt < maxRetries - 1) await sleep(settings.retryIntervalMs || DEFAULT_SETTINGS.retryIntervalMs);
      }
      results.push(result);
      if (!result.ok && !result.skipped && rule.execution.stopOnError === true) break;
      const delayMs = num(step.runtime?.delayMs, step.runtime?.delay_ms, context.delayMs);
      if (delayMs) await sleep(Math.min(Math.max(delayMs, 0), 5000));
    }

    const hardFailed = results.some((item) => !item.ok && !item.skipped);
    const advanced = results.length > 0 && !(hardFailed && rule.execution.stopOnError === true);
    const nextStepIndex = stepMode && advanced ? startIndex + results.length : startIndex;
    const completed = stepMode && (steps.length === 0 || nextStepIndex >= steps.length);
    if (stepMode) {
      if (completed) stepCursors.delete(cursorKey);
      else stepCursors.set(cursorKey, nextStepIndex);
    }

    return {
      id: rule.id,
      name: rule.name || "Untitled Rule",
      mode,
      matchedSteps: steps.length,
      executedSteps: results.length,
      currentStep: stepMode && steps.length ? startIndex + 1 : null,
      nextStep: stepMode && !completed ? nextStepIndex + 1 : null,
      completed,
      succeeded: results.filter((item) => item.ok && !item.skipped).length,
      skipped: results.filter((item) => item.skipped).length,
      failed: results.filter((item) => !item.ok && !item.skipped).length,
      results
    };
  }

  async function loadState() {
    const response = await sendMessage({
      type: "GET_EXTENSION_STORAGE",
      keys: ["fp_settings", "fp_rules", "fp_profiles"]
    });
    if (!response.ok) throw new Error(response.error || "Storage read failed");
    return response.data || {};
  }

  async function loadRuntimeLimits() {
    const response = await sendMessage({ type: "GET_RUNTIME_PLAN_LIMITS" });
    return response.ok ? response : { limits: { rules: null }, features: { autofill: true } };
  }

  async function executeMatchingRules(options = {}) {
    if (running) return { ok: false, error: "Autofill is already running" };
    if (window.EazyFillExcludedHosts?.isExcludedHost()) return { ok: false, error: "This site is excluded" };

    running = true;
    try {
      resetPageStateIfNeeded();
      const data = await loadState();
      const settings = { ...DEFAULT_SETTINGS, ...(data.fp_settings?.autofill || {}), ...(data.fp_settings || {}) };
      if (settings.extensionEnabled === false) return { ok: false, error: "Extension is turned off" };
      if (settings.autofillEnabled === false) return { ok: false, error: "Autofill is disabled" };

      const rules = (Array.isArray(data.fp_rules) ? data.fp_rules : []).map(normalizeRule);
      const matching = rules
        .filter(ruleMatches)
        .filter((rule) => options.ruleId ? true : ruleMatchesActiveProfile(rule, settings))
        .sort((a, b) => (b.priority || 100) - (a.priority || 100));
      const planAllowed = applyRuleRuntimeLimit(matching, await loadRuntimeLimits());
      const selected = options.ruleId ? planAllowed.filter((rule) => String(rule.id) === String(options.ruleId)) : planAllowed;
      if (!selected.length) {
        return {
          ok: true,
          matchedRules: matching.length,
          executedRules: 0,
          planLimitedRules: Math.max(0, matching.length - planAllowed.length),
          results: []
        };
      }

      const results = [];
      const rulesToRun = isStepMode(options.mode) ? selected.slice(0, 1) : selected;
      for (const rule of rulesToRun) {
        results.push(await executeRule(rule, options, data.fp_profiles || [], settings));
      }
      return {
        ok: true,
        matchedRules: matching.length,
        executedRules: results.length,
        planLimitedRules: Math.max(0, matching.length - planAllowed.length),
        succeededSteps: results.reduce((sum, item) => sum + item.succeeded, 0),
        failedSteps: results.reduce((sum, item) => sum + item.failed, 0),
        skippedSteps: results.reduce((sum, item) => sum + item.skipped, 0),
        results
      };
    } finally {
      running = false;
    }
  }

  function reportAutomaticRun(result, reason) {
    if (!result?.ok || !Number(result.succeededSteps || 0)) return;
    sendMessage({
      type: "AUTOFILL_AUTO_EXECUTED",
      succeededSteps: Number(result.succeededSteps || 0),
      matchedRules: Number(result.matchedRules || 0),
      executedRules: Number(result.executedRules || 0),
      reason,
      url: location.href
    }).catch(() => {});
  }

  async function runAutomaticAutofill(reason = "auto") {
    if (document.visibilityState === "hidden") return;
    lastAutoRunAt = Date.now();
    try {
      const result = await executeMatchingRules({ automatic: true });
      reportAutomaticRun(result, reason);
    } catch (_) {
      // Automatic runs should never disturb the page.
    }
  }

  function scheduleAutomaticAutofill(reason = "auto") {
    if (autoRunTimer) return;
    const elapsed = Date.now() - lastAutoRunAt;
    const delayMs = Math.max(350, Math.min(1200, 1200 - elapsed));
    autoRunTimer = setTimeout(() => {
      autoRunTimer = null;
      runAutomaticAutofill(reason);
    }, delayMs);
  }

  function patchHistoryMethod(name) {
    const original = history[name];
    if (typeof original !== "function" || original.__eazyfillPatched) return;
    const patched = function (...args) {
      const result = original.apply(this, args);
      scheduleAutomaticAutofill("navigation");
      return result;
    };
    patched.__eazyfillPatched = true;
    history[name] = patched;
  }

  function startAutomaticAutofill() {
    scheduleAutomaticAutofill("page-load");
    window.addEventListener("pageshow", () => scheduleAutomaticAutofill("pageshow"), { passive: true });
    window.addEventListener("popstate", () => scheduleAutomaticAutofill("navigation"), { passive: true });
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "visible") scheduleAutomaticAutofill("visible");
    }, { passive: true });
    patchHistoryMethod("pushState");
    patchHistoryMethod("replaceState");

    if (!mutationObserver && document.documentElement) {
      mutationObserver = new MutationObserver((mutations) => {
        if (mutations.some((mutation) => mutation.addedNodes?.length || mutation.type === "attributes")) {
          scheduleAutomaticAutofill("dom-change");
        }
      });
      mutationObserver.observe(document.documentElement, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ["disabled", "hidden", "aria-hidden"]
      });
    }
  }

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message?.type !== "AUTOFILL_EXECUTE_NOW") return false;
    executeMatchingRules(message)
      .then(sendResponse)
      .catch((error) => sendResponse({ ok: false, error: error.message || String(error) }));
    return true;
  });

  startAutomaticAutofill();

  window.EazyFillAutofillEngine = {
    executeMatchingRules,
    normalizeRule,
    ruleMatches
  };
})();
