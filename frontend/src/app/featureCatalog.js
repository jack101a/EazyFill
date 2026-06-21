export const EAZYFILL_FEATURE_FLAGS = [
  {
    key: "captcha",
    label: "CAPTCHA solving",
    description: "Allow solve requests and credit usage.",
  },
  {
    key: "autofill",
    label: "Autofill rules",
    description: "Allow recorded and approved form rules.",
  },
  {
    key: "userscripts",
    label: "Userscripts",
    description: "Allow server-controlled and local scripts.",
  },
  {
    key: "sync",
    label: "Cloud sync",
    description: "Allow encrypted backup and restore.",
  },
  {
    key: "priority_solving",
    label: "Priority solving",
    description: "Prefer faster solve queues when available.",
  },
  {
    key: "unlimited_rules",
    label: "Unlimited rules",
    description: "Ignore normal autofill rule count limits.",
  },
  {
    key: "js_rules",
    label: "Advanced JS rules",
    description: "Allow advanced JavaScript-backed automation.",
  },
];

export const EAZYFILL_LIMIT_FIELDS = [
  { key: "captcha_solve_cost", label: "CAPTCHA solve cost", fallback: 1, min: 0 },
  { key: "rules_limit", label: "Rules limit", fallback: 50, min: 0 },
  { key: "scripts_limit", label: "Scripts limit", fallback: 20, min: 0 },
  { key: "script_storage_mb", label: "Script storage MB", fallback: 10, min: 0 },
];

export const EAZYFILL_CORE_SERVICE_KEYS = ["captcha", "autofill", "userscripts", "sync"];

export const DEFAULT_PLAN_ALLOWED_SERVICES = Object.freeze({
  captcha: true,
  autofill: true,
  userscripts: true,
  sync: true,
  priority_solving: false,
  unlimited_rules: false,
  js_rules: false,
  captcha_solve_cost: 1,
  rules_limit: 50,
  scripts_limit: 20,
  script_storage_mb: 10,
});

const BOOLEAN_FEATURE_KEYS = new Set(EAZYFILL_FEATURE_FLAGS.map((feature) => feature.key));
const LIMIT_FEATURE_KEYS = new Set(EAZYFILL_LIMIT_FIELDS.map((field) => field.key));

export function isKnownFeatureKey(key) {
  return BOOLEAN_FEATURE_KEYS.has(key) || LIMIT_FEATURE_KEYS.has(key);
}

export function isBooleanFeatureKey(key) {
  return BOOLEAN_FEATURE_KEYS.has(key);
}

export function featureLabel(key) {
  return EAZYFILL_FEATURE_FLAGS.find((feature) => feature.key === key)?.label || key;
}

export function normalizeAllowedServices(value, options = {}) {
  const source = value && typeof value === "object" ? value : {};
  const base = options.defaults ? { ...DEFAULT_PLAN_ALLOWED_SERVICES } : {};

  for (const feature of EAZYFILL_FEATURE_FLAGS) {
    if (Object.prototype.hasOwnProperty.call(source, feature.key)) {
      base[feature.key] = source[feature.key] === true;
    } else if (!Object.prototype.hasOwnProperty.call(base, feature.key)) {
      base[feature.key] = false;
    }
  }

  for (const limit of EAZYFILL_LIMIT_FIELDS) {
    const parsed = Number(source[limit.key]);
    base[limit.key] = Number.isFinite(parsed) ? Math.max(limit.min, Math.floor(parsed)) : (base[limit.key] ?? limit.fallback);
  }

  return base;
}

export function enabledFeatureLabels(value) {
  const source = value && typeof value === "object" ? value : {};
  return EAZYFILL_FEATURE_FLAGS
    .filter((feature) => source[feature.key] === true)
    .map((feature) => feature.label);
}

export function activeFeatureKeys(value) {
  const source = value && typeof value === "object" ? value : {};
  return EAZYFILL_FEATURE_FLAGS
    .filter((feature) => source[feature.key] === true)
    .map((feature) => feature.key);
}

export function limitSummary(value) {
  const normalized = normalizeAllowedServices(value, { defaults: false });
  return EAZYFILL_LIMIT_FIELDS.map((limit) => `${limit.label}: ${normalized[limit.key]}`);
}
