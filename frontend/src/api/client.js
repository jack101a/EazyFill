const DEFAULT_TIMEOUT_MS = 20_000;
const ADMIN_API_PREFIX = "/admin/api";

export class ApiError extends Error {
  constructor(message, status, data, requestId = "") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
    this.requestId = requestId;
  }
}

export function adminApi(path = "") {
  const value = String(path || "");
  if (!value) return ADMIN_API_PREFIX;
  if (value.startsWith(ADMIN_API_PREFIX)) return value;
  return `${ADMIN_API_PREFIX}${value.startsWith("/") ? value : `/${value}`}`;
}

async function parseResponse(response) {
  if (response.status === 204) return null;
  const text = await response.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return { message: text };
  }
}

function errorMessage(response, data, requestId) {
  let message = data?.message || data?.detail || data?.error || `Request failed (${response.status})`;
  if (typeof message === "object") {
    message = message.message || message.error || JSON.stringify(message);
  }
  if (response.status === 401) message = "Admin session expired. Please sign in again.";
  if (response.status === 403 && message === "admin_csrf_required") {
    message = "Admin session safety check failed. Refresh the page and try again.";
  }
  return requestId ? `${message} (request ${requestId})` : message;
}

export async function apiRequest(url, options = {}) {
  const {
    headers = {},
    timeoutMs = DEFAULT_TIMEOUT_MS,
    signal: externalSignal,
    ...requestOptions
  } = options;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);
  const abortExternal = () => controller.abort();
  externalSignal?.addEventListener("abort", abortExternal, { once: true });

  try {
    const response = await fetch(url, {
      credentials: "include",
      ...requestOptions,
      headers: {
        Accept: "application/json",
        "X-Admin-API": "1",
        ...headers,
      },
      signal: controller.signal,
    });
    const data = await parseResponse(response);
    if (!response.ok) {
      const requestId = response.headers.get("x-request-id") || response.headers.get("x-correlation-id") || "";
      throw new ApiError(errorMessage(response, data, requestId), response.status, data, requestId);
    }
    return data;
  } catch (error) {
    if (error?.name === "AbortError") {
      throw new ApiError(`Request timed out after ${timeoutMs}ms`, 0, null);
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
    externalSignal?.removeEventListener("abort", abortExternal);
  }
}

export function apiGet(url, options = {}) {
  return apiRequest(url, { ...options, method: "GET" });
}

export function apiPost(url, body = {}, options = {}) {
  const formData = new FormData();
  Object.entries(body).forEach(([key, value]) => {
    if (value !== undefined && value !== null) formData.append(key, value);
  });
  return apiRequest(url, { ...options, method: "POST", body: formData });
}

export function apiPostForm(url, formData, options = {}) {
  return apiRequest(url, { ...options, method: "POST", body: formData });
}

function jsonRequest(method, url, body = {}, options = {}) {
  return apiRequest(url, {
    ...options,
    method,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    body: JSON.stringify(body),
  });
}

export function apiPostJson(url, body = {}, options = {}) {
  return jsonRequest("POST", url, body, options);
}

export function apiPatchJson(url, body = {}, options = {}) {
  return jsonRequest("PATCH", url, body, options);
}

export function apiPutJson(url, body = {}, options = {}) {
  return jsonRequest("PUT", url, body, options);
}

export function apiDelete(url, options = {}) {
  return apiRequest(url, { ...options, method: "DELETE" });
}
