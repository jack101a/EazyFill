// EazyFill userscript URL matching helpers.
(function () {
  "use strict";

  if (window.UserscriptMatcher) return;

  function list(value) {
    return Array.isArray(value) ? value.filter(Boolean).map(String) : [];
  }

  function escapeRegex(value) {
    return String(value).replace(/[|\\{}()[\]^$+*?.]/g, "\\$&");
  }

  function globToRegex(glob, ignoreCase = true) {
    const source = `^${escapeRegex(glob).replace(/\\\*/g, ".*?")}$`;
    return new RegExp(source, ignoreCase ? "i" : "");
  }

  function normalizeUrlParts(url) {
    try {
      const parsed = new URL(url);
      return {
        scheme: parsed.protocol.slice(0, -1).toLowerCase(),
        host: parsed.hostname.toLowerCase(),
        path: parsed.pathname + parsed.search + parsed.hash
      };
    } catch (_) {
      return { scheme: "", host: "", path: "" };
    }
  }

  function matchHost(host, ruleHost) {
    const clean = String(ruleHost || "").toLowerCase();
    if (!clean || clean === "*") return true;
    if (clean.startsWith("*.")) {
      const base = clean.slice(2);
      return host === base || host.endsWith(`.${base}`);
    }
    if (clean.endsWith(".tld")) {
      const base = clean.slice(0, -4);
      return host === base || host.startsWith(`${base}.`);
    }
    return globToRegex(clean).test(host);
  }

  function matchPattern(url, pattern) {
    const rule = String(pattern || "").trim();
    if (!rule) return false;
    if (rule === "<all_urls>") return /^(https?|file|ftp):/i.test(url);

    const match = rule.match(/^(\*|https?|file|ftp):\/\/([^/]*)\/(.*)$/i);
    if (!match) return false;

    const [, rawScheme, rawHost, rawPath] = match;
    const parts = normalizeUrlParts(url);
    const scheme = rawScheme.toLowerCase();
    const schemeOk = scheme === "*"
      ? parts.scheme === "http" || parts.scheme === "https"
      : parts.scheme === scheme;
    if (!schemeOk) return false;
    if (scheme !== "file" && !matchHost(parts.host, rawHost)) return false;
    return globToRegex(`/${rawPath || "*"}`, false).test(parts.path || "/");
  }

  function includePattern(url, pattern) {
    const rule = String(pattern || "").trim();
    if (!rule) return false;
    if (rule.length > 1 && rule[0] === "/" && rule[rule.length - 1] === "/") {
      try {
        return new RegExp(rule.slice(1, -1), "i").test(url);
      } catch (error) {
        console.warn("[EazyFill Userscript Matcher] Bad include regex:", rule, error.message);
        return false;
      }
    }
    if (rule.includes(".tld/")) {
      return globToRegex(rule.replace(".tld/", ".*?/")).test(url);
    }
    return globToRegex(rule).test(url);
  }

  function ruleMatches(url, pattern) {
    return matchPattern(url, pattern) || includePattern(url, pattern);
  }

  function shouldRun(script, url, frameInfo) {
    if (!script || script.enabled === false) return false;
    const meta = script.parsedMeta || {};
    const isTop = frameInfo ? frameInfo.isTop !== false : window.top === window.self;
    if (meta.noframes && !isTop) return false;

    const matches = list(meta.matches);
    const includes = list(meta.includes);
    const excludes = list(meta.exclude);
    const excludeMatches = list(meta.excludeMatches || meta.excludeMatch);
    const hasPositiveRules = matches.length || includes.length;

    if (excludes.some((pattern) => includePattern(url, pattern))) return false;
    if (excludeMatches.some((pattern) => matchPattern(url, pattern))) return false;
    if (!hasPositiveRules) return false;
    return matches.some((pattern) => matchPattern(url, pattern))
      || includes.some((pattern) => includePattern(url, pattern));
  }

  window.UserscriptMatcher = {
    includePattern,
    matchPattern,
    ruleMatches,
    shouldRun,
    _test: { globToRegex, normalizeUrlParts }
  };
})();
