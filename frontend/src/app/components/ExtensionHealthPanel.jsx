import React from "react";
import PropTypes from "prop-types";
import { AlertCircle, Bug, RefreshCw, ShieldCheck } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { fetchExtensionErrorReports } from "../../api/extension";
import { useThemeContext } from "../context/ThemeContext";
import { EmptyState } from "./EmptyState";

function formatDate(value) {
  if (!value) return "-";
  try { return new Date(value).toLocaleString(); } catch { return String(value); }
}

function StatCard({ label, value, tone }) {
  const { t_textHeading, t_textMuted, glassPanel } = useThemeContext();
  const toneClass = tone === "danger" ? "text-rose-400" : tone === "warn" ? "text-amber-400" : "text-emerald-400";
  return (
    <div className={`rounded-2xl p-4 ${glassPanel}`}>
      <p className={`text-xs font-medium ${t_textMuted}`}>{label}</p>
      <p className={`mt-1 text-2xl font-bold ${toneClass || t_textHeading}`}>{value}</p>
    </div>
  );
}

StatCard.propTypes = {
  label: PropTypes.string.isRequired,
  value: PropTypes.oneOfType([PropTypes.string, PropTypes.number]).isRequired,
  tone: PropTypes.string,
};

export function ExtensionHealthPanel({ showToast }) {
  const { isDark, t_textHeading, t_textMuted, t_borderLight, t_rowHover, glassPanel, glassButton } = useThemeContext();
  const reports = useQuery({
    queryKey: ["extensionErrorReports"],
    queryFn: fetchExtensionErrorReports,
    staleTime: 30_000,
  });
  const summary = reports.data?.summary || {};
  const events = Array.isArray(reports.data?.events) ? reports.data.events : [];
  const recentEvents = events.slice(-50).reverse();
  const totalEvents = Number(summary.total_events || events.length || 0);
  const uniqueDevices = Number(summary.unique_devices || 0);
  const lastSeen = summary.last_seen || summary.latest_ts || recentEvents[0]?.ts;
  const topErrors = summary.top_errors || summary.error_counts || {};

  const refresh = async () => {
    try {
      await reports.refetch();
      showToast?.("Extension health refreshed.");
    } catch (error) {
      showToast?.(error.message || "Failed to refresh extension health", "error");
    }
  };

  return (
    <div className="space-y-6">
      <div className={`rounded-2xl p-5 ${glassPanel}`}>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-3">
            <div className="rounded-xl bg-[#8B5CF6]/15 p-3 text-[#C4B5FD]">
              <Bug size={22} />
            </div>
            <div>
              <h2 className={`text-lg font-semibold ${t_textHeading}`}>Extension Health</h2>
              <p className={`text-xs ${t_textMuted}`}>Recent extension-side errors, sync failures, and client diagnostics.</p>
            </div>
          </div>
          <button type="button" onClick={refresh} disabled={reports.isFetching} className={glassButton}>
            <RefreshCw size={14} className={reports.isFetching ? "animate-spin" : ""} />
            Refresh
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatCard label="Recorded Events" value={totalEvents.toLocaleString()} tone={totalEvents ? "warn" : "ok"} />
        <StatCard label="Unique Devices" value={uniqueDevices.toLocaleString()} />
        <StatCard label="Last Seen" value={formatDate(lastSeen)} />
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-[22rem_1fr]">
        <div className={`rounded-2xl p-5 ${glassPanel}`}>
          <div className="mb-4 flex items-center gap-2">
            <AlertCircle size={18} className={Object.keys(topErrors).length ? "text-amber-400" : "text-emerald-400"} />
            <h3 className={`text-base font-semibold ${t_textHeading}`}>Top Error Types</h3>
          </div>
          {Object.keys(topErrors).length ? (
            <div className="space-y-2">
              {Object.entries(topErrors).slice(0, 12).map(([name, count]) => (
                <div key={name} className={`rounded-xl border px-3 py-2 ${t_borderLight}`}>
                  <div className="flex items-center justify-between gap-3">
                    <span className={`min-w-0 truncate text-xs font-semibold ${t_textHeading}`}>{name}</span>
                    <span className="rounded-full bg-amber-500/15 px-2 py-0.5 text-xs font-bold text-amber-400">{count}</span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <EmptyState icon={ShieldCheck} title="No extension errors" description="No recent extension error reports were found." />
          )}
        </div>

        <div className={`rounded-2xl overflow-hidden ${glassPanel}`}>
          <div className={`border-b p-4 ${t_borderLight}`}>
            <h3 className={`text-base font-semibold ${t_textHeading}`}>Latest Events</h3>
            <p className={`text-xs ${t_textMuted}`}>Newest events are shown first. Use this when rules sync but behavior looks wrong.</p>
          </div>
          <div className="max-h-[34rem] overflow-auto">
            {recentEvents.length ? (
              <table className="w-full min-w-[780px] text-left text-xs">
                <thead>
                  <tr className={`border-b ${t_borderLight} ${isDark ? "bg-slate-950/80" : "bg-white/90"}`}>
                    <th className={`p-3 font-semibold ${t_textMuted}`}>Time</th>
                    <th className={`p-3 font-semibold ${t_textMuted}`}>Type</th>
                    <th className={`p-3 font-semibold ${t_textMuted}`}>Page</th>
                    <th className={`p-3 font-semibold ${t_textMuted}`}>Device / Browser</th>
                    <th className={`p-3 font-semibold ${t_textMuted}`}>Message</th>
                  </tr>
                </thead>
                <tbody className={`divide-y ${t_borderLight}`}>
                  {recentEvents.map((event, index) => (
                    <tr key={`${event.ts || "event"}-${index}`} className={t_rowHover}>
                      <td className={`p-3 whitespace-nowrap ${t_textMuted}`}>{formatDate(event.ts || event.created_at)}</td>
                      <td className="p-3">
                        <span className="rounded-full border border-rose-500/30 bg-rose-500/10 px-2 py-0.5 text-[10px] font-bold uppercase text-rose-400">
                          {event.type || event.error_type || "error"}
                        </span>
                      </td>
                      <td className={`p-3 max-w-[220px] truncate font-mono ${t_textMuted}`}>{event.url || event.page || event.host || "-"}</td>
                      <td className={`p-3 max-w-[180px] truncate ${t_textMuted}`}>
                        {event.device_id || event.deviceId || "-"} {event.browser ? `/ ${event.browser}` : ""}
                      </td>
                      <td className={`p-3 max-w-[320px] break-words ${t_textHeading}`}>{event.message || event.error || event.reason || "-"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="p-8">
                <EmptyState icon={ShieldCheck} title="No events yet" description="Extension diagnostics will appear here after clients report them." />
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

ExtensionHealthPanel.propTypes = {
  showToast: PropTypes.func,
};
