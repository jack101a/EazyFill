import { adminApi, apiDelete, apiGet, apiPostJson, apiPutJson } from "./client";

export function listUsers(filters = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  return apiGet(`${adminApi("/users")}?${params}`);
}

export function getUser(userId) {
  return apiGet(adminApi(`/users/${Number(userId)}`));
}

export function createUser(payload) {
  return apiPostJson(adminApi("/users"), payload);
}

export function updateUser(userId, payload) {
  return apiPutJson(adminApi(`/users/${Number(userId)}`), payload);
}

export function setUserStatus(userId, status) {
  return apiPostJson(adminApi(`/users/${Number(userId)}/status`), { status });
}

export function deleteUser(userId) {
  return apiDelete(adminApi(`/users/${Number(userId)}`));
}

export function changeUserPlan(userId, payload) {
  return apiPostJson(adminApi(`/users/${Number(userId)}/subscription/change-plan`), payload);
}

export function renewUserSubscription(userId, payload) {
  return apiPostJson(adminApi(`/users/${Number(userId)}/subscription/renew`), payload);
}

export function expireUserSubscription(userId) {
  return apiPostJson(adminApi(`/users/${Number(userId)}/subscription/expire`), {});
}

export function runUserKeyAction(userId, action) {
  return apiPostJson(adminApi(`/users/${Number(userId)}/key/${action}`), {});
}
