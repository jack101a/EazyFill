import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  CreditCard,
  Gauge,
  RefreshCw,
  Smartphone,
  Users,
} from "lucide-react";
import { fetchEazyFillAbuse, fetchEazyFillOverview, eazyfillQueryKeys } from "../../../api/eazyfill";
import { usePageTitle } from "../../hooks/usePageTitle";
import { useThemeContext } from "../../context/ThemeContext";
import { SkeletonCard } from "../../components/Skeleton";

function formatCount(value) {
  return Number(value || 0).toLocaleString();
}

function formatMoney(totals = {}) {
  const entries = Object.entries(totals);
  if (!entries.length) return "INR 0.00";
  return entries
    .map(([currency, amount]) => `${currency} ${(Number(amount || 0) / 100).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`)
    .join(" + ");
}

function Metric({ label, value, detail, icon: Icon, tone = "text-[#C4B5FD]" }) {
  const { isDark, t_textHeading, t_textMuted } = useThemeContext();
  return (
    <div className={`border-b p-5 sm:border-b-0 sm:border-r ${isDark ? "border-white/[0.07]" : "border-slate-200"}`}>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <p className={`text-xs font-semibold uppercase ${t_textMuted}`}>{label}</p>
          <p className={`mt-2 text-2xl font-bold ${t_textHeading}`}>{value}</p>
          <p className={`mt-1 text-xs ${t_textMuted}`}>{detail}</p>
        </div>
        <Icon size={20} className={tone} />
      </div>
    </div>
  );
}

export function EazyFillOverviewPage() {
  usePageTitle("Overview");
  const { isDark, t_textHeading, t_textMuted, glassPanel, glassButton } = useThemeContext();
  const overview = useQuery({
    queryKey: eazyfillQueryKeys.overview,
    queryFn: fetchEazyFillOverview,
    staleTime: 30_000,
  });
  const abuse = useQuery({
    queryKey: eazyfillQueryKeys.abuse,
    queryFn: () => fetchEazyFillAbuse(10),
    staleTime: 30_000,
  });

  const data = overview.data || {};
  const risk = abuse.data || {};
  const usageLimit = Number(data.usage?.limit || 0);
  const usageUsed = Number(data.usage?.used || 0);
  const usagePercent = usageLimit > 0 ? Math.min(100, Math.round((usageUsed / usageLimit) * 100)) : 0;
  const riskCount = (risk.quota_exhausted?.length || 0)
    + (risk.multi_device_keys?.length || 0)
    + (risk.failed_webhooks?.length || 0);
  const refresh = () => {
    overview.refetch();
    abuse.refetch();
  };

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className={`text-xs font-bold uppercase ${t_textMuted}`}>EazyFill Operations</p>
          <h1 className={`mt-1 text-2xl font-bold ${t_textHeading}`}>Product overview</h1>
          <p className={`mt-1 text-sm ${t_textMuted}`}>Backend-owned users, plans, billing, devices, usage, and extension risk.</p>
        </div>
        <button type="button" className={glassButton} onClick={refresh} disabled={overview.isFetching || abuse.isFetching}>
          <RefreshCw size={15} className={overview.isFetching || abuse.isFetching ? "animate-spin" : ""} />
          Refresh
        </button>
      </header>

      {overview.isLoading ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 8 }).map((_, index) => <SkeletonCard key={index} />)}
        </div>
      ) : overview.error ? (
        <div className="border border-rose-500/30 bg-rose-500/10 p-4 text-sm text-rose-400">
          {overview.error.message || "EazyFill overview could not be loaded."}
        </div>
      ) : (
        <section className={`overflow-hidden border ${glassPanel}`}>
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4">
            <Metric label="Users" value={formatCount(data.users?.total)} detail={`${formatCount(data.users?.active)} active, ${formatCount(data.users?.blocked)} blocked`} icon={Users} />
            <Metric label="Subscriptions" value={formatCount(data.subscriptions?.active)} detail="Active product subscriptions" icon={CreditCard} tone="text-emerald-400" />
            <Metric label="Device sessions" value={formatCount(data.keys?.active)} detail={`${formatCount(data.keys?.active_devices)} active devices`} icon={Smartphone} tone="text-amber-400" />
            <Metric label="Revenue" value={formatMoney(data.billing?.approved_revenue)} detail={`${formatCount(data.billing?.pending_payments)} pending payments`} icon={CreditCard} tone="text-emerald-400" />
            <Metric label="Usage" value={`${formatCount(usageUsed)} / ${formatCount(usageLimit)}`} detail={`${usagePercent}% of allocated credits consumed`} icon={Gauge} tone="text-sky-400" />
            <Metric label="Quota risk" value={formatCount(data.usage?.quota_risk_users)} detail="Users at or beyond current limit" icon={AlertTriangle} tone="text-rose-400" />
            <Metric label="Webhook failures" value={formatCount(data.billing?.webhook_failures_7d)} detail="Razorpay failures in the last 7 days" icon={AlertTriangle} tone="text-orange-400" />
            <Metric label="Devices" value={formatCount(data.keys?.active_devices)} detail="Active signed-in devices" icon={Smartphone} tone="text-violet-400" />
          </div>
        </section>
      )}

      <section className={`border ${glassPanel}`}>
        <div className={`flex flex-col gap-3 border-b p-5 sm:flex-row sm:items-center sm:justify-between ${isDark ? "border-white/[0.07]" : "border-slate-200"}`}>
          <div>
            <h2 className={`text-base font-semibold ${t_textHeading}`}>Attention queue</h2>
            <p className={`mt-1 text-xs ${t_textMuted}`}>Quota, device, and payment signals requiring operator review.</p>
          </div>
          <Link to="/operations" className={glassButton}>Open operations</Link>
        </div>
        <div className="grid grid-cols-1 divide-y sm:grid-cols-3 sm:divide-x sm:divide-y-0 divide-white/[0.07]">
          <Metric label="Quota exhausted" value={formatCount(risk.quota_exhausted?.length)} detail="Current result window" icon={Gauge} tone="text-rose-400" />
          <Metric label="Multi-device sessions" value={formatCount(risk.multi_device_keys?.length)} detail="Accounts seen on multiple active devices" icon={Smartphone} tone="text-amber-400" />
          <Metric label="Failed webhooks" value={formatCount(risk.failed_webhooks?.length)} detail={`${formatCount(riskCount)} combined signals`} icon={AlertTriangle} tone="text-orange-400" />
        </div>
      </section>
    </div>
  );
}
