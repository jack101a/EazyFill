import React, { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, CloudDownload, CloudUpload, Database, Gauge, HardDrive, RefreshCw, Smartphone, Webhook } from "lucide-react";
import {
  backupQueryKeys,
  createBackup,
  getBackupHealth,
  listBackups,
  pullLatestCloudBackup,
  restoreBackup,
  restoreLatestCloudBackup,
  syncLatestBackupsToCloud,
} from "../../../api/backups";
import { fetchEazyFillAbuse, eazyfillQueryKeys } from "../../../api/eazyfill";
import { usePageTitle } from "../../hooks/usePageTitle";
import { useThemeContext } from "../../context/ThemeContext";
import { EmptyState } from "../../components/EmptyState";
import { useConfirm } from "../../components/ConfirmDialog";

function formatDate(value) {
  return value ? new Date(value).toLocaleString() : "-";
}

function formatBytes(value) {
  const bytes = Number(value || 0);
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  let amount = bytes;
  let unit = 0;
  while (amount >= 1024 && unit < units.length - 1) {
    amount /= 1024;
    unit += 1;
  }
  return `${amount.toFixed(amount >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

const BACKUP_TYPES = [
  { type: "postgres", title: "Database", description: "PostgreSQL dump for full database recovery." },
  { type: "system", title: "System Assets", description: "Models, routes, mappings, and system files." },
  { type: "users", title: "Users", description: "Accounts, plans, payments, usage, and cloud sync rows." },
];

function backupItems(data, type) {
  return Array.isArray(data?.[type]) ? data[type] : [];
}

function latestSplitBackup(data) {
  return BACKUP_TYPES
    .flatMap((config) => backupItems(data, config.type).map((item) => ({ ...item, type: config.type })))
    .sort((a, b) => new Date(b.created || 0) - new Date(a.created || 0))[0] || null;
}

function backupNotice(request, result) {
  if (request.action === "cloud-sync") {
    const failed = (result.results || []).filter((item) => item.success === false);
    if (failed.length) {
      return { tone: "warning", text: `Cloud sync finished with ${failed.length} issue(s): ${failed.map((item) => `${item.category}: ${item.error || "failed"}`).join("; ")}` };
    }
    return { tone: "success", text: "Latest backups synced to cloud." };
  }
  if (result?.success === false || result?.ok === false) {
    return { tone: "error", text: result.error || "Backup action failed." };
  }
  const typeLabel = BACKUP_TYPES.find((item) => item.type === request.type)?.title || request.type;
  const labels = {
    create: `${typeLabel} backup created.`,
    "restore-local": `${typeLabel} backup restored from local copy.`,
    pull: `${typeLabel} backup pulled from cloud.`,
    "restore-cloud": `${typeLabel} backup restored from cloud latest copy.`,
  };
  return { tone: "success", text: labels[request.action] || "Backup action completed." };
}

function BackupControlPanel() {
  const { isDark, t_textHeading, t_textMuted, glassPanel, glassButton } = useThemeContext();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState(null);
  const backups = useQuery({
    queryKey: backupQueryKeys.list,
    queryFn: listBackups,
    staleTime: 15_000,
  });
  const health = useQuery({
    queryKey: [...backupQueryKeys.all, "health"],
    queryFn: getBackupHealth,
    staleTime: 30_000,
  });
  const tableBorder = isDark ? "border-white/[0.07]" : "border-slate-200";
  const splitCount = BACKUP_TYPES.reduce((total, config) => total + backupItems(backups.data, config.type).length, 0);
  const latestSplit = latestSplitBackup(backups.data);
  const mutation = useMutation({
    mutationFn: async (request) => {
      if (request.action === "create") return createBackup(request.type);
      if (request.action === "restore-local") return restoreBackup({ type: request.type, filename: request.filename, confirm: request.confirm });
      if (request.action === "cloud-sync") return syncLatestBackupsToCloud();
      if (request.action === "pull") return pullLatestCloudBackup(request.type);
      if (request.action === "restore-cloud") return restoreLatestCloudBackup({ type: request.type, confirm: request.confirm });
      throw new Error("Unknown backup action");
    },
    onSuccess: (result, request) => {
      const nextNotice = backupNotice(request, result);
      setNotice(nextNotice);
      queryClient.invalidateQueries({ queryKey: backupQueryKeys.all });
    },
    onError: (error) => setNotice({ tone: "error", text: error.message || "Backup action failed." }),
  });
  const busy = mutation.isPending;

  const requestRestore = async ({ type, filename = "", cloud = false }) => {
    const title = cloud ? "Restore latest cloud backup" : "Restore local backup";
    if (type === "postgres") {
      const phrase = window.prompt(`Type RESTORE POSTGRES to restore the ${cloud ? "latest cloud database backup" : filename}.`);
      if (phrase !== "RESTORE POSTGRES") {
        setNotice({ tone: "warning", text: "Database restore cancelled." });
        return;
      }
      mutation.mutate({ action: cloud ? "restore-cloud" : "restore-local", type, filename, confirm: phrase });
      return;
    }
    const approved = await confirm({
      title,
      message: `Restore ${type} backup now?`,
      details: [cloud ? "Source: latest configured cloud copy" : `Source: ${filename}`, "This overwrites matching local server data."],
      confirmLabel: "Restore Backup",
      tone: "warning",
    });
    if (!approved) return;
    mutation.mutate({ action: cloud ? "restore-cloud" : "restore-local", type, filename });
  };

  return (
    <section className={`overflow-hidden border ${glassPanel}`}>
      <div className={`flex flex-col gap-3 border-b p-5 sm:flex-row sm:items-center sm:justify-between ${tableBorder}`}>
        <div className="flex items-center gap-3">
          <Database size={19} className="text-emerald-400" />
          <div>
            <h2 className={`text-base font-semibold ${t_textHeading}`}>Database Backup / Restore</h2>
            <p className={`text-xs ${t_textMuted}`}>Create local recovery files, sync latest copies to cloud, and restore split backups.</p>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" className={glassButton} onClick={() => backups.refetch()} disabled={backups.isFetching || busy}>
            <RefreshCw size={15} className={backups.isFetching ? "animate-spin" : ""} />
            Refresh
          </button>
          <button type="button" className={glassButton} onClick={() => mutation.mutate({ action: "cloud-sync" })} disabled={busy}>
            <CloudUpload size={15} />
            Sync Latest to Cloud
          </button>
        </div>
      </div>

      {notice && (
        <div className={`mx-5 mt-5 rounded-xl border px-3 py-2 text-xs ${
          notice.tone === "error"
            ? "border-rose-500/30 bg-rose-500/10 text-rose-400"
            : notice.tone === "warning"
              ? "border-amber-500/30 bg-amber-500/10 text-amber-400"
              : "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
        }`}>
          {notice.text}
        </div>
      )}

      <div className={`grid grid-cols-1 gap-3 border-b p-5 text-xs sm:grid-cols-2 xl:grid-cols-4 ${tableBorder}`}>
        <div>
          <div className={`font-semibold ${t_textHeading}`}>Automated scheduler</div>
          <div className={t_textMuted}>Enabled by backend loop; interval defaults to 6h</div>
        </div>
        <div>
          <div className={`font-semibold ${t_textHeading}`}>Database</div>
          <div className={t_textMuted}>{health.data?.db_type || "Loading..."}</div>
        </div>
        <div>
          <div className={`font-semibold ${t_textHeading}`}>Local split backups</div>
          <div className={t_textMuted}>{splitCount} files{latestSplit ? ` · latest ${formatDate(latestSplit.created)}` : ""}</div>
        </div>
        <div>
          <div className={`font-semibold ${t_textHeading}`}>Server folder</div>
          <div className={`truncate ${t_textMuted}`} title={health.data?.backup_dir || ""}>{health.data?.backup_dir || "-"}</div>
        </div>
      </div>

      {backups.error ? (
        <div className="p-5 text-sm text-rose-400">{backups.error.message || "Backups could not be loaded."}</div>
      ) : (
        <div className={`grid grid-cols-1 divide-y xl:grid-cols-3 xl:divide-x xl:divide-y-0 ${isDark ? "divide-white/[0.07]" : "divide-slate-200"}`}>
          {BACKUP_TYPES.map((config) => {
            const items = backupItems(backups.data, config.type);
            const latest = items[0] || null;
            return (
              <div className="space-y-4 p-5" key={config.type}>
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className={`text-sm font-semibold ${t_textHeading}`}>{config.title}</h3>
                    <p className={`mt-1 text-xs ${t_textMuted}`}>{config.description}</p>
                  </div>
                  <HardDrive size={18} className={t_textMuted} />
                </div>
                <div className="flex flex-wrap gap-2">
                  <button type="button" className={glassButton} disabled={busy} onClick={() => mutation.mutate({ action: "create", type: config.type })}>
                    Create
                  </button>
                  <button type="button" className={glassButton} disabled={busy || !latest} onClick={() => requestRestore({ type: config.type, filename: latest?.name || "" })}>
                    Restore Local
                  </button>
                </div>
                <div className={`rounded-xl border p-3 text-xs ${tableBorder}`}>
                  {latest ? (
                    <div className="space-y-1">
                      <div className={`font-mono ${t_textHeading}`}>{latest.name}</div>
                      <div className={t_textMuted}>{formatBytes(latest.size)} · {formatDate(latest.created)}</div>
                    </div>
                  ) : (
                    <span className={t_textMuted}>No local backup found.</span>
                  )}
                </div>
                <div className="flex flex-wrap gap-2">
                  <button type="button" className={glassButton} disabled={busy} onClick={() => mutation.mutate({ action: "pull", type: config.type })}>
                    <CloudDownload size={14} />
                    Pull Cloud Latest
                  </button>
                  <button type="button" className={glassButton} disabled={busy} onClick={() => requestRestore({ type: config.type, cloud: true })}>
                    Restore Cloud Latest
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
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

      <BackupControlPanel />

      <QueueSection title="Quota exhausted" description="Active cycles at or above their plan limit." icon={Gauge} count={quota.length}>
        {quota.length ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[680px] text-left text-sm">
              <thead><tr className={`border-b ${tableBorder}`}><th className="p-3">User</th><th className="p-3">Status</th><th className="p-3">Usage</th><th className="p-3">Cycle ends</th></tr></thead>
              <tbody>{quota.map((item) => <tr key={item.cycle_id} className={`border-b ${tableBorder}`}><td className="p-3">{item.name || `User #${item.user_id}`}</td><td className="p-3">{item.status}</td><td className="p-3">{item.used} / {item.limit}</td><td className="p-3">{formatDate(item.cycle_end_at)}</td></tr>)}</tbody>
            </table>
          </div>
        ) : <EmptyState icon={Gauge} title="No quota incidents" description="No active user is currently at the configured plan limit." />}
      </QueueSection>

      <QueueSection title="Multi-device sessions" description="Accounts or credentials seen on more than one active device." icon={Smartphone} count={devices.length}>
        {devices.length ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[520px] text-left text-sm">
              <thead><tr className={`border-b ${tableBorder}`}><th className="p-3">Credential ID</th><th className="p-3">User ID</th><th className="p-3">Active devices</th></tr></thead>
              <tbody>{devices.map((item) => <tr key={item.key_id} className={`border-b ${tableBorder}`}><td className="p-3 font-mono">#{item.key_id}</td><td className="p-3">#{item.user_id}</td><td className="p-3">{item.active_device_count}</td></tr>)}</tbody>
            </table>
          </div>
        ) : <EmptyState icon={Smartphone} title="No shared sessions detected" description="Active devices are within the expected account bindings." />}
      </QueueSection>

      <QueueSection title="Failed payment webhooks" description="Recent provider events that could not be processed." icon={Webhook} count={webhooks.length}>
        {webhooks.length ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[780px] text-left text-sm">
              <thead><tr className={`border-b ${tableBorder}`}><th className="p-3">Provider</th><th className="p-3">Event</th><th className="p-3">Payment</th><th className="p-3">Error</th><th className="p-3">Received</th></tr></thead>
              <tbody>{webhooks.map((item) => <tr key={item.event_id} className={`border-b ${tableBorder}`}><td className="p-3 capitalize">{item.provider}</td><td className="p-3 font-mono text-xs">{item.event_type}</td><td className="p-3">{item.payment_id ? `#${item.payment_id}` : "-"}</td><td className="p-3 text-rose-400">{item.error_message || "-"}</td><td className="p-3">{formatDate(item.received_at)}</td></tr>)}</tbody>
            </table>
          </div>
        ) : <EmptyState icon={AlertTriangle} title="No webhook failures" description="Payment provider events are processing normally." />}
      </QueueSection>
    </div>
  );
}
