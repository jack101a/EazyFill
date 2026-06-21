import { getExtensionStorage } from "./protected-storage.js";

const DEFAULT_API_BASE = "https://eazyfill.app";
const DEFAULT_TIMEOUT_MS = 15000;

function trimBaseUrl(value) {
  return String(value || DEFAULT_API_BASE).replace(/\/+$/, "");
}

function joinUrl(baseUrl, path) {
  const cleanPath = String(path || "").startsWith("/") ? path : `/${path || ""}`;
  return `${trimBaseUrl(baseUrl)}${cleanPath}`;
}

async function getDeviceId() {
  const data = await chrome.storage.local.get(["fp_device_id"]);
  if (data.fp_device_id) return data.fp_device_id;
  const deviceId = crypto.randomUUID ? crypto.randomUUID() : `device_${Date.now()}_${Math.random().toString(36).slice(2)}`;
  await chrome.storage.local.set({ fp_device_id: deviceId });
  return deviceId;
}

async function readClientContext() {
  const data = await getExtensionStorage(["fp_auth", "fp_settings"]);
  return {
    apiKey: String(data.fp_auth?.apiKey || "").trim(),
    sessionToken: String(data.fp_auth?.sessionToken || data.fp_auth?.session_token || "").trim(),
    baseUrl: trimBaseUrl(data.fp_settings?.apiBaseUrl || DEFAULT_API_BASE),
    deviceId: await getDeviceId()
  };
}

async function parseResponse(response) {
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) return response.json();
  const text = await response.text();
  return text ? { message: text } : {};
}

export function createApiClient(options = {}) {
  const defaultBaseUrl = trimBaseUrl(options.baseUrl || DEFAULT_API_BASE);

  async function request(path, requestOptions = {}) {
    const context = await readClientContext();
    const baseUrl = requestOptions.baseUrl ? trimBaseUrl(requestOptions.baseUrl) : (context.baseUrl || defaultBaseUrl);
    const url = joinUrl(baseUrl, path);
    const timeoutMs = Number(requestOptions.timeoutMs || DEFAULT_TIMEOUT_MS);
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

    const headers = {
      "Content-Type": "application/json",
      "X-EazyFill-Device-Id": context.deviceId,
      ...(requestOptions.headers || {})
    };
    if (requestOptions.skipAuth !== true) {
      if (context.sessionToken) headers["X-EazyFill-Session"] = context.sessionToken;
      else if (context.apiKey) headers["X-Api-Key"] = context.apiKey;
    }

    try {
      const response = await fetch(url, {
        method: requestOptions.method || "GET",
        headers,
        body: requestOptions.body === undefined ? undefined : JSON.stringify(requestOptions.body),
        signal: controller.signal
      });
      const data = await parseResponse(response);
      if (!response.ok) {
        const detail = data?.detail && typeof data.detail === "object" ? data.detail : null;
        const error = new Error(data?.message || data?.error || detail?.message || detail?.error || `HTTP ${response.status}`);
        error.status = response.status;
        error.data = data;
        throw error;
      }
      return data;
    } catch (error) {
      if (requestOptions.retry !== false && (error.name === "AbortError" || error.status >= 500)) {
        return request(path, { ...requestOptions, retry: false });
      }
      if (!error.status) {
        error.message = `${error.message || "Network request failed"} (${requestOptions.method || "GET"} ${url})`;
      }
      throw error;
    } finally {
      clearTimeout(timeoutId);
    }
  }

  return {
    get: (path, optionsForRequest = {}) => request(path, { ...optionsForRequest, method: "GET" }),
    post: (path, body, optionsForRequest = {}) => request(path, { ...optionsForRequest, method: "POST", body }),
    put: (path, body, optionsForRequest = {}) => request(path, { ...optionsForRequest, method: "PUT", body }),
    delete: (path, optionsForRequest = {}) => request(path, { ...optionsForRequest, method: "DELETE" }),
    request
  };
}
