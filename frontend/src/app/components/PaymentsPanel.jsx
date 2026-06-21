import React, { useState, useEffect, useCallback } from "react";
import PropTypes from "prop-types";
import { AlertTriangle, CreditCard, Loader2, CheckCircle, XCircle } from "lucide-react";
import { useThemeContext } from "../context/ThemeContext";
import { approvePayment, fetchPendingPaymentCount, listPayments, rejectPayment } from "../../api/billing";

const STATUS_COLORS = {
  pending_payment: "bg-[#8B5CF6]/20 text-[#C4B5FD]",
  pending: "bg-amber-500/20 text-amber-400",
  created: "bg-sky-500/20 text-sky-400",
  approved: "bg-emerald-500/20 text-emerald-400",
  rejected: "bg-red-500/20 text-red-400",
  expired: "bg-gray-500/20 text-gray-400",
};

export function PaymentsPanel({ showToast }) {
  const { t_textHeading, t_textMuted, t_borderLight, glassPanel, glassInput, solidButton, iconBtn, isDark } = useThemeContext();
  const [payments, setPayments] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("");
  const [pendingCount, setPendingCount] = useState(0);
  const [page, setPage] = useState(0);
  const [approving, setApproving] = useState(null);
  const [approveReason, setApproveReason] = useState("");
  const [approveConfirmed, setApproveConfirmed] = useState(false);
  const [rejecting, setRejecting] = useState(null);
  const [rejectReason, setRejectReason] = useState("");
  const limit = 20;

  const fetchPayments = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listPayments({ offset: page * limit, limit, status: statusFilter });
      setPayments(data.payments || []);
      setTotal(data.total || 0);
    } catch (e) {
      showToast("Failed to load payments", "error");
    } finally {
      setLoading(false);
    }
  }, [page, statusFilter, showToast]);

  const fetchPendingCount = useCallback(async () => {
    try {
      const data = await fetchPendingPaymentCount();
      setPendingCount(data.pending_count || 0);
    } catch (_) {}
  }, []);

  useEffect(() => { fetchPayments(); fetchPendingCount(); }, [fetchPayments, fetchPendingCount]);

  const resetApproveModal = () => {
    setApproving(null);
    setApproveReason("");
    setApproveConfirmed(false);
  };

  const handleApprove = async () => {
    if (!approving) return;
    try {
      await approvePayment(approving.id, approveReason, approveConfirmed);
      showToast("Payment approved");
      resetApproveModal();
      fetchPayments();
      fetchPendingCount();
    } catch (e) {
      showToast(e.message || "Failed to approve", "error");
    }
  };

  const handleReject = async (paymentId) => {
    try {
      await rejectPayment(paymentId, rejectReason);
      showToast("Payment rejected");
      setRejecting(null);
      setRejectReason("");
      fetchPayments();
      fetchPendingCount();
    } catch (e) {
      showToast(e.message || "Failed to reject", "error");
    }
  };

  const totalPages = Math.ceil(total / limit);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-amber-500/20 text-amber-500 rounded-lg backdrop-blur-md">
            <CreditCard size={20} />
          </div>
          <div>
            <h2 className={`text-lg font-semibold ${t_textHeading}`}>Payment Approvals</h2>
            <p className={`text-xs ${t_textMuted}`}>
              {pendingCount > 0 && <span className="text-amber-400 font-medium">{pendingCount} pending</span>}
              {pendingCount === 0 && "All clear"}
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          {["", "created", "pending_payment", "approved", "rejected", "failed", "expired"].map((s) => (
            <button key={s} onClick={() => { setStatusFilter(s); setPage(0); }}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-all ${
                statusFilter === s ? "bg-indigo-500/20 text-indigo-400 border border-indigo-500/30" : `${t_textMuted} border ${t_borderLight}`
              }`}>
              {s || "All"}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className={`rounded-2xl overflow-hidden ${glassPanel}`}>
        {loading ? (
          <div className="flex items-center justify-center p-12"><Loader2 className="animate-spin text-indigo-500" size={32} /></div>
        ) : payments.length === 0 ? (
          <div className="p-12 text-center"><p className={t_textMuted}>No payments found</p></div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className={`border-b ${t_borderLight}`}>
                  <th className={`text-left p-3 text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>ID</th>
                  <th className={`text-left p-3 text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>User</th>
                  <th className={`text-left p-3 text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>Contact</th>
                  <th className={`text-left p-3 text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>Plan</th>
                  <th className={`text-left p-3 text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>Amount</th>
                  <th className={`text-left p-3 text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>Provider</th>
                  <th className={`text-left p-3 text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>Ref</th>
                  <th className={`text-left p-3 text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>Provider Ref</th>
                  <th className={`text-left p-3 text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>Provider Status</th>
                  <th className={`text-left p-3 text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>Status</th>
                  <th className={`text-left p-3 text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>Date</th>
                  <th className={`text-right p-3 text-xs font-semibold uppercase tracking-wider ${t_textMuted}`}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {payments.map((p) => (
                  <tr key={p.id} className={`border-b ${t_borderLight} ${isDark ? "hover:bg-white/[0.02]" : "hover:bg-black/[0.02]"}`}>
                    <td className={`p-3 font-mono text-xs ${t_textHeading}`}>#{p.id}</td>
                    <td className={`p-3 ${t_textHeading}`}>
                      <div>{p.user_full_name || `User #${p.user_id}`}</div>
                    </td>
                    <td className={`p-3 font-mono text-xs ${t_textMuted}`}>{p.user_email || p.user_mobile_number || "-"}</td>
                    <td className={`p-3 text-xs ${t_textMuted}`}>{p.plan_name || (p.plan_id ? `#${p.plan_id}` : "-")}</td>
                    <td className={`p-3 font-medium ${t_textHeading}`}>INR {(p.amount / 100).toFixed(2)}</td>
                    <td className={`p-3 text-xs ${t_textHeading}`}>
                      <div className="capitalize">{p.payment_provider || p.payment_method || "razorpay"}</div>
                      {p.payment_method && p.payment_method !== p.payment_provider && (
                        <div className={`font-mono text-[10px] ${t_textMuted}`}>{p.payment_method}</div>
                      )}
                    </td>
                    <td className={`p-3 font-mono text-xs ${t_textMuted}`}>{p.payment_ref || "-"}</td>
                    <td className={`p-3 font-mono text-xs ${t_textMuted}`}>
                      {p.provider_payment_id || p.provider_order_id || "-"}
                    </td>
                    <td className={`p-3 font-mono text-xs ${t_textMuted}`}>{p.provider_status || "-"}</td>
                    <td className="p-3">
                      <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_COLORS[p.status] || "bg-slate-500/20 text-slate-400"}`}>
                        {p.status}
                      </span>
                    </td>
                    <td className={`p-3 ${t_textMuted}`}>{(p.submitted_at || p.created_at) ? new Date(p.submitted_at || p.created_at).toLocaleString() : "-"}</td>
                    <td className="p-3">
                      {(p.status === "created" || p.status === "pending" || p.status === "pending_payment") && (
                        <div className="flex items-center justify-end gap-1">
                          <button onClick={() => setApproving(p)} className={iconBtn("success")} title="Manual approval override">
                            <CheckCircle size={16} className="text-emerald-400" />
                          </button>
                          <button onClick={() => setRejecting(p.id)} className={iconBtn("danger")} title="Reject">
                            <XCircle size={16} className="text-red-400" />
                          </button>
                        </div>
                      )}
                      {p.status === "rejected" && p.rejection_reason && (
                        <span className={`text-xs ${t_textMuted}`}>{p.rejection_reason}</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Manual Approval Modal */}
      {approving && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={resetApproveModal}>
          <div className={`${glassPanel} rounded-2xl p-6 w-full max-w-lg border ${t_borderLight}`} onClick={(e) => e.stopPropagation()}>
            <div className="flex items-start gap-3 mb-4">
              <div className="p-2 rounded-lg bg-amber-500/20 text-amber-400">
                <AlertTriangle size={18} />
              </div>
              <div>
                <h3 className={`text-lg font-semibold ${t_textHeading}`}>Manual Approval Override</h3>
                <p className={`text-xs mt-1 ${t_textMuted}`}>
                  Use this only when payment has been verified outside the automated Razorpay flow.
                </p>
              </div>
            </div>
            <div className={`rounded-xl border ${t_borderLight} p-3 mb-4 text-xs ${t_textMuted}`}>
              <div className="grid grid-cols-2 gap-2">
                <span>Payment</span><span className={`text-right font-mono ${t_textHeading}`}>#{approving.id}</span>
                <span>Amount</span><span className={`text-right font-medium ${t_textHeading}`}>INR {(approving.amount / 100).toFixed(2)}</span>
                <span>Provider</span><span className={`text-right ${t_textHeading}`}>{approving.payment_provider || approving.payment_method || "razorpay"}</span>
                <span>Provider Ref</span><span className={`text-right font-mono break-all ${t_textHeading}`}>{approving.provider_payment_id || approving.provider_order_id || "-"}</span>
                <span>Status</span><span className={`text-right font-mono ${t_textHeading}`}>{approving.status}</span>
              </div>
            </div>
            <div className="space-y-3">
              <div>
                <label className={`text-xs block mb-1 ${t_textMuted}`}>Manual Approval Reason</label>
                <textarea
                  className={glassInput}
                  rows={3}
                  value={approveReason}
                  onChange={(e) => setApproveReason(e.target.value)}
                  placeholder="Example: Matched Razorpay dashboard payment ID and amount manually."
                />
              </div>
              <label className={`flex items-start gap-2 text-xs ${t_textMuted}`}>
                <input
                  type="checkbox"
                  className="mt-0.5 h-4 w-4 rounded border-slate-400 accent-emerald-500"
                  checked={approveConfirmed}
                  onChange={(e) => setApproveConfirmed(e.target.checked)}
                />
                <span>I confirm this is a manual billing override and the payment evidence was verified.</span>
              </label>
              <div className="flex gap-2 pt-2">
                <button
                  onClick={handleApprove}
                  disabled={!approveConfirmed || approveReason.trim().length < 8}
                  className={`px-4 py-2 rounded-xl text-sm font-medium ${solidButton} disabled:opacity-50 disabled:cursor-not-allowed`}
                >
                  Approve Manually
                </button>
                <button onClick={resetApproveModal} className={`px-4 py-2 rounded-xl text-sm ${t_textMuted} border ${t_borderLight}`}>Cancel</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Reject Modal */}
      {rejecting && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={() => setRejecting(null)}>
          <div className={`${glassPanel} rounded-2xl p-6 w-full max-w-md border ${t_borderLight}`} onClick={(e) => e.stopPropagation()}>
            <h3 className={`text-lg font-semibold mb-4 ${t_textHeading}`}>Reject Payment #{rejecting}</h3>
            <div className="space-y-3">
              <div>
                <label className={`text-xs block mb-1 ${t_textMuted}`}>Rejection Reason</label>
                <textarea className={glassInput} rows={2} value={rejectReason} onChange={(e) => setRejectReason(e.target.value)} placeholder="Why is this payment rejected?" />
              </div>
              <div className="flex gap-2 pt-2">
                <button onClick={() => handleReject(rejecting)} className={`px-4 py-2 rounded-xl text-sm font-medium bg-red-500/20 text-red-400 border border-red-500/30`}>Reject</button>
                <button onClick={() => setRejecting(null)} className={`px-4 py-2 rounded-xl text-sm ${t_textMuted} border ${t_borderLight}`}>Cancel</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

PaymentsPanel.propTypes = {
  showToast: PropTypes.func.isRequired,
};
