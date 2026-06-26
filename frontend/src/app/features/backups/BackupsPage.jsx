import React, { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Cloud, CloudDownload, CloudUpload, Database, HardDrive, RefreshCw, Save, Send, ShieldCheck } from "lucide-react";
import {
  backupQueryKeys,
  createBackup,
  getBackupHealth,
  getBackupRemoteConfig,
  listBackups,
  pullLatestRemoteBackup,
  restoreBackup,
  restoreLatestRemoteBackup,
  saveBackupRemoteConfig,
  syncLatestBackupsToRemote,
  testBackupTarget,
} from "../../../api/backups";
import { useConfirm } from "../../components/ConfirmDialog";
import { EmptyState } from "../../components/EmptyState";
import { useThemeContext } from "../../context/ThemeContext";
import { usePageTitle } from "../../hooks/usePageTitle";

const BACKUP_TYPES = [
  {
    type: "full",
    title: "Full Snapshot",
    description: "Complete backend snapshot for migration or disaster recovery.",
  },
  {
    type: "system",
    title: "System Data",
    description: "CAPTCHA models, routes, mappings, platform settings, and runtime assets.",
  },
  {
    type: "users",
    title: "User Data",
    description: "Accounts, subscriptions, payments, usage, and sync blobs.",
  },
];

const TARGETS = [
  {
    target: "telegram",
    title: "Telegram Dump",
    description: "Uploads latest backup files to the configured group or channel.",
    icon: Send,
  },
  {
    target: "rclone",
    title: "rclone / Google Drive",
    description: "Uses the configured rclone remote and folder path.",
    icon: CloudUpload,
  },
  {
    target: "r2",
    title: "Cloudflare R2",
    description: "Uses a private R2 bucket through an S3-compatible rclone remote.",
    icon: Cloud,
  },
];

const initialConfig = {
  backup_size_cap_mb: "2048",
  rclone_remote: "",
  rclone_path: "eazyfill-backups",
  rclone_config: "",
  telegram_chat_id: "",
  telegram_bot_token: "",
  cloudflare_r2_remote: "cloudflare-r2",
  cloudflare_r2_account_id: "",
  cloudflare_r2_bucket: "",
  cloudflare_r2_prefix: "eazyfill-backups",
  cloudflare_r2_access_key_id: "",
  cloudflare_r2_secret_access_key: "",
};

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

function backupItems(data, type) {
  return Array.isArray(data?.[type]) ? data[type] : [];
}

function latestBackup(data, type) {
  return backupItems(data, type)[0] || null;
}

function actionNotice(request, result) {
  if (request.action === "remote-sync") {
    const failed = (result.results || []).filter((item) => item.success === false);
    if (failed.length) {
      return {
        tone: "warning",
        text: `${request.target} sync finished with ${failed.length} issue(s): ${failed.map((item) => `${item.category}: ${item.error || "failed"}`).join("; ")}`,
      };
    }
    return { tone: "success", text: `${request.target} latest backups synced.` };
  }
  if (result?.success === false || result?.ok === false || result?.status === "failed") {
    return { tone: "error", text: result.error || "Backup action failed." };
  }
  const typeLabel = BACKUP_TYPES.find((item) => item.type === request.type)?.title || request.type;
  const labels = {
    create: `${typeLabel} created.`,
    "restore-local": `${typeLabel} restored from local file.`,
    "remote-pull": `${typeLabel} pulled from ${request.target}.`,
    "remote-restore": `${typeLabel} restored from ${request.target}.`,
    "save-config": "Backup configuration saved.",
    "test-target": `${request.target} target test completed.`,
  };
  return { tone: "success", text: labels[request.action] || "Backup action completed." };
}

