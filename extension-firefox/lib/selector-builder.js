// Shared selector helpers for EazyFill content modules.
(function () {
  "use strict";

  if (window.EazyFillSelectorBuilder) return;

  function cssEscape(value) {
    if (window.CSS && typeof CSS.escape === "function") return CSS.escape(String(value));
    return String(value).replace(/[^a-zA-Z0-9_-]/g, (char) => `\\${char}`);
  }

  function uniqueElements(items) {
    const seen = new Set();
    return (items || []).filter((element) => {
      if (!element || seen.has(element)) return false;
      seen.add(element);
      return true;
    });
  }

  function walkOpenRoots(root, visitor) {
    if (!root) return;
    visitor(root);
    const nodes = root.querySelectorAll ? Array.from(root.querySelectorAll("*")) : [];
    for (const node of nodes) {
      if (node.shadowRoot) walkOpenRoots(node.shadowRoot, visitor);
    }
  }

  function queryCssDeep(selector, root = document) {
    if (!selector) return [];
    const found = [];
    try {
      walkOpenRoots(root, (openRoot) => {
        try {
          found.push(...Array.from(openRoot.querySelectorAll(selector)));
        } catch (_) {
          // Invalid selectors simply do not match.
        }
      });
    } catch (_) {
      return [];
    }
    return uniqueElements(found);
  }

  function queryByIdDeep(id, root = document) {
    if (!id) return [];
    return queryCssDeep(`#${cssEscape(id)}`, root);
  }

  function queryByNameDeep(name, root = document) {
    if (!name) return [];
    return queryCssDeep(`[name="${cssEscape(name)}"]`, root);
  }

  function queryXPath(xpath, root = document) {
    if (!xpath) return [];
    try {
      const result = document.evaluate(xpath, root, null, XPathResult.ORDERED_NODE_SNAPSHOT_TYPE, null);
      const out = [];
      for (let i = 0; i < result.snapshotLength; i += 1) out.push(result.snapshotItem(i));
      return uniqueElements(out);
    } catch (_) {
      return [];
    }
  }

  function isElementVisible(element) {
    if (!element || !(element instanceof Element)) return false;
    const style = window.getComputedStyle(element);
    if (style.display === "none" || style.visibility === "hidden" || Number(style.opacity) === 0) return false;
    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function buildXPath(element) {
    const parts = [];
    let node = element;
    while (node && node.nodeType === Node.ELEMENT_NODE && node !== document.documentElement) {
      const tag = node.tagName.toLowerCase();
      let index = 1;
      let sibling = node.previousElementSibling;
      while (sibling) {
        if (sibling.tagName.toLowerCase() === tag) index += 1;
        sibling = sibling.previousElementSibling;
      }
      parts.unshift(`${tag}[${index}]`);
      node = node.parentElement;
    }
    return `/html/${parts.join("/")}`;
  }

  function buildCssPath(element) {
    const pathParts = [];
    let node = element;
    while (node && node.nodeType === Node.ELEMENT_NODE && node !== document.body) {
      let nth = 1;
      let sibling = node.previousElementSibling;
      while (sibling) {
        nth += 1;
        sibling = sibling.previousElementSibling;
      }
      pathParts.unshift(`${node.tagName.toLowerCase()}:nth-child(${nth})`);
      node = node.parentElement;
    }
    return pathParts.join(" > ");
  }

  function getElementLabel(element) {
    if (!element) return "";
    const labels = [];
    if (element.id) {
      const label = document.querySelector(`label[for="${cssEscape(element.id)}"]`);
      if (label?.innerText) labels.push(label.innerText.trim());
    }
    const wrappingLabel = element.closest?.("label");
    if (wrappingLabel?.innerText) labels.push(wrappingLabel.innerText.trim());
    const attrs = ["aria-label", "placeholder", "title", "alt"];
    attrs.forEach((attr) => {
      const value = element.getAttribute(attr);
      if (value) labels.push(value.trim());
    });
    return labels.find(Boolean) || "";
  }

  function selectorQueryTarget(candidate) {
    if (!candidate) return "";
    if (candidate.strategy === "xpath") return candidate.xpath || candidate.primary || "";
    return candidate.css || candidate.primary || "";
  }

  function queryCandidate(candidate) {
    if (!candidate) return [];
    if (candidate.id || candidate.element_id) return queryByIdDeep(candidate.id || candidate.element_id);
    if (candidate.name) return queryByNameDeep(candidate.name);
    if (candidate.strategy === "xpath" || candidate.primary === "xpath") return queryXPath(candidate.xpath || candidate.primary);
    const target = selectorQueryTarget(candidate);
    if (!target) return [];
    if (String(target).startsWith("/")) return queryXPath(target);
    return queryCssDeep(target);
  }

  function scoreCandidate(candidate, baseScore) {
    const found = queryCandidate(candidate);
    const matches = found.length;
    const visibleMatches = found.filter(isElementVisible).length;
    let confidence = baseScore;
    if (matches === 1) confidence += 10;
    else if (matches > 1) confidence -= Math.min(35, matches * 5);
    if (visibleMatches === 1) confidence += 5;
    if (matches === 0) confidence = 0;
    return {
      ...candidate,
      matches,
      visibleMatches,
      visible_matches: visibleMatches,
      confidence: Math.max(0, Math.min(100, confidence))
    };
  }

  function buildSelector(element) {
    if (!element || !(element instanceof Element)) {
      return { strategy: "css", primary: "", fallback: "", confidence: 0, label: "" };
    }

    const tag = element.tagName.toLowerCase();
    const candidates = [];

    if (element.id && !/^\d/.test(element.id)) {
      candidates.push({
        strategy: "id",
        primary: `#${cssEscape(element.id)}`,
        css: `#${cssEscape(element.id)}`,
        id: element.id,
        element_id: element.id,
        fallback: "",
        baseScore: 90
      });
    }
    if (element.name) {
      candidates.push({
        strategy: "name",
        primary: `${tag}[name="${cssEscape(element.name)}"]`,
        css: `${tag}[name="${cssEscape(element.name)}"]`,
        name: element.name,
        fallback: "",
        baseScore: 78
      });
    }

    ["data-testid", "data-name", "data-qa", "data-cy", "data-id"].forEach((attr) => {
      const value = element.getAttribute(attr);
      if (value) {
        candidates.push({
          strategy: "css",
          primary: `${tag}[${attr}="${cssEscape(value)}"]`,
          css: `${tag}[${attr}="${cssEscape(value)}"]`,
          fallback: "",
          baseScore: 82
        });
      }
    });

    ["aria-label", "placeholder", "title"].forEach((attr) => {
      const value = element.getAttribute(attr);
      if (value) {
        candidates.push({
          strategy: "css",
          primary: `${tag}[${attr}="${cssEscape(value)}"]`,
          css: `${tag}[${attr}="${cssEscape(value)}"]`,
          fallback: "",
          baseScore: attr === "aria-label" ? 72 : 66
        });
      }
    });

    if (element.className && typeof element.className === "string") {
      const classes = element.className.trim().split(/\s+/).slice(0, 3).map((className) => `.${cssEscape(className)}`).join("");
      if (classes) {
        candidates.push({ strategy: "css", primary: `${tag}${classes}`, css: `${tag}${classes}`, fallback: "", baseScore: 62 });
      }
    }

    const cssPath = buildCssPath(element);
    const xpath = buildXPath(element);
    if (cssPath) candidates.push({ strategy: "css", primary: cssPath, css: cssPath, xpath, fallback: xpath, baseScore: 45 });
    if (xpath) candidates.push({ strategy: "xpath", primary: xpath, xpath, fallback: cssPath, baseScore: 42 });

    const scored = candidates.map((candidate) => scoreCandidate(candidate, candidate.baseScore));
    scored.sort((a, b) => b.confidence - a.confidence);
    const best = scored[0] || { strategy: "xpath", primary: xpath, xpath, fallback: "", confidence: 35 };
    return {
      strategy: best.strategy,
      primary: best.primary,
      css: best.css || (best.strategy !== "xpath" ? best.primary : ""),
      xpath: best.xpath || xpath || "",
      id: best.id || "",
      element_id: best.element_id || best.id || "",
      name: best.name || "",
      fallback: best.fallback || "",
      confidence: best.confidence,
      matches: best.matches || 0,
      visibleMatches: best.visibleMatches || 0,
      visible_matches: best.visibleMatches || 0,
      label: getElementLabel(element),
      candidates: scored
        .filter((candidate) => candidate !== best)
        .map(({ baseScore, ...candidate }) => candidate)
    };
  }

  function findBySelector(selector) {
    if (!selector) return [];
    if (typeof selector === "string") {
      return selector.startsWith("/") ? queryXPath(selector) : queryCssDeep(selector);
    }

    const attempts = [];
    const addAttempt = (candidate) => {
      if (!candidate) return;
      attempts.push(candidate);
    };

    addAttempt(selector);
    if (selector.primary === "id" && (selector.id || selector.element_id)) {
      addAttempt({ strategy: "id", id: selector.id || selector.element_id });
    } else if (selector.primary === "name" && selector.name) {
      addAttempt({ strategy: "name", name: selector.name });
    } else if (selector.primary === "css" && selector.css) {
      addAttempt({ strategy: "css", primary: selector.css, css: selector.css });
    } else if (selector.primary === "xpath" && selector.xpath) {
      addAttempt({ strategy: "xpath", primary: selector.xpath, xpath: selector.xpath });
    }

    if (selector.fallback) {
      addAttempt(String(selector.fallback).startsWith("/")
        ? { strategy: "xpath", primary: selector.fallback, xpath: selector.fallback }
        : { strategy: "css", primary: selector.fallback, css: selector.fallback });
    }
    if (Array.isArray(selector.candidates)) selector.candidates.forEach(addAttempt);

    for (const attempt of attempts) {
      let found = [];
      if (attempt.strategy === "id" && !(attempt.id || attempt.element_id)) {
        found = queryByIdDeep(String(attempt.primary || "").replace(/^#/, ""));
      } else if (attempt.strategy === "name" && !(attempt.name)) {
        const match = String(attempt.primary || "").match(/\[name="([^"]+)"\]/);
        found = match ? queryByNameDeep(match[1]) : queryCandidate(attempt);
      } else {
        found = queryCandidate(attempt);
      }
      if (found.length) {
        return found.sort((a, b) => Number(isElementVisible(b)) - Number(isElementVisible(a)));
      }
    }

    return [];
  }

  window.EazyFillSelectorBuilder = {
    buildSelector,
    buildCssPath,
    buildXPath,
    cssEscape,
    findBySelector,
    getElementLabel,
    isElementVisible,
    queryByIdDeep,
    queryByNameDeep,
    queryCssDeep,
    queryXPath
  };
})();
