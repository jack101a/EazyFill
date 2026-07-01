import React, { useState, useEffect, useCallback } from "react";
import PropTypes from "prop-types";
import {
  Ban,
  CalendarPlus,
  CheckCircle,
  ChevronLeft,
  ChevronRight,
  CreditCard,
  Edit3,
  Loader2,
  RefreshCw,
  Search,
  ShieldOff,
  Trash2,
  UserPlus,
  Users,
} from "lucide-react";
import { useThemeContext } from "../context/ThemeContext";
import { createRazorpayOrder, listAdminPlans } from "../../api/billing";
import {
  changeUserPlan,
  createUser,
  deleteUser,
  expireUserSubscription,
  getUser,
  listUsers,
  renewUserSubscription,
  setUserStatus,
  updateUser,
} from "../../api/users";
import { useConfirm } from "./ConfirmDialog";

const STATUS_COLORS = {
  active: "bg-emerald-500/20 text-emerald-400",
  blocked: "bg-red-500/20 text-red-400",
  inactive: "bg-slate-500/20 text-slate-400",
  expired: "bg-amber-500/20 text-amber-400",
  pending_payment: "bg-[#8B5CF6]/20 text-[#C4B5FD]",
  pending_approval: "bg-purple-500/20 text-purple-400",
  deleted: "bg-gray-500/20 text-gray-400",
};

const EMPTY_FORM = {
  full_name: "",
  email: "",
  mobile_number: "",
  status: "pending_payment",
  notes: "",
  plan_id: "",
  duration_days: "",
};

function errMessage(error, fallback) {
  return error?.data?.error || error?.message || fallback;
}

function formatDate(value) {
  return value ? new Date(value).toLocaleDateString() : "--";
}

function formatCount(value) {
  return Number(value || 0).toLocaleString();
}

function formatDateTime(value) {
  return value ? new Date(value).toLocaleString() : "--";
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / (1024 ** index)).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function usagePercent(used, limit) {
  const cap = Number(limit || 0);
  if (cap <= 0) return 0;
  return Math.min(100, Math.round((Number(used || 0) / cap) * 100));
}

function rowUsageText(user) {
  const used = user.plan_usage_used ?? user.quota_used ?? user.usage_used ?? 0;
  const limit = user.quota_limit ?? user.plan_monthly_limit ?? 0;
  return `${formatCount(used)}/${formatCount(limit)}`;
}

function rowActivityText(user) {
  const today = Number(user.today_credits_used || 0);
  const sessions = Number(user.active_session_count || 0);
  const devices = Number(user.active_device_count || 0);
  if (today || sessions || devices || user.last_activity_at) {
    return {
      primary: today ? `${formatCount(today)} credits today` : `${formatCount(sessions)} sessions`,
      secondary: `${formatCount(devices)} devices · Last ${formatDate(user.last_activity_at)}`,
    };
  }
  const fallback = Number(user.key_usage_count || user.request_usage_count || 0);
  if (fallback || user.key_last_used_at) {
    return {
      primary: `${formatCount(fallback)} requests`,
      secondary: `Last ${formatDate(user.key_last_used_at)}`,
    };
  }
  return null;
}

function planDuration(plans, planId) {
  const plan = plans.find((p) => String(p.id) === String(planId));
  return plan?.duration_days || 30;
}

function loadRazorpayCheckout() {
  if (window.Razorpay) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const existing = document.querySelector('script[src="https://checkout.razorpay.com/v1/checkout.js"]');
    if (existing) {
      existing.addEventListener("load", resolve, { once: true });
      existing.addEventListener("error", reject, { once: true });
      return;
    }
    const script = document.createElement("script");
    script.src = "https://checkout.razorpay.com/v1/checkout.js";
    script.async = true;
    script.onload = resolve;
    script.onerror = reject;
    document.body.appendChild(script);
  });
}

