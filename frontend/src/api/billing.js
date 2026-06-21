import { adminApi, apiDelete, apiGet, apiPostJson, apiPutJson } from "./client";

export function listAdminPlans() {
  return apiGet(adminApi("/plans"));
}

export function createAdminPlan(payload) {
  return apiPostJson(adminApi("/plans"), payload);
}

export function updateAdminPlan(planId, payload) {
  return apiPutJson(adminApi(`/plans/${Number(planId)}`), payload);
}

export function deleteAdminPlan(planId, targetPlanId = null) {
  const body = targetPlanId ? { target_plan_id: Number(targetPlanId) } : {};
  return apiDelete(adminApi(`/plans/${Number(planId)}`), {
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function listPayments(filters = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  }
  return apiGet(`${adminApi("/payments")}?${params}`);
}

export function fetchPendingPaymentCount() {
  return apiGet(adminApi("/payments/pending-count"));
}

export function approvePayment(paymentId, manualOverrideReason, confirmManualOverride = true) {
  return apiPostJson(adminApi(`/payments/${Number(paymentId)}/approve`), {
    manual_override_reason: manualOverrideReason,
    confirm_manual_override: confirmManualOverride,
  });
}

export function rejectPayment(paymentId, rejectionReason) {
  return apiPostJson(adminApi(`/payments/${Number(paymentId)}/reject`), {
    rejection_reason: rejectionReason,
  });
}

export function createRazorpayOrder(userId, planId) {
  return apiPostJson(adminApi("/payments/razorpay/order"), {
    user_id: Number(userId),
    plan_id: Number(planId),
  });
}