export function BackupsPage() {
  usePageTitle("Backups");
  const {
    isDark,
    t_textHeading,
    t_textMuted,
    glassPanel,
    glassButton,
    solidButton,
    glassInput,
    smallGlassInput,
  } = useThemeContext();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  const [notice, setNotice] = useState(null);
  const [form, setForm] = useState(initialConfig);

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
  const config = useQuery({
    queryKey: [...backupQueryKeys.all, "remote-config"],
    queryFn: getBackupRemoteConfig,
    staleTime: 30_000,
  });

  useEffect(() => {
    if (!config.data) return;
    setForm((current) => ({
      ...current,
      backup_size_cap_mb: String(config.data.backup_size_cap_mb || 2048),
      rclone_remote: config.data.rclone_remote || "",
      rclone_path: config.data.rclone_path || "eazyfill-backups",
      rclone_config: config.data.rclone_config || "",
      telegram_chat_id: config.data.telegram_chat_id || "",
      cloudflare_r2_remote: config.data.cloudflare_r2_remote || "cloudflare-r2",
      cloudflare_r2_account_id: config.data.cloudflare_r2_account_id || "",
      cloudflare_r2_bucket: config.data.cloudflare_r2_bucket || "",
      cloudflare_r2_prefix: config.data.cloudflare_r2_prefix || "eazyfill-backups",
    }));
  }, [config.data]);

  const latestAny = useMemo(() => {
    return BACKUP_TYPES
      .flatMap((item) => backupItems(backups.data, item.type).map((backup) => ({ ...backup, type: item.type })))
      .sort((a, b) => new Date(b.created || 0) - new Date(a.created || 0))[0] || null;
  }, [backups.data]);

  const tableBorder = isDark ? "border-white/[0.07]" : "border-slate-200";
  const busyText = isDark ? "text-slate-400" : "text-slate-500";

  const mutation = useMutation({
    mutationFn: async (request) => {
      if (request.action === "create") return createBackup(request.type);
      if (request.action === "restore-local") return restoreBackup({ type: request.type, filename: request.filename, confirm: request.confirm });
      if (request.action === "remote-sync") return syncLatestBackupsToRemote(request.target);
      if (request.action === "remote-pull") return pullLatestRemoteBackup({ type: request.type, target: request.target });
      if (request.action === "remote-restore") return restoreLatestRemoteBackup({ type: request.type, target: request.target, confirm: request.confirm });
      if (request.action === "save-config") return saveBackupRemoteConfig(request.payload);
      if (request.action === "test-target") return testBackupTarget(request.target);
      throw new Error("Unknown backup action");
    },
    onSuccess: (result, request) => {
      setNotice(actionNotice(request, result));
      queryClient.invalidateQueries({ queryKey: backupQueryKeys.all });
    },
    onError: (error) => setNotice({ tone: "error", text: error.message || "Backup action failed." }),
  });

  const busy = mutation.isPending;

  const updateForm = (key, value) => {
    setForm((current) => ({ ...current, [key]: value }));
  };

  const saveConfig = () => {
    const payload = { ...form };
    if (!payload.telegram_bot_token) delete payload.telegram_bot_token;
    if (!payload.cloudflare_r2_access_key_id) delete payload.cloudflare_r2_access_key_id;
    if (!payload.cloudflare_r2_secret_access_key) delete payload.cloudflare_r2_secret_access_key;
    mutation.mutate({ action: "save-config", payload });
  };

  const requestRestore = async ({ type, filename = "", target = "", remote = false }) => {
    if (type === "full") {
      const phrase = window.prompt(`Type RESTORE FULL SNAPSHOT to restore ${remote ? `the latest ${target} full snapshot` : filename}.`);
      if (phrase !== "RESTORE FULL SNAPSHOT") {
        setNotice({ tone: "warning", text: "Full snapshot restore cancelled." });
        return;
      }
      mutation.mutate({
        action: remote ? "remote-restore" : "restore-local",
        type,
        target,
        filename,
        confirm: phrase,
      });
      return;
    }
    const approved = await confirm({
      title: remote ? `Restore latest from ${target}` : "Restore local backup",
      message: `Restore ${BACKUP_TYPES.find((item) => item.type === type)?.title || type} now?`,
      details: [
        remote ? `Source: latest ${target} copy` : `Source: ${filename}`,
        "Matching server data will be overwritten.",
      ],
      confirmLabel: "Restore Backup",
      tone: "warning",
    });
    if (!approved) return;
    mutation.mutate({
      action: remote ? "remote-restore" : "restore-local",
      type,
      target,
      filename,
    });
  };

  return (
    <div className="space-y-6">
      <header className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className={`text-xs font-bold uppercase ${t_textMuted}`}>Operations</p>
          <h1 className={`mt-1 text-2xl font-bold ${t_textHeading}`}>Backups</h1>
          <p className={`mt-1 text-sm ${t_textMuted}`}>Full snapshot, system data, and user data backup/restore for server recovery.</p>
        </div>
        <button type="button" className={glassButton} onClick={() => { backups.refetch(); health.refetch(); config.refetch(); }} disabled={busy || backups.isFetching || config.isFetching}>
          <RefreshCw size={15} className={backups.isFetching || config.isFetching ? "animate-spin" : ""} />
          Refresh
        </button>
      </header>

      {notice && (
        <div className={`rounded-xl border px-4 py-3 text-sm ${
          notice.tone === "error"
            ? "border-rose-500/30 bg-rose-500/10 text-rose-400"
            : notice.tone === "warning"
              ? "border-amber-500/30 bg-amber-500/10 text-amber-400"
              : "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
        }`}>
          {notice.text}
        </div>
      )}

      <section className={`grid grid-cols-1 gap-3 border p-5 md:grid-cols-4 ${glassPanel}`}>
        <div>
          <div className={`text-xs font-semibold uppercase ${t_textMuted}`}>Database</div>
          <div className={`mt-1 text-sm font-bold ${t_textHeading}`}>{health.data?.db_type || "Loading"}</div>
        </div>
        <div>
          <div className={`text-xs font-semibold uppercase ${t_textMuted}`}>Latest Backup</div>
          <div className={`mt-1 text-sm font-bold ${t_textHeading}`}>{latestAny ? formatDate(latestAny.created) : "None"}</div>
        </div>
        <div>
          <div className={`text-xs font-semibold uppercase ${t_textMuted}`}>Retention</div>
          <div className={`mt-1 text-sm font-bold ${t_textHeading}`}>{form.backup_size_cap_mb || 2048} MB cap</div>
          <div className={`text-xs ${t_textMuted}`}>Rotate at 90%</div>
        </div>
        <div>
          <div className={`text-xs font-semibold uppercase ${t_textMuted}`}>Folder</div>
          <div className={`mt-1 truncate text-sm font-bold ${t_textHeading}`} title={health.data?.backup_dir || ""}>{health.data?.backup_dir || "-"}</div>
        </div>
      </section>

      <section className={`overflow-hidden border ${glassPanel}`}>
        <div className={`flex items-center justify-between gap-3 border-b p-5 ${tableBorder}`}>
          <div className="flex items-center gap-3">
            <Database size={19} className="text-emerald-400" />
            <div>
              <h2 className={`text-base font-semibold ${t_textHeading}`}>Local Backup Sets</h2>
              <p className={`text-xs ${t_textMuted}`}>Create and restore the three supported recovery scopes.</p>
            </div>
          </div>
        </div>

        {backups.error ? (
          <div className="p-5 text-sm text-rose-400">{backups.error.message || "Backups could not be loaded."}</div>
        ) : (
          <div className={`grid grid-cols-1 divide-y xl:grid-cols-3 xl:divide-x xl:divide-y-0 ${isDark ? "divide-white/[0.07]" : "divide-slate-200"}`}>
            {BACKUP_TYPES.map((configItem) => {
              const latest = latestBackup(backups.data, configItem.type);
              return (
                <div className="space-y-4 p-5" key={configItem.type}>
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <h3 className={`text-sm font-semibold ${t_textHeading}`}>{configItem.title}</h3>
                      <p className={`mt-1 text-xs ${t_textMuted}`}>{configItem.description}</p>
                    </div>
                    <HardDrive size={18} className={t_textMuted} />
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <button type="button" className={solidButton} disabled={busy} onClick={() => mutation.mutate({ action: "create", type: configItem.type })}>
                      Create
                    </button>
                    <button type="button" className={glassButton} disabled={busy || !latest} onClick={() => requestRestore({ type: configItem.type, filename: latest?.name || "" })}>
                      Restore Local
                    </button>
                  </div>
                  <div className={`border p-3 text-xs ${tableBorder}`}>
                    {latest ? (
                      <div className="space-y-1">
                        <div className={`font-mono ${t_textHeading}`}>{latest.name}</div>
                        <div className={t_textMuted}>{formatBytes(latest.size)} - {formatDate(latest.created)}</div>
                      </div>
                    ) : (
                      <span className={t_textMuted}>No local backup found.</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      <section className={`overflow-hidden border ${glassPanel}`}>
        <div className={`flex items-center justify-between gap-3 border-b p-5 ${tableBorder}`}>
          <div className="flex items-center gap-3">
            <ShieldCheck size={19} className="text-sky-400" />
            <div>
              <h2 className={`text-base font-semibold ${t_textHeading}`}>Remote Backup Targets</h2>
              <p className={`text-xs ${t_textMuted}`}>Sync latest local backups, pull latest copies, and restore from Telegram, rclone/GDrive, or R2.</p>
            </div>
          </div>
        </div>
        <div className={`grid grid-cols-1 divide-y xl:grid-cols-3 xl:divide-x xl:divide-y-0 ${isDark ? "divide-white/[0.07]" : "divide-slate-200"}`}>
          {TARGETS.map((targetItem) => {
            const Icon = targetItem.icon;
            return (
              <div className="space-y-4 p-5" key={targetItem.target}>
                <div className="flex items-start gap-3">
                  <Icon size={18} className="text-[#8B5CF6]" />
                  <div>
                    <h3 className={`text-sm font-semibold ${t_textHeading}`}>{targetItem.title}</h3>
                    <p className={`mt-1 text-xs ${t_textMuted}`}>{targetItem.description}</p>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  {targetItem.target !== "telegram" ? (
                    <button type="button" className={glassButton} disabled={busy} onClick={() => mutation.mutate({ action: "test-target", target: targetItem.target })}>
                      Test
                    </button>
                  ) : null}
                  <button type="button" className={solidButton} disabled={busy} onClick={() => mutation.mutate({ action: "remote-sync", target: targetItem.target })}>
                    <CloudUpload size={15} />
                    Backup Latest
                  </button>
                </div>
                <div className="space-y-2">
                  {BACKUP_TYPES.map((backupType) => (
                    <div className={`flex flex-wrap items-center justify-between gap-2 border px-3 py-2 text-xs ${tableBorder}`} key={`${targetItem.target}-${backupType.type}`}>
                      <span className={`font-semibold ${t_textHeading}`}>{backupType.title}</span>
                      <div className="flex gap-2">
                        <button type="button" className={glassButton} disabled={busy} onClick={() => mutation.mutate({ action: "remote-pull", target: targetItem.target, type: backupType.type })}>
                          <CloudDownload size={14} />
                          Pull
                        </button>
                        <button type="button" className={glassButton} disabled={busy} onClick={() => requestRestore({ type: backupType.type, target: targetItem.target, remote: true })}>
                          Restore
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <section className={`overflow-hidden border ${glassPanel}`}>
        <div className={`flex items-center justify-between gap-3 border-b p-5 ${tableBorder}`}>
          <div>
            <h2 className={`text-base font-semibold ${t_textHeading}`}>Backup Configuration</h2>
            <p className={`text-xs ${t_textMuted}`}>Secrets are write-only. Leave secret fields blank to keep the saved value.</p>
          </div>
          <button type="button" className={solidButton} onClick={saveConfig} disabled={busy}>
            <Save size={15} />
            Save
          </button>
        </div>
        {config.error ? (
          <div className="p-5 text-sm text-rose-400">{config.error.message || "Backup configuration could not be loaded."}</div>
        ) : (
          <div className="grid grid-cols-1 gap-5 p-5 xl:grid-cols-3">
            <div className="space-y-3">
              <h3 className={`text-sm font-semibold ${t_textHeading}`}>Retention and rclone</h3>
              <label className={`block text-xs ${t_textMuted}`}>
                Max target size (MB)
                <input className={`mt-1 ${smallGlassInput}`} value={form.backup_size_cap_mb} onChange={(event) => updateForm("backup_size_cap_mb", event.target.value)} />
              </label>
              <label className={`block text-xs ${t_textMuted}`}>
                rclone remote
                <input className={`mt-1 ${smallGlassInput}`} value={form.rclone_remote} onChange={(event) => updateForm("rclone_remote", event.target.value)} placeholder="gdrive" />
              </label>
              <label className={`block text-xs ${t_textMuted}`}>
                rclone path
                <input className={`mt-1 ${smallGlassInput}`} value={form.rclone_path} onChange={(event) => updateForm("rclone_path", event.target.value)} placeholder="eazyfill-backups" />
              </label>
              <textarea
                className={`${glassInput} min-h-[150px] font-mono text-xs`}
                value={form.rclone_config}
                onChange={(event) => updateForm("rclone_config", event.target.value)}
                placeholder="[gdrive]\ntype = drive"
              />
              <div className={`text-xs ${busyText}`}>Binary: {config.data?.rclone_binary || "not found"}</div>
            </div>

            <div className="space-y-3">
              <h3 className={`text-sm font-semibold ${t_textHeading}`}>Telegram Dump</h3>
              <label className={`block text-xs ${t_textMuted}`}>
                Chat ID
                <input className={`mt-1 ${smallGlassInput}`} value={form.telegram_chat_id} onChange={(event) => updateForm("telegram_chat_id", event.target.value)} placeholder="-100..." />
              </label>
              <label className={`block text-xs ${t_textMuted}`}>
                Bot token
                <input className={`mt-1 ${smallGlassInput}`} value={form.telegram_bot_token} onChange={(event) => updateForm("telegram_bot_token", event.target.value)} placeholder={config.data?.telegram_bot_token_set ? "Stored - leave blank to keep" : "Paste bot token"} />
              </label>
              <div className={`border p-3 text-xs ${tableBorder}`}>
                {config.data?.telegram_bot_token_set ? "Bot token stored." : "Bot token not stored."}
                {config.data?.telegram_last_error ? <div className="mt-2 text-rose-400">{config.data.telegram_last_error}</div> : null}
              </div>
            </div>

            <div className="space-y-3">
              <h3 className={`text-sm font-semibold ${t_textHeading}`}>Cloudflare R2</h3>
              <input className={smallGlassInput} value={form.cloudflare_r2_remote} onChange={(event) => updateForm("cloudflare_r2_remote", event.target.value)} placeholder="cloudflare-r2" />
              <input className={smallGlassInput} value={form.cloudflare_r2_account_id} onChange={(event) => updateForm("cloudflare_r2_account_id", event.target.value)} placeholder="Account ID" />
              <input className={smallGlassInput} value={form.cloudflare_r2_bucket} onChange={(event) => updateForm("cloudflare_r2_bucket", event.target.value)} placeholder="Bucket" />
              <input className={smallGlassInput} value={form.cloudflare_r2_prefix} onChange={(event) => updateForm("cloudflare_r2_prefix", event.target.value)} placeholder="Prefix" />
              <input className={smallGlassInput} value={form.cloudflare_r2_access_key_id} onChange={(event) => updateForm("cloudflare_r2_access_key_id", event.target.value)} placeholder={config.data?.cloudflare_r2_access_key_set ? "Access key stored" : "Access key ID"} />
              <input className={smallGlassInput} value={form.cloudflare_r2_secret_access_key} onChange={(event) => updateForm("cloudflare_r2_secret_access_key", event.target.value)} placeholder={config.data?.cloudflare_r2_secret_key_set ? "Secret stored" : "Secret access key"} />
              {config.data?.cloudflare_r2_last_error ? <div className="text-xs text-rose-400">{config.data.cloudflare_r2_last_error}</div> : null}
            </div>
          </div>
        )}
      </section>

      {!backups.isLoading && !backupItems(backups.data, "full").length && !backupItems(backups.data, "system").length && !backupItems(backups.data, "users").length ? (
        <EmptyState icon={Database} title="No recovery files yet" description="Create a full snapshot, system backup, or user backup before testing remote restore." />
      ) : null}
    </div>
  );
}