export function UsersPanel({ showToast }) {
  const { t_textHeading, t_textMuted, t_borderLight, glassPanel, glassInput, solidButton, iconBtn, glassButton, dangerButton, isDark } = useThemeContext();
  const confirm = useConfirm();
  const [users, setUsers] = useState([]);
  const [plans, setPlans] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [showCreate, setShowCreate] = useState(false);
  const [editingUser, setEditingUser] = useState(null);
  const [userDetails, setUserDetails] = useState(null);
  const [usageUser, setUsageUser] = useState(null);
  const [usageDetails, setUsageDetails] = useState(null);
  const [usageLoading, setUsageLoading] = useState(false);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [razorpayOrder, setRazorpayOrder] = useState(null);
  const limit = 20;

  const fetchUsers = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listUsers({
        offset: page * limit,
        limit,
        status: statusFilter,
        search,
      });
      setUsers(data.users || []);
      setTotal(data.total || 0);
    } catch (e) {
      showToast(errMessage(e, "Failed to load users"), "error");
    } finally {
      setLoading(false);
    }
  }, [page, statusFilter, search, showToast]);

  const fetchPlans = useCallback(async () => {
    try {
      const data = await listAdminPlans();
      setPlans((data.plans || []).filter((p) => p.is_active !== false));
    } catch {
      setPlans([]);
    }
  }, []);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);
  useEffect(() => { fetchPlans(); }, [fetchPlans]);

  const resetModal = () => {
    setShowCreate(false);
    setEditingUser(null);
    setUserDetails(null);
    setForm(EMPTY_FORM);
  };

  const closeUsage = () => {
    setUsageUser(null);
    setUsageDetails(null);
  };

  const openCreate = () => {
    setForm({ ...EMPTY_FORM, duration_days: plans[0]?.duration_days || "" });
    setShowCreate(true);
  };

  const openEdit = async (user) => {
    setEditingUser(user);
    setUserDetails(null);
    setDetailsLoading(true);
    setForm({
      ...EMPTY_FORM,
      full_name: user.full_name || "",
      email: user.email || "",
      mobile_number: user.mobile_number || "",
      status: user.status || "inactive",
      notes: user.notes || "",
    });
    try {
      const details = await getUser(user.id);
      setUserDetails(details);
      const activeSub = details.active_subscription || {};
      setForm((prev) => ({
        ...prev,
        plan_id: activeSub.plan_id ? String(activeSub.plan_id) : "",
        duration_days: activeSub.plan_duration_days || planDuration(plans, activeSub.plan_id),
      }));
    } catch (e) {
      showToast(errMessage(e, "Failed to load user details"), "error");
    } finally {
      setDetailsLoading(false);
    }
  };

  const createPayload = () => ({
    full_name: form.full_name,
    email: form.email || null,
    mobile_number: form.mobile_number || null,
    status: form.status,
    notes: form.notes,
    plan_id: form.plan_id ? Number(form.plan_id) : null,
    duration_days: form.duration_days ? Number(form.duration_days) : null,
    issue_api_key: false,
  });

  const handleCreate = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await createUser(createPayload());
      showToast("User created");
      resetModal();
      fetchUsers();
    } catch (e) {
      showToast(errMessage(e, "Failed to create user"), "error");
    } finally {
      setSaving(false);
    }
  };

  const handleUpdate = async (e) => {
    e.preventDefault();
    setSaving(true);
    try {
      await updateUser(editingUser.id, {
        full_name: form.full_name,
        email: form.email || null,
        mobile_number: form.mobile_number || null,
        status: form.status,
        notes: form.notes,
      });
      showToast("User updated");
      await openEdit({ ...editingUser, ...form });
      fetchUsers();
    } catch (e) {
      showToast(errMessage(e, "Failed to update user"), "error");
    } finally {
      setSaving(false);
    }
  };

  const handleStatusChange = async (userId, newStatus) => {
    try {
      await setUserStatus(userId, newStatus);
      showToast(`User ${newStatus}`);
      fetchUsers();
    } catch (e) {
      showToast(errMessage(e, "Failed to change status"), "error");
    }
  };

  const handleDelete = async (userId) => {
    const ok = await confirm({
      title: "Soft-delete user",
      message: "Soft-delete this user account?",
      details: [`User ID: ${userId}`, "The user record is retained for audit/history."],
      confirmLabel: "Delete User",
    });
    if (!ok) return;
    try {
      await deleteUser(userId);
      showToast("User deleted");
      fetchUsers();
    } catch (e) {
      showToast(errMessage(e, "Failed to delete"), "error");
    }
  };

  const handleSubscriptionAction = async (action) => {
    if (!editingUser) return;
    if ((action === "change-plan" || action === "renew") && !form.plan_id) {
      showToast("Select a plan first", "error");
      return;
    }
    if (action === "expire") {
      const ok = await confirm({
        title: "Expire subscription",
        message: "Expire this user's active subscription now?",
        details: ["The user will lose active plan access until renewed."],
        confirmLabel: "Expire Subscription",
        tone: "warning",
      });
      if (!ok) return;
    }
    setSaving(true);
    try {
      if (action === "change-plan") {
        await changeUserPlan(editingUser.id, {
          plan_id: Number(form.plan_id),
          duration_days: form.duration_days ? Number(form.duration_days) : null,
        });
        showToast("Plan changed");
      } else if (action === "renew") {
        await renewUserSubscription(editingUser.id, {
          plan_id: Number(form.plan_id),
          duration_days: form.duration_days ? Number(form.duration_days) : planDuration(plans, form.plan_id),
          issue_api_key: false,
        });
        showToast("Subscription renewed");
      } else {
        await expireUserSubscription(editingUser.id);
        showToast("Subscription expired");
      }
      await openEdit(editingUser);
      fetchUsers();
    } catch (e) {
      showToast(errMessage(e, "Subscription action failed"), "error");
    } finally {
      setSaving(false);
    }
  };

  const openUsage = async (user) => {
    setUsageUser(user);
    setUsageDetails(null);
    setUsageLoading(true);
    try {
      const details = await getUser(user.id);
      setUsageDetails(details);
    } catch (e) {
      showToast(errMessage(e, "Failed to load account usage"), "error");
    } finally {
      setUsageLoading(false);
    }
  };

  const handleCreateRazorpayOrder = async () => {
    if (!editingUser) return;
    if (!form.plan_id) {
      showToast("Select a plan first", "error");
      return;
    }
    setSaving(true);
    try {
      const data = await createRazorpayOrder(editingUser.id, form.plan_id);
      setRazorpayOrder(data);
      showToast("Razorpay order created");
      fetchUsers();
    } catch (e) {
      showToast(errMessage(e, "Failed to create Razorpay order"), "error");
    } finally {
      setSaving(false);
    }
  };

  const openRazorpayCheckout = async () => {
    if (!razorpayOrder?.order?.id) return;
    try {
      await loadRazorpayCheckout();
      const selectedPlan = plans.find((p) => String(p.id) === String(razorpayOrder.payment?.plan_id || form.plan_id));
      const checkout = new window.Razorpay({
        key: razorpayOrder.key_id,
        amount: razorpayOrder.order.amount,
        currency: razorpayOrder.order.currency || "INR",
        name: "EazyFill",
        description: selectedPlan?.name || "Subscription payment",
        order_id: razorpayOrder.order.id,
        prefill: {
          name: editingUser?.full_name || "",
          email: editingUser?.email || "",
          contact: editingUser?.mobile_number || "",
        },
        notes: {
          payment_id: String(razorpayOrder.payment?.id || ""),
          user_id: String(editingUser?.id || ""),
          plan_id: String(razorpayOrder.payment?.plan_id || form.plan_id || ""),
        },
        handler: () => {
          showToast("Payment completed. Waiting for Razorpay webhook confirmation.");
          setRazorpayOrder(null);
        },
        modal: {
          ondismiss: () => showToast("Razorpay checkout closed", "info"),
        },
      });
      checkout.open();
    } catch (e) {
      showToast("Failed to load Razorpay checkout", "error");
    }
  };

  const totalPages = Math.ceil(total / limit);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-indigo-500/20 text-indigo-500 rounded-lg backdrop-blur-md">
            <Users size={20} />
          </div>
          <div>
            <h2 className={`text-lg font-semibold ${t_textHeading}`}>User Management</h2>
            <p className={`text-xs ${t_textMuted}`}>{total} total users</p>
          </div>
        </div>
        <button onClick={openCreate} className={solidButton}>
          <UserPlus size={16} /> Add User
        </button>
      </div>

      <div className={`rounded-2xl p-4 ${glassPanel} flex flex-wrap gap-3 items-center`}>
        <div className="relative flex-1 min-w-[200px]">
          <Search size={14} className={`absolute left-3 top-1/2 -translate-y-1/2 ${t_textMuted}`} />
          <input className={`${glassInput} pl-9 w-full`} placeholder="Search name, email, or mobile..." value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(0); }} />
        </div>
        <select className={glassInput} value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value); setPage(0); }}>
          <option value="">All Statuses</option>
          <option value="active">Active</option>
          <option value="pending_payment">Pending Payment</option>
          <option value="pending_approval">Pending Approval</option>
          <option value="blocked">Blocked</option>
          <option value="expired">Expired</option>
          <option value="inactive">Inactive</option>
        </select>
      </div>

      <div className={`rounded-2xl overflow-hidden ${glassPanel}`}>
        {loading ? (
          <div className="flex items-center justify-center p-12"><Loader2 className="animate-spin text-indigo-500" size={32} /></div>
        ) : users.length === 0 ? (
          <div className="p-12 text-center"><p className={t_textMuted}>No users found</p></div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className={`border-b ${t_borderLight}`}>
                  <th className={`text-left p-3 text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>Name</th>
                  <th className={`text-left p-3 text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>Email</th>
                  <th className={`text-left p-3 text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>Mobile</th>
                  <th className={`text-left p-3 text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>Plan</th>
                  <th className={`text-left p-3 text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>Activity</th>
                  <th className={`text-left p-3 text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>Rate</th>
                  <th className={`text-left p-3 text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>Expiry</th>
                  <th className={`text-left p-3 text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>Status</th>
                  <th className={`text-left p-3 text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>Created</th>
                  <th className={`text-right p-3 text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} className={`border-b ${t_borderLight} ${isDark ? "hover:bg-white/[0.02]" : "hover:bg-black/[0.02]"}`}>
                    <td className="p-3">
                      <button
                        type="button"
                        onClick={() => openUsage(u)}
                        className={`text-left font-medium underline-offset-2 hover:underline ${t_textHeading}`}
                        title="Open account usage"
                      >
                        {u.full_name || u.email || `User #${u.id}`}
                      </button>
                    </td>
                    <td className={`p-3 ${t_textMuted}`}>{u.email || "--"}</td>
                    <td className={`p-3 ${t_textMuted}`}>{u.mobile_number || "--"}</td>
                    <td className={`p-3 ${t_textHeading}`}>
                      {u.plan_name ? (
                        <span>
                          {u.plan_name}
                          {u.subscription_status && u.subscription_status !== "active" ? <span className={`text-xs ${t_textMuted}`}> ({u.subscription_status})</span> : null}
                          <br/><span className={`text-xs ${t_textMuted}`}>Usage {rowUsageText(u)}</span>
                        </span>
                      ) : <span className={t_textMuted}>--</span>}
                    </td>
                    <td className={`p-3 ${t_textHeading}`}>
                      {rowActivityText(u) ? (
                        <span>{rowActivityText(u).primary}<br/><span className={`text-xs ${t_textMuted}`}>{rowActivityText(u).secondary}</span></span>
                      ) : <span className={t_textMuted}>No activity</span>}
                    </td>
                    <td className={`p-3 ${t_textMuted}`}>
                      {u.plan_rate_limit_rpm ? `${u.plan_rate_limit_rpm} RPM / +${u.plan_rate_limit_burst || 0}` : "--"}
                    </td>
                    <td className={`p-3 ${t_textMuted}`}>{formatDate(u.subscription_expiry)}</td>
                    <td className="p-3">
                      <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_COLORS[u.status] || "bg-slate-500/20 text-slate-400"}`}>
                        {u.status}
                      </span>
                    </td>
                    <td className={`p-3 ${t_textMuted}`}>{formatDate(u.created_at)}</td>
                    <td className="p-3">
                      <div className="flex items-center justify-end gap-1">
                        <button onClick={() => openEdit(u)} className={iconBtn("edit")} title="Manage"><Edit3 size={14} /></button>
                        {u.status !== "active" && u.status !== "deleted" && (
                          <button onClick={() => handleStatusChange(u.id, "active")} className={iconBtn("success")} title="Activate"><CheckCircle size={14} className="text-emerald-400" /></button>
                        )}
                        {u.status === "active" && (
                          <button onClick={() => handleStatusChange(u.id, "blocked")} className={iconBtn("danger")} title="Block"><Ban size={14} className="text-red-400" /></button>
                        )}
                        {u.status !== "deleted" && (
                          <button onClick={() => handleDelete(u.id)} className={iconBtn("danger")} title="Delete"><Trash2 size={14} className="text-red-400" /></button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <p className={`text-xs ${t_textMuted}`}>Page {page + 1} of {totalPages}</p>
          <div className="flex gap-2">
            <button onClick={() => setPage((p) => Math.max(0, p - 1))} disabled={page === 0} className={iconBtn("ghost")}><ChevronLeft size={16} /></button>
            <button onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1} className={iconBtn("ghost")}><ChevronRight size={16} /></button>
          </div>
        </div>
      )}

      {usageUser && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4" onClick={closeUsage}>
          <div className={`${glassPanel} rounded-2xl p-6 w-full max-w-4xl border ${t_borderLight} max-h-[90vh] overflow-auto`} onClick={(e) => e.stopPropagation()}>
            <div className="mb-4 flex items-start justify-between gap-3">
              <div>
                <h3 className={`text-lg font-semibold ${t_textHeading}`}>Account usage</h3>
                <p className={`text-xs ${t_textMuted}`}>{usageUser.full_name || usageUser.email || `User #${usageUser.id}`} - {usageUser.email || "No email"}</p>
              </div>
              <div className="flex items-center gap-2">
                {usageLoading && <Loader2 size={18} className="animate-spin text-indigo-500" />}
                <button type="button" onClick={closeUsage} className={`px-3 py-2 rounded-xl text-sm ${t_textMuted} border ${t_borderLight}`}>Close</button>
              </div>
            </div>
            <AccountUsageContent
              details={usageDetails}
              fallbackUser={usageUser}
              muted={t_textMuted}
              heading={t_textHeading}
              border={t_borderLight}
            />
          </div>
        </div>
      )}

      {(showCreate || editingUser) && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4" onClick={resetModal}>
          <div className={`${glassPanel} rounded-2xl p-6 w-full max-w-3xl border ${t_borderLight} max-h-[90vh] overflow-auto`} onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start justify-between gap-3 mb-4">
              <div>
                <h3 className={`text-lg font-semibold ${t_textHeading}`}>{editingUser ? "Manage User" : "Create User"}</h3>
                {editingUser && <p className={`text-xs ${t_textMuted}`}>Profile, plan, billing, and subscription controls.</p>}
              </div>
              {detailsLoading && <Loader2 size={18} className="animate-spin text-indigo-500" />}
            </div>

            <form onSubmit={editingUser ? handleUpdate : handleCreate} className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <Field label="Full Name" muted={t_textMuted}>
                  <input className={glassInput} value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} required />
                </Field>
                <Field label="Email" muted={t_textMuted}>
                  <input type="email" className={glassInput} value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} placeholder="user@gmail.com" />
                </Field>
                <Field label="Mobile Number" muted={t_textMuted}>
                  <input className={glassInput} value={form.mobile_number} onChange={(e) => setForm({ ...form, mobile_number: e.target.value })} placeholder="+91..." />
                </Field>
                <Field label="Status" muted={t_textMuted}>
                  <select className={glassInput} value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
                    {Object.keys(STATUS_COLORS).map((status) => <option key={status} value={status}>{status}</option>)}
                  </select>
                </Field>
                <Field label="Plan" muted={t_textMuted}>
                  <select
                    className={glassInput}
                    value={form.plan_id}
                    onChange={(e) => setForm({
                      ...form,
                      plan_id: e.target.value,
                      duration_days: planDuration(plans, e.target.value),
                    })}
                  >
                    <option value="">No plan</option>
                    {plans.map((plan) => (
                      <option key={plan.id} value={plan.id}>{plan.name} ({plan.duration_days}d)</option>
                    ))}
                  </select>
                </Field>
                <Field label="Duration Days" muted={t_textMuted}>
                  <input type="number" min="1" className={glassInput} value={form.duration_days}
                    onChange={(e) => setForm({ ...form, duration_days: e.target.value })} />
                </Field>
                <div className="sm:col-span-2">
                  <Field label="Notes" muted={t_textMuted}>
                    <textarea className={glassInput} rows={2} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} />
                  </Field>
                </div>
              </div>

              <div className="flex flex-wrap gap-2 pt-1">
                <button type="submit" className={solidButton} disabled={saving}>
                  {saving ? <Loader2 size={16} className="animate-spin" /> : "Save Profile"}
                </button>
                <button type="button" onClick={resetModal} className={`px-4 py-2 rounded-xl text-sm ${t_textMuted} border ${t_borderLight}`}>Close</button>
              </div>
            </form>

            {editingUser && (
              <div className="mt-6 grid grid-cols-1 gap-4">
                <section className={`rounded-xl border p-4 ${t_borderLight}`}>
                  <h4 className={`text-sm font-semibold mb-3 ${t_textHeading}`}>Subscription</h4>
                  <div className={`text-xs mb-3 ${t_textMuted}`}>
                    Current: {userDetails?.active_subscription?.plan_name || "--"} · Expires {formatDate(userDetails?.active_subscription?.end_at)}
                  </div>
                  <div className={`grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs mb-3 ${t_textMuted}`}>
                    <div>
                      <span className={t_textHeading}>Plan usage:</span> {formatCount(userDetails?.usage?.plan_usage_used ?? userDetails?.usage?.quota_used)}/{formatCount(userDetails?.usage?.quota_limit)}
                    </div>
                    <div>
                      <span className={t_textHeading}>Rate limit:</span> {userDetails?.rate_limit?.requests_per_minute || "--"} RPM / +{userDetails?.rate_limit?.burst || 0}
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button type="button" className={glassButton} disabled={saving} onClick={() => handleSubscriptionAction("change-plan")}>
                      <RefreshCw size={14} /> Change Plan
                    </button>
                    <button type="button" className={glassButton} disabled={saving} onClick={() => handleSubscriptionAction("renew")}>
                      <CalendarPlus size={14} /> Renew
                    </button>
                    <button type="button" className={glassButton} disabled={saving || !form.plan_id} onClick={handleCreateRazorpayOrder}>
                      <CreditCard size={14} /> Razorpay Order
                    </button>
                    <button type="button" className={dangerButton} disabled={saving} onClick={() => handleSubscriptionAction("expire")}>
                      <ShieldOff size={14} /> Expire
                    </button>
                  </div>
                </section>

              </div>
            )}
          </div>
        </div>
      )}

      {razorpayOrder?.order?.id && (
        <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 backdrop-blur-sm p-4" onClick={() => setRazorpayOrder(null)}>
          <div className={`${glassPanel} rounded-2xl p-6 w-full max-w-lg border ${t_borderLight}`} onClick={(e) => e.stopPropagation()}>
            <h3 className={`text-lg font-semibold mb-2 ${t_textHeading}`}>Razorpay Order Created</h3>
            <p className={`text-xs mb-4 ${t_textMuted}`}>Open checkout to test/pay now. Final activation still waits for the signed Razorpay webhook.</p>
            <div className={`rounded-xl border ${t_borderLight} p-3 space-y-2 text-xs ${t_textMuted}`}>
              <div><span className={t_textHeading}>Order:</span> <span className="font-mono">{razorpayOrder.order.id}</span></div>
              <div><span className={t_textHeading}>Payment:</span> #{razorpayOrder.payment?.id}</div>
              <div><span className={t_textHeading}>Amount:</span> {razorpayOrder.order.currency || "INR"} {(Number(razorpayOrder.order.amount || 0) / 100).toFixed(2)}</div>
              <div><span className={t_textHeading}>Status:</span> {razorpayOrder.order.status || razorpayOrder.payment?.status}</div>
            </div>
            <div className="flex flex-wrap gap-2 mt-4">
              <button className={solidButton} onClick={openRazorpayCheckout}>
                <CreditCard size={16} /> Open Checkout
              </button>
              <button
                className={`px-4 py-2 rounded-xl text-sm ${t_textMuted} border ${t_borderLight}`}
                onClick={() => navigator.clipboard.writeText(razorpayOrder.order.id).catch(() => {})}
              >
                Copy Order ID
              </button>
              <button className={`px-4 py-2 rounded-xl text-sm ${t_textMuted} border ${t_borderLight}`} onClick={() => setRazorpayOrder(null)}>Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Field({ label, muted, children }) {
  return (
    <label className="block">
      <span className={`text-xs block mb-1 ${muted}`}>{label}</span>
      {children}
    </label>
  );
}

function MetricCard({ label, value, detail, muted, heading, border }) {
  return (
    <div className={`rounded-xl border ${border} p-3`}>
      <div className={`text-xs font-semibold uppercase ${muted}`}>{label}</div>
      <div className={`mt-1 text-lg font-semibold ${heading}`}>{value}</div>
      <div className={`mt-1 text-xs ${muted}`}>{detail}</div>
    </div>
  );
}

function DetailList({ title, items, empty, muted, heading, border }) {
  return (
    <div className={`rounded-xl border ${border} p-3`}>
      <div className={`mb-2 text-xs font-semibold uppercase ${muted}`}>{title}</div>
      {items.length ? (
        <div className="grid gap-2">
          {items.map((item) => (
            <div key={item.key} className="text-xs">
              <div className={`font-medium ${heading}`}>{item.primary}</div>
              <div className={muted}>{item.secondary}</div>
            </div>
          ))}
        </div>
      ) : (
        <p className={`text-xs ${muted}`}>{empty}</p>
      )}
    </div>
  );
}

function AccountUsageContent({ details, fallbackUser, muted, heading, border }) {
  const account = details || fallbackUser || {};
  const usage = details?.usage || {};
  const subscription = details?.display_subscription || details?.active_subscription || {};
  const activeSessions = (details?.sessions || []).filter((item) => item.status === "active").length;
  return (
    <div className="grid gap-4">
      <section className={`rounded-xl border p-4 ${border}`}>
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <div>
            <h4 className={`text-sm font-semibold ${heading}`}>Usage stats</h4>
            <p className={`text-xs ${muted}`}>
              {subscription.plan_name || account.plan_name || "No plan"}{subscription.status ? ` (${subscription.status})` : ""} - expires {formatDate(subscription.end_at || account.subscription_expiry)}
            </p>
          </div>
          <span className={`rounded-full px-2 py-1 text-xs ${STATUS_COLORS[account.status] || STATUS_COLORS.inactive}`}>
            {account.status || "unknown"}
          </span>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <MetricCard
            label="Cycle usage"
            value={`${formatCount(usage.quota_used ?? account.quota_used)}/${formatCount(usage.quota_limit ?? account.quota_limit)}`}
            detail={`${usagePercent(usage.quota_used ?? account.quota_used, usage.quota_limit ?? account.quota_limit)}% used`}
            muted={muted}
            heading={heading}
            border={border}
          />
          <MetricCard
            label="Today"
            value={formatCount(usage.today?.credits_used ?? account.today_credits_used)}
            detail="credits used"
            muted={muted}
            heading={heading}
            border={border}
          />
          <MetricCard
            label="Cloud backup"
            value={formatBytes(details?.sync_backup?.blob_size_bytes ?? account.sync_backup_size_bytes)}
            detail={details?.sync_backup?.updated_at || account.sync_updated_at ? `Updated ${formatDate(details?.sync_backup?.updated_at || account.sync_updated_at)}` : "No sync blob"}
            muted={muted}
            heading={heading}
            border={border}
          />
          <MetricCard
            label="Sessions"
            value={formatCount(activeSessions || account.active_session_count)}
            detail={`${formatCount(details?.plan_limits?.max_devices || 0)} device limit`}
            muted={muted}
            heading={heading}
            border={border}
          />
        </div>
      </section>
      <div className="grid gap-3 lg:grid-cols-2">
        <DetailList
          title="Recent sessions"
          items={(details?.sessions || []).slice(0, 6).map((item) => ({
            key: item.id,
            primary: item.device_name || item.device_id || `Session #${item.id}`,
            secondary: `${item.status} - ${formatDateTime(item.last_seen)}`,
          }))}
          empty="No account sessions recorded"
          muted={muted}
          heading={heading}
          border={border}
        />
        <DetailList
          title="Devices"
          items={(details?.all_devices || details?.devices || []).slice(0, 6).map((item) => ({
            key: item.id,
            primary: item.device_name || item.device_fingerprint || `Device #${item.id}`,
            secondary: `${item.status} - ${formatDateTime(item.last_seen)}`,
          }))}
          empty="No device activity recorded"
          muted={muted}
          heading={heading}
          border={border}
        />
      </div>
      <section className={`rounded-xl border p-4 ${border}`}>
        <h4 className={`mb-3 text-sm font-semibold ${heading}`}>Recent payments</h4>
        {(details?.payments || []).length ? (
          <div className="grid gap-2">
            {(details?.payments || []).slice(0, 8).map((payment) => (
              <div key={payment.id} className="flex flex-wrap items-center justify-between gap-2 text-xs">
                <span className={heading}>#{payment.id} - {payment.plan_name || `Plan ${payment.plan_id || "--"}`}</span>
                <span className={muted}>{payment.currency || "INR"} {(Number(payment.amount || 0) / 100).toFixed(2)} - {payment.status} - {formatDate(payment.created_at)}</span>
              </div>
            ))}
          </div>
        ) : (
          <p className={`text-xs ${muted}`}>No payments recorded</p>
        )}
      </section>
    </div>
  );
}

Field.propTypes = {
  label: PropTypes.string.isRequired,
  muted: PropTypes.string.isRequired,
  children: PropTypes.node.isRequired,
};

MetricCard.propTypes = {
  label: PropTypes.string.isRequired,
  value: PropTypes.string.isRequired,
  detail: PropTypes.string.isRequired,
  muted: PropTypes.string.isRequired,
  heading: PropTypes.string.isRequired,
  border: PropTypes.string.isRequired,
};

DetailList.propTypes = {
  title: PropTypes.string.isRequired,
  items: PropTypes.arrayOf(PropTypes.shape({
    key: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
    primary: PropTypes.string.isRequired,
    secondary: PropTypes.string.isRequired,
  })).isRequired,
  empty: PropTypes.string.isRequired,
  muted: PropTypes.string.isRequired,
  heading: PropTypes.string.isRequired,
  border: PropTypes.string.isRequired,
};

AccountUsageContent.propTypes = {
  details: PropTypes.object,
  fallbackUser: PropTypes.object,
  muted: PropTypes.string.isRequired,
  heading: PropTypes.string.isRequired,
  border: PropTypes.string.isRequired,
};

UsersPanel.propTypes = {
  showToast: PropTypes.func.isRequired,
};
