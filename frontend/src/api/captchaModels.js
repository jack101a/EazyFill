import { adminApi, apiGet, apiPostForm, apiPostJson } from "./client";

export const captchaModelQueryKeys = {
  root: ["captcha-models"],
};

export function fetchCaptchaModels() {
  return apiGet(adminApi("/captcha/models"));
}

export function fetchCaptchaSamples({ status = "all", domain = "", limit = 60 } = {}) {
  const params = new URLSearchParams({
    status: status || "all",
    limit: String(limit || 60),
  });
  if (domain) params.set("domain", domain);
  return apiGet(adminApi(`/captcha/samples?${params}`));
}

export function fetchCaptchaProposals(status = "pending") {
  return apiGet(adminApi(`/captcha/proposals?status=${encodeURIComponent(status)}`));
}

export function uploadCaptchaModel({ file, ai_model_name, version, notes }) {
  const body = new FormData();
  body.append("file", file);
  body.append("ai_model_name", ai_model_name);
  body.append("version", version || "v1");
  body.append("task_type", "image");
  body.append("runtime", "onnx");
  if (notes) body.append("notes", notes);
  return apiPostForm(adminApi("/captcha/models/upload"), body, { timeoutMs: 120_000 });
}

export function setCaptchaMapping(payload) {
  return apiPostJson(adminApi("/captcha/mappings"), payload);
}

export function bulkUpdateCaptchaMappingModel(payload) {
  return apiPostJson(adminApi("/captcha/mappings/bulk-model"), payload);
}

export function approveCaptchaProposal(proposalId, modelId = "", verifySample = false) {
  const payload = { verify_sample: !!verifySample };
  if (modelId !== "" && modelId !== null && modelId !== undefined) payload.model_id = Number(modelId);
  return apiPostJson(adminApi(`/captcha/proposals/${Number(proposalId)}/approve`), payload);
}

export function rejectCaptchaProposal(proposalId) {
  return apiPostJson(adminApi(`/captcha/proposals/${Number(proposalId)}/reject`), {});
}
