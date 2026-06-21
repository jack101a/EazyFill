import { adminApi, apiGet, apiPostForm, apiPostJson } from "./client";

export const captchaModelQueryKeys = {
  root: ["captcha-models"],
};

export function fetchCaptchaModels() {
  return apiGet(adminApi("/captcha/models"));
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

export function approveCaptchaProposal(proposalId, modelId) {
  return apiPostJson(adminApi(`/captcha/proposals/${Number(proposalId)}/approve`), { model_id: Number(modelId) });
}

export function rejectCaptchaProposal(proposalId) {
  return apiPostJson(adminApi(`/captcha/proposals/${Number(proposalId)}/reject`), {});
}
