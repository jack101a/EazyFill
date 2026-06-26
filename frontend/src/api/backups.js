import { adminApi, apiGet, apiPostJson } from "./client";

export const backupQueryKeys = {
  all: ["backups"],
  list: ["backups", "list"],
};

export function listBackups() {
  return apiGet(adminApi("/backups/list"));
}

export function getBackupHealth() {
  return apiGet(adminApi("/system/backup-health"));
}

export function createBackup(type) {
  return apiPostJson(adminApi(`/backups/${type}`), {});
}

export function restoreBackup({ type, filename, confirm = "" }) {
  return apiPostJson(adminApi("/backups/restore"), { type, filename, confirm });
}

export function getBackupRemoteConfig() {
  return apiGet(adminApi("/backups/remote-config"));
}

export function saveBackupRemoteConfig(payload) {
  return apiPostJson(adminApi("/backups/remote-config"), payload);
}

export function testBackupTarget(target = "rclone") {
  return apiPostJson(adminApi("/backups/test-rclone"), { target });
}

export function syncLatestBackupsToRemote(target = "rclone") {
  if (target === "telegram") {
    return apiPostJson(adminApi("/backups/telegram-sync"), {});
  }
  return apiPostJson(adminApi("/backups/rclone-sync"), { target });
}

export function pullLatestRemoteBackup({ type, target = "rclone" }) {
  if (target === "telegram") {
    return apiPostJson(adminApi("/backups/telegram-pull-latest"), { type });
  }
  return apiPostJson(adminApi("/backups/rclone-pull-latest"), { type, target });
}

export function restoreLatestRemoteBackup({ type, target = "rclone", confirm = "" }) {
  if (target === "telegram") {
    return apiPostJson(adminApi("/backups/telegram-restore-latest"), { type, confirm });
  }
  return apiPostJson(adminApi("/backups/rclone-restore-latest"), { type, target, confirm });
}
