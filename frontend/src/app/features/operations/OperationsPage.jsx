import React from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Gauge, RefreshCw, Smartphone, Webhook } from "lucide-react";
import { fetchEazyFillAbuse, eazyfillQueryKeys } from "../../../api/eazyfill";
import { EmptyState } from "../../components/EmptyState";
import { useThemeContext } from "../../context/ThemeContext";
import { usePageTitle } from "../../hooks/usePageTitle";

function formatDate(value) {
  return value ? new Date(value).toLocaleString() : "-";
}

function QueueSection({ title, description, icon: Icon, count, children }) {
  const { isDark, t_textHeading, t_textMuted, glassPanel } = useThemeContext();
  return (
    <section className={`overflow-hidden border ${glassPanel}`}>
      <div className={`flex items-center justify-between gap-4 border-b p-5 ${isDark ? "border-white/[0.07]" : "border-slate-200"}`}>
        <div className="flex items-center gap-3">
          <Icon size={19} className="text-amber-400" />
          <div>
            <h2 className={`text-base font-semibold ${t_textHeading}`}>{title}</h2>
            <p className={`text-xs ${t_textMuted}`}>{description}</p>
          </div>
        </div>
        <span className="border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-xs font-bold text-amber-400">{count}</span>
      </div>
      {children}
    </section>
  );
}

export function OperationsPage() {
  usePageTitle("Risk & Abuse");
  const { isDark, t_textHeading, t_textMuted, glassButton } = useThemeContext();
  const query = useQuery({
    queryKey: eazyfillQueryKeys.abuse,
    queryFn: () => fetchEazyFillAbuse(100),
    staleTime: 20_000,
  });
  const data = query.data || {};
  const quota = data.quota_exhausted || [];
  const devices = data.multi_device_keys || [];
  const webhooks = data.failed_webhooks || [];
  const tableBorder = isDark ? "border-white/[0.07]" : "border-slate-200";

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className={`text-xs font-bold uppercase ${t_textMuted}`}>Operations</p>
          <h1 className={`mt-1 text-2xl font-bold ${t_textHeading}`}>Risk and abuse</h1>
          <p className={`mt-1 text-sm ${t_textMuted}`}>Backend signals for quota enforcement, device sharing, and payment delivery failures.</p>
        </div>
        <button type="button" className={glassButton} onClick={() => query.refetch()} disabled={query.isFetching}>
          <RefreshCw size={15} className={query.isFetching ? "animate-spin" : ""} />
          Refresh
        </button>
      </header>

      {query.error ? (
        <div className="border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-400">
          {query.error.message || "Operations queue could not be loaded."}
        </div>
      ) : null}

      <QueueSection title="Quota exhausted" description="Active cycles at or above their plan limit." icon={Gauge} count={quota.length}>
        {quota.length ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[680px] text-left text-sm">
              <thead>
                <tr className={`border-b ${tableBorder}`}>
                  <th className="p-3">User</th>
                  <th className="p-3">Status</th>
                  <th className="p-3">Usage</th>
                  <th className="p-3">Cycle ends</th>
                </tr>
              </thead>
              <tbody>
                {quota.map((item) => (
                  <tr key={item.cycle_id} className={`border-b ${tableBorder}`}>
                    <td className="p-3">{item.name || `User #${item.user_id}`}</td>
                    <td className="p-3">{item.status}</td>
                    <td className="p-3">{item.used} / {item.limit}</td>
                    <td className="p-3">{formatDate(item.cycle_end_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState icon={Gauge} title="No quota incidents" description="No active user is currently at the configured plan limit." />
        )}
      </QueueSection>

      <QueueSection title="Multi-device sessions" description="Accounts or credentials seen on more than one active device." icon={Smartphone} count={devices.length}>
        {devices.length ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-left text-sm">
              <thead>
                <tr className={`border-b ${tableBorder}`}>
                  <th className="p-3">Credential ID</th>
                  <th className="p-3">User ID</th>
                  <th className="p-3">Active devices</th>
                </tr>
              </thead>
              <tbody>
                {devices.map((item) => (
                  <tr key={item.key_id} className={`border-b ${tableBorder}`}>
                    <td className="p-3 font-mono">#{item.key_id}</td>
                    <td className="p-3">#{item.user_id}</td>
                    <td className="p-3">{item.active_device_count}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState icon={Smartphone} title="No shared sessions detected" description="Active devices are within the expected account bindings." />
        )}
      </QueueSection>

      <QueueSection title="Failed payment webhooks" description="Recent provider events that could not be processed." icon={Webhook} count={webhooks.length}>
        {webhooks.length ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[780px] text-left text-sm">
              <thead>
                <tr className={`border-b ${tableBorder}`}>
                  <th className="p-3">Provider</th>
                  <th className="p-3">Event</th>
                  <th className="p-3">Payment</th>
                  <th className="p-3">Error</th>
                  <th className="p-3">Received</th>
                </tr>
              </thead>
              <tbody>
                {webhooks.map((item) => (
                  <tr key={item.event_id} className={`border-b ${tableBorder}`}>
                    <td className="p-3 capitalize">{item.provider}</td>
                    <td className="p-3 font-mono text-xs">{item.event_type}</td>
                    <td className="p-3">{item.payment_id ? `#${item.payment_id}` : "-"}</td>
                    <td className="p-3 text-rose-400">{item.error_message || "-"}</td>
                    <td className="p-3">{formatDate(item.received_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState icon={AlertTriangle} title="No webhook failures" description="Payment provider events are processing normally." />
        )}
      </QueueSection>
    </div>
  );
}
