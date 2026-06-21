import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import {
  DEFAULT_PLAN_ALLOWED_SERVICES,
  EAZYFILL_CORE_SERVICE_KEYS,
  EAZYFILL_FEATURE_FLAGS,
  EAZYFILL_LIMIT_FIELDS,
} from "../src/app/featureCatalog.js";

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const readSource = (path) => readFile(join(root, path), "utf8");

const [
  app,
  navigation,
  apiClient,
  overviewPage,
  operationsPage,
  plansPanel,
] = await Promise.all([
  readSource("src/app/App.jsx"),
  readSource("src/app/navigation.js"),
  readSource("src/api/eazyfill.js"),
  readSource("src/app/features/overview/EazyFillOverviewPage.jsx"),
  readSource("src/app/features/operations/OperationsPage.jsx"),
  readSource("src/app/components/PlansPanel.jsx"),
]);

for (const route of [
  "/dashboard",
  "/users",
  "/plans",
  "/payments",
  "/operations",
  "/extension-health",
  "/captcha-models",
]) {
  assert.ok(navigation.includes(`path: "${route}"`), `navigation should include ${route}`);
}

for (const route of [
  '<Route path="/dashboard" element={<EazyFillOverviewPage />} />',
  '<Route path="/operations" element={<OperationsPage />} />',
  '<Route path="/captcha-models" element={<CaptchaModelsPage showToast={context.showToast} />} />',
]) {
  assert.ok(app.includes(route), `app routes should include ${route}`);
}

for (const redirect of [
  '{ from: "/subscriptions", to: "/users" }',
  '{ from: "/models", to: "/captcha-models" }',
  '{ from: "/exam", to: "/dashboard" }',
]) {
  assert.ok(navigation.includes(redirect), `navigation should include compatibility redirect ${redirect}`);
}

assert.deepEqual(EAZYFILL_CORE_SERVICE_KEYS, ["captcha", "autofill", "userscripts", "sync"]);

for (const key of EAZYFILL_CORE_SERVICE_KEYS) {
  assert.equal(DEFAULT_PLAN_ALLOWED_SERVICES[key], true, `default plans should include ${key}`);
}

for (const key of ["solver", "exam", "stall"]) {
  assert.equal(DEFAULT_PLAN_ALLOWED_SERVICES[key], undefined, `default plan contract should not include legacy ${key}`);
}

for (const field of ["rules_limit", "scripts_limit", "script_storage_mb"]) {
  assert.ok(EAZYFILL_LIMIT_FIELDS.some((entry) => entry.key === field), `limit field ${field} should be defined`);
}

for (const feature of ["captcha", "autofill", "userscripts", "sync", "priority_solving", "unlimited_rules", "js_rules"]) {
  assert.ok(EAZYFILL_FEATURE_FLAGS.some((entry) => entry.key === feature), `feature ${feature} should be defined`);
}

assert.ok(apiClient.includes('adminApi("/eazyfill/overview")'), "overview client should use the EazyFill admin route");
assert.ok(apiClient.includes('adminApi("/eazyfill/abuse")'), "abuse client should use the EazyFill admin route");
assert.ok(apiClient.includes("eazyfillQueryKeys"), "API cache keys should use the EazyFill namespace");
assert.ok(overviewPage.includes("EazyFill Operations"), "overview page should use current product copy");
assert.ok(operationsPage.includes("fetchEazyFillAbuse"), "operations page should use the current API client");

assert.ok(plansPanel.includes("DEFAULT_PLAN_ALLOWED_SERVICES"), "plans panel should use the shared entitlement defaults");
assert.ok(plansPanel.includes("EAZYFILL_FEATURE_FLAGS"), "plans panel should render shared feature flags");
assert.ok(plansPanel.includes("Show in customer checkout"), "plans panel should use checkout-facing copy");
assert.ok(!plansPanel.includes('["captcha", "solver", "autofill", "exam"]'), "plans panel should not use legacy services");

console.log("EazyFill frontend contract checks passed.");
