import { adminApi, apiGet } from "./client";

export const eazyfillQueryKeys = {
  overview: ["eazyfill", "overview"],
  abuse: ["eazyfill", "abuse"],
  support: (userId) => ["eazyfill", "support", Number(userId)],
};

export function fetchEazyFillOverview() {
  return apiGet(adminApi("/eazyfill/overview"));
}

export function fetchEazyFillAbuse(limit = 50) {
  const params = new URLSearchParams({ limit: String(limit) });
  return apiGet(`${adminApi("/eazyfill/abuse")}?${params}`);
}

export function fetchEazyFillUserSupport(userId) {
  return apiGet(adminApi(`/eazyfill/users/${Number(userId)}/support`));
}
