import { adminApi, apiGet } from "./client";

export function fetchExtensionErrorReports() {
  return apiGet(adminApi("/extension/error-reports"));
}
