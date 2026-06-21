import React, { useCallback, useEffect, useMemo, useState } from "react";
import PropTypes from "prop-types";
import { Edit3, Loader2, Plus, Save, Tag, Trash2, X } from "lucide-react";
import { useThemeContext } from "../context/ThemeContext";
import {
  createAdminPlan,
  deleteAdminPlan,
  listAdminPlans,
  updateAdminPlan,
} from "../../api/billing";
import {
  DEFAULT_PLAN_ALLOWED_SERVICES,
  EAZYFILL_FEATURE_FLAGS,
  EAZYFILL_LIMIT_FIELDS,
  enabledFeatureLabels,
  limitSummary,
  normalizeAllowedServices,
} from "../featureCatalog";

function createDefaultForm() {
  return {
    code: "",
    name: "",
    description: "",
    monthly_limit: 1000,
    duration_days: 30,
    price_amount: 0,
    max_devices: 1,
    rate_limit_rpm: 60,
    rate_limit_burst: 10,
    show_in_checkout: true,
    is_promo: false,
    promo_audience: "both",
    allowed_services: { ...DEFAULT_PLAN_ALLOWED_SERVICES },
  };
}

function numberOr(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function normalizeForm(form) {
  return {
    ...form,
    monthly_limit: Math.max(0, Math.floor(numberOr(form.monthly_limit, 0))),
    duration_days: Math.max(1, Math.floor(numberOr(form.duration_days, 30))),
    price_amount: Math.max(0, Math.floor(numberOr(form.price_amount, 0))),
    max_devices: Math.max(1, Math.floor(numberOr(form.max_devices, 1))),
    rate_limit_rpm: Math.max(1, Math.floor(numberOr(form.rate_limit_rpm, 60))),
    rate_limit_burst: Math.max(1, Math.floor(numberOr(form.rate_limit_burst, 10))),
    show_in_checkout: !!form.show_in_checkout,
    is_promo: !!form.is_promo,
    promo_audience: form.promo_audience || "both",
    allowed_services: normalizeAllowedServices(form.allowed_services, { defaults: true }),
  };
}

function formFromPlan(plan) {
  return normalizeForm({
    code: plan.code || "",
    name: plan.name || "",
    description: plan.description || "",
    monthly_limit: plan.monthly_limit ?? 1000,
    duration_days: plan.duration_days ?? 30,
    price_amount: plan.price_amount ?? 0,
    max_devices: plan.max_devices ?? 1,
    rate_limit_rpm: plan.rate_limit_rpm ?? 60,
    rate_limit_burst: plan.rate_limit_burst ?? 10,
    show_in_checkout: plan.show_in_checkout !== false,
    is_promo: !!plan.is_promo,
    promo_audience: plan.promo_audience || "both",
    allowed_services: normalizeAllowedServices(plan.allowed_services, { defaults: false }),
  });
}

function promoAudienceLabel(audience) {
  return {
    new: "New users",
    registered: "Registered users",
    both: "Both",
  }[audience] || "Both";
}

function priceLabel(plan) {
  return `INR ${(Number(plan.price_amount || 0) / 100).toFixed(2)}`;
}

export function PlansPanel({ showToast }) {
  const {
    t_textHeading,
    t_textMuted,
    t_borderLight,
    glassPanel,
    glassInput,
    solidButton,
    iconBtn,
    isDark,
  } = useThemeContext();

  const [plans, setPlans] = useState([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState(createDefaultForm);
  const [formMode, setFormMode] = useState(null);
  const [editingPlanId, setEditingPlanId] = useState(null);
  const [deletePlanId, setDeletePlanId] = useState(null);
  const [deleteTargetPlanId, setDeleteTargetPlanId] = useState("");

  const activePlans = useMemo(() => plans.filter((plan) => plan.is_active), [plans]);

  const fetchPlans = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listAdminPlans();
      setPlans(Array.isArray(data.plans) ? data.plans : []);
    } catch (error) {
      showToast(error.message || "Failed to load plans", "error");
    } finally {
      setLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    fetchPlans();
  }, [fetchPlans]);

  const updateField = (key, value) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  const updateAllowedService = (key, value) => {
    setForm((current) => ({
      ...current,
      allowed_services: {
        ...(current.allowed_services || {}),
        [key]: value,
      },
    }));
  };

  const updateAllowedLimit = (key, value) => {
    const config = EAZYFILL_LIMIT_FIELDS.find((field) => field.key === key);
    const parsed = Math.max(config?.min ?? 0, Math.floor(numberOr(value, config?.fallback ?? 0)));
    updateAllowedService(key, parsed);
  };

  const openCreate = () => {
    setForm(createDefaultForm());
    setEditingPlanId(null);
    setFormMode("create");
  };

  const openEdit = (plan) => {
    setForm(formFromPlan(plan));
    setEditingPlanId(plan.id);
    setFormMode("edit");
  };

  const closeFormModal = () => {
    setFormMode(null);
    setEditingPlanId(null);
    setForm(createDefaultForm());
  };

  const savePlan = async (event) => {
    event.preventDefault();
    setSaving(true);
    try {
      const payload = normalizeForm(form);
      if (editingPlanId) {
        await updateAdminPlan(editingPlanId, payload);
        showToast("Plan updated");
      } else {
        await createAdminPlan(payload);
        showToast("Plan created");
      }
      closeFormModal();
      await fetchPlans();
    } catch (error) {
      showToast(error.message || "Failed to save plan", "error");
    } finally {
      setSaving(false);
    }
  };

  const openDeleteModal = (planId) => {
    const fallbackTarget = activePlans.find((plan) => plan.id !== planId);
    setDeletePlanId(planId);
    setDeleteTargetPlanId(fallbackTarget ? String(fallbackTarget.id) : "");
  };

  const closeDeleteModal = () => {
    setDeletePlanId(null);
    setDeleteTargetPlanId("");
  };

  const handleDelete = async () => {
    if (!deletePlanId) return;
    setSaving(true);
    try {
      const result = await deleteAdminPlan(deletePlanId, deleteTargetPlanId || null);
      const moved = Number(result?.migrated_count || 0);
      const removedSubscriptions = Number(result?.deleted_subscription_count || 0);
      if (moved > 0) {
        showToast(`Plan deleted. Migrated ${moved} linked subscription(s).`);
      } else if (removedSubscriptions > 0) {
        showToast(`Plan deleted. Removed ${removedSubscriptions} old subscription record(s).`);
      } else {
        showToast("Plan deleted");
      }
      closeDeleteModal();
      await fetchPlans();
    } catch (error) {
      showToast(error.message || "Failed to delete plan", "error");
    } finally {
      setSaving(false);
    }
  };

  const handleActiveToggle = async (plan, nextActive) => {
    setSaving(true);
    try {
      await updateAdminPlan(plan.id, { is_active: nextActive });
      showToast(nextActive ? "Plan enabled" : "Plan disabled");
      await fetchPlans();
    } catch (error) {
      showToast(error.message || "Failed to update plan status", "error");
    } finally {
      setSaving(false);
    }
  };

  const handleCheckoutVisibilityToggle = async (plan, nextVisible) => {
    setSaving(true);
    try {
      await updateAdminPlan(plan.id, { show_in_checkout: nextVisible });
      showToast(nextVisible ? "Plan visible in checkout" : "Plan hidden from checkout");
      await fetchPlans();
    } catch (error) {
      showToast(error.message || "Failed to update checkout visibility", "error");
    } finally {
      setSaving(false);
    }
  };

  const activeSwitchClass = (active) => [
    "relative inline-flex h-6 w-11 items-center rounded-full border transition-colors disabled:opacity-50",
    active
      ? "bg-emerald-500/80 border-emerald-400/60"
      : isDark
        ? "bg-slate-800 border-slate-600"
        : "bg-slate-200 border-slate-300",
  ].join(" ");

  const switchKnobClass = (active) => [
    "inline-block h-4 w-4 rounded-full bg-white shadow-sm transition-transform",
    active ? "translate-x-5" : "translate-x-1",
  ].join(" ");

  const renderFeatureSummary = (plan) => {
    const labels = enabledFeatureLabels(plan.allowed_services);
    const limits = limitSummary(plan.allowed_services);
    return (
      <div className="min-w-[14rem] space-y-1">
        <div className={t_textHeading}>{labels.length ? labels.join(", ") : "No feature flags"}</div>
        <div className={`text-[11px] ${t_textMuted}`}>{limits.length ? limits.join(" / ") : "No limits configured"}</div>
      </div>
    );
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="rounded-lg bg-emerald-500/15 p-2 text-emerald-500">
            <Tag size={20} />
          </div>
          <div>
            <h2 className={`text-lg font-semibold ${t_textHeading}`}>Plans</h2>
            <p className={`text-xs ${t_textMuted}`}>{plans.length} product plans</p>
          </div>
        </div>
        <button type="button" onClick={openCreate} className={solidButton}>
          <Plus size={16} /> Add Plan
        </button>
      </div>

      <div className={`rounded-2xl overflow-hidden ${glassPanel}`}>
        {loading ? (
          <div className="flex items-center justify-center p-12">
            <Loader2 className="animate-spin text-indigo-500" size={32} />
          </div>
        ) : plans.length === 0 ? (
          <div className="p-12 text-center">
            <p className={t_textMuted}>No plans created yet</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1040px] text-sm">
              <thead>
                <tr className={`border-b ${t_borderLight}`}>
                  <th className={`p-3 text-left text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>Plan</th>
                  <th className={`p-3 text-left text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>Price</th>
                  <th className={`p-3 text-left text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>Credits</th>
                  <th className={`p-3 text-left text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>Devices</th>
                  <th className={`p-3 text-left text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>Rate</th>
                  <th className={`p-3 text-left text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>Features</th>
                  <th className={`p-3 text-left text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>Promo</th>
                  <th className={`p-3 text-left text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>Checkout</th>
                  <th className={`p-3 text-left text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>Active</th>
                  <th className={`p-3 text-right text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {plans.map((plan) => (
                  <tr key={plan.id} className={`border-b ${t_borderLight} ${isDark ? "hover:bg-white/[0.02]" : "hover:bg-black/[0.02]"}`}>
                    <td className="p-3">
                      <div className={`font-medium ${t_textHeading}`}>{plan.name}</div>
                      <div className={`font-mono text-[11px] ${t_textMuted}`}>{plan.code}</div>
                    </td>
                    <td className="p-3 font-medium text-emerald-400">{priceLabel(plan)}</td>
                    <td className={`p-3 ${t_textHeading}`}>
                      <div>{Number(plan.monthly_limit || 0).toLocaleString()} / month</div>
                      <div className={`text-[11px] ${t_textMuted}`}>{Number(plan.duration_days || 0)} days</div>
                    </td>
                    <td className={`p-3 ${t_textHeading}`}>{Number(plan.max_devices || 1)}</td>
                    <td className={`p-3 ${t_textHeading}`}>
                      <div>{Number(plan.rate_limit_rpm || 60)} rpm</div>
                      <div className={`text-[11px] ${t_textMuted}`}>Burst {Number(plan.rate_limit_burst || 10)}</div>
                    </td>
                    <td className={`p-3 ${t_textMuted}`}>{renderFeatureSummary(plan)}</td>
                    <td className="p-3">
                      {plan.is_promo ? (
                        <div className="space-y-1">
                          <span className="inline-flex items-center rounded-full bg-amber-500/15 px-2 py-0.5 text-xs font-medium text-amber-500">
                            Promo
                          </span>
                          <div className={`text-xs ${t_textMuted}`}>{promoAudienceLabel(plan.promo_audience)}</div>
                        </div>
                      ) : (
                        <span className={`text-xs ${t_textMuted}`}>Standard</span>
                      )}
                    </td>
                    <td className="p-3">
                      <div className={`inline-flex items-center gap-2 text-xs ${t_textMuted}`}>
                        <button
                          type="button"
                          role="switch"
                          aria-checked={!!plan.show_in_checkout}
                          disabled={saving || !plan.is_active}
                          onClick={() => handleCheckoutVisibilityToggle(plan, !plan.show_in_checkout)}
                          className={activeSwitchClass(!!plan.show_in_checkout)}
                          title={plan.show_in_checkout ? "Hide from customer checkout" : "Show in customer checkout"}
                        >
                          <span className={switchKnobClass(!!plan.show_in_checkout)} />
                        </button>
                        <span>{plan.show_in_checkout ? "Shown" : "Hidden"}</span>
                      </div>
                    </td>
                    <td className="p-3">
                      <div className={`inline-flex items-center gap-2 text-xs ${t_textMuted}`}>
                        <button
                          type="button"
                          role="switch"
                          aria-checked={!!plan.is_active}
                          disabled={saving}
                          onClick={() => handleActiveToggle(plan, !plan.is_active)}
                          className={activeSwitchClass(!!plan.is_active)}
                          title={plan.is_active ? "Disable plan" : "Enable plan"}
                        >
                          <span className={switchKnobClass(!!plan.is_active)} />
                        </button>
                        <span className={`rounded-full px-2 py-0.5 font-medium ${plan.is_active ? "bg-emerald-500/20 text-emerald-400" : "bg-slate-500/20 text-slate-400"}`}>
                          {plan.is_active ? "Active" : "Inactive"}
                        </span>
                      </div>
                    </td>
                    <td className="p-3">
                      <div className="flex items-center justify-end gap-1">
                        <button type="button" onClick={() => openEdit(plan)} className={iconBtn("edit")} title="Edit">
                          <Edit3 size={14} />
                        </button>
                        <button type="button" onClick={() => openDeleteModal(plan.id)} className={iconBtn("danger")} title="Delete plan" disabled={saving}>
                          <Trash2 size={14} className="text-rose-400" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {formMode && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-3 backdrop-blur-sm" onClick={closeFormModal}>
          <div className={`${glassPanel} max-h-[92vh] w-full max-w-3xl overflow-y-auto rounded-2xl border p-6 ${t_borderLight}`} onClick={(event) => event.stopPropagation()}>
            <div className="mb-5 flex items-start justify-between gap-4">
              <div>
                <h3 className={`text-lg font-semibold ${t_textHeading}`}>{formMode === "edit" ? "Edit Plan" : "Create Plan"}</h3>
                <p className={`text-xs ${t_textMuted}`}>Plans control credits, extension feature flags, limits, sync access, and checkout visibility.</p>
              </div>
              <button type="button" onClick={closeFormModal} className={iconBtn("ghost")} title="Close">
                <X size={16} />
              </button>
            </div>

            <form onSubmit={savePlan} className="space-y-5">
              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <Field label="Code" muted={t_textMuted}>
                  <input className={glassInput} value={form.code} onChange={(event) => updateField("code", event.target.value)} placeholder="basic_monthly" required />
                </Field>
                <Field label="Name" muted={t_textMuted}>
                  <input className={glassInput} value={form.name} onChange={(event) => updateField("name", event.target.value)} placeholder="Basic Monthly" required />
                </Field>
              </div>

              <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                <Field label="Price (paise)" muted={t_textMuted}>
                  <input className={glassInput} type="number" min="0" value={form.price_amount} onChange={(event) => updateField("price_amount", event.target.value)} />
                </Field>
                <Field label="Solve credits / month" muted={t_textMuted}>
                  <input className={glassInput} type="number" min="0" value={form.monthly_limit} onChange={(event) => updateField("monthly_limit", event.target.value)} />
                </Field>
                <Field label="Duration days" muted={t_textMuted}>
                  <input className={glassInput} type="number" min="1" value={form.duration_days} onChange={(event) => updateField("duration_days", event.target.value)} />
                </Field>
              </div>

              <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                <Field label="Max devices" muted={t_textMuted}>
                  <input className={glassInput} type="number" min="1" max="10" value={form.max_devices} onChange={(event) => updateField("max_devices", event.target.value)} />
                </Field>
                <Field label="Rate limit rpm" muted={t_textMuted}>
                  <input className={glassInput} type="number" min="1" max="1000" value={form.rate_limit_rpm} onChange={(event) => updateField("rate_limit_rpm", event.target.value)} />
                </Field>
                <Field label="Burst" muted={t_textMuted}>
                  <input className={glassInput} type="number" min="1" max="1000" value={form.rate_limit_burst} onChange={(event) => updateField("rate_limit_burst", event.target.value)} />
                </Field>
              </div>

              <section className={`rounded-xl border p-4 ${t_borderLight}`}>
                <div className="mb-3">
                  <h4 className={`text-sm font-semibold ${t_textHeading}`}>Feature Entitlements</h4>
                  <p className={`text-xs ${t_textMuted}`}>These values are returned to the extension from the backend plan catalog.</p>
                </div>
                <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {EAZYFILL_FEATURE_FLAGS.map((feature) => (
                    <label key={feature.key} className={`flex items-center justify-between gap-3 rounded-lg border px-3 py-2 text-sm ${t_borderLight}`}>
                      <span>
                        <span className={`block font-medium ${t_textHeading}`}>{feature.label}</span>
                        <span className={`block text-[11px] ${t_textMuted}`}>{feature.description}</span>
                      </span>
                      <input
                        type="checkbox"
                        checked={!!(form.allowed_services || {})[feature.key]}
                        onChange={(event) => updateAllowedService(feature.key, event.target.checked)}
                      />
                    </label>
                  ))}
                </div>
              </section>

              <section className={`rounded-xl border p-4 ${t_borderLight}`}>
                <h4 className={`mb-3 text-sm font-semibold ${t_textHeading}`}>Extension Limits & Costs</h4>
                <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
                  {EAZYFILL_LIMIT_FIELDS.map((limit) => (
                    <Field key={limit.key} label={limit.label} muted={t_textMuted}>
                      <input
                        className={glassInput}
                        type="number"
                        min={limit.min}
                        value={(form.allowed_services || {})[limit.key] ?? limit.fallback}
                        onChange={(event) => updateAllowedLimit(limit.key, event.target.value)}
                      />
                    </Field>
                  ))}
                </div>
              </section>

              <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
                <label className={`flex items-center justify-between gap-3 rounded-xl border p-3 text-sm ${t_textHeading} ${t_borderLight}`}>
                  <span>
                    <span className="block font-semibold">Show in customer checkout</span>
                    <span className={`block text-[11px] ${t_textMuted}`}>Controls plan visibility for self-serve purchase flows.</span>
                  </span>
                  <input type="checkbox" checked={!!form.show_in_checkout} onChange={(event) => updateField("show_in_checkout", event.target.checked)} />
                </label>
                <label className={`flex items-center justify-between gap-3 rounded-xl border p-3 text-sm ${t_textHeading} ${t_borderLight}`}>
                  <span>
                    <span className="block font-semibold">Promo plan</span>
                    <span className={`block text-[11px] ${t_textMuted}`}>One-use promotional purchase option.</span>
                  </span>
                  <input type="checkbox" checked={!!form.is_promo} onChange={(event) => updateField("is_promo", event.target.checked)} />
                </label>
              </div>

              <Field label="Promo audience" muted={t_textMuted}>
                <select className={glassInput} value={form.promo_audience || "both"} disabled={!form.is_promo} onChange={(event) => updateField("promo_audience", event.target.value)}>
                  <option value="new">Only new users</option>
                  <option value="registered">Only registered users</option>
                  <option value="both">New and registered users</option>
                </select>
              </Field>

              <Field label="Description" muted={t_textMuted}>
                <textarea className={glassInput} rows={3} value={form.description} onChange={(event) => updateField("description", event.target.value)} />
              </Field>

              <div className="flex flex-wrap gap-2 pt-1">
                <button type="submit" className={solidButton} disabled={saving}>
                  {saving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
                  {formMode === "edit" ? "Save Plan" : "Create Plan"}
                </button>
                <button type="button" onClick={closeFormModal} className={`inline-flex items-center gap-2 rounded-xl border px-4 py-2 text-sm ${t_textMuted} ${t_borderLight}`}>
                  <X size={16} /> Cancel
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {deletePlanId && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-3 backdrop-blur-sm" onClick={closeDeleteModal}>
          <div className={`${glassPanel} w-full max-w-md rounded-2xl border p-6 ${t_borderLight}`} onClick={(event) => event.stopPropagation()}>
            <h3 className={`mb-3 text-lg font-semibold ${t_textHeading}`}>Delete Plan</h3>
            <p className={`mb-4 text-sm ${t_textMuted}`}>Move linked subscriptions to another active plan before deleting.</p>
            <Field label="Target plan" muted={t_textMuted}>
              <select className={glassInput} value={deleteTargetPlanId} onChange={(event) => setDeleteTargetPlanId(event.target.value)}>
                <option value="">No target plan</option>
                {activePlans
                  .filter((plan) => plan.id !== deletePlanId)
                  .map((plan) => (
                    <option key={plan.id} value={String(plan.id)}>
                      {plan.name} ({plan.code})
                    </option>
                  ))}
              </select>
            </Field>
            <div className="flex gap-2 pt-4">
              <button type="button" onClick={handleDelete} className={solidButton} disabled={saving}>
                {saving ? <Loader2 size={16} className="animate-spin" /> : <Trash2 size={16} />}
                Delete
              </button>
              <button type="button" onClick={closeDeleteModal} className={`rounded-xl border px-4 py-2 text-sm ${t_textMuted} ${t_borderLight}`}>
                Cancel
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, muted, children }) {
  return (
    <label className="block space-y-1">
      <span className={`block text-xs font-semibold uppercase tracking-wide ${muted}`}>{label}</span>
      {children}
    </label>
  );
}

Field.propTypes = {
  label: PropTypes.string.isRequired,
  muted: PropTypes.string.isRequired,
  children: PropTypes.node.isRequired,
};

PlansPanel.propTypes = {
  showToast: PropTypes.func.isRequired,
};
