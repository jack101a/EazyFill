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

export function syncLatestBackupsToCloud() {
  return apiPostJson(adminApi("/backups/rclone-sync"), {});
}

export function pullLatestCloudBackup(type) {
  return apiPostJson(adminApi("/backups/rclone-pull-latest"), { type });
}

export function restoreLatestCloudBackup({ type, confirm = "" }) {
  return apiPostJson(adminApi("/backups/rclone-restore-latest"), { type, confirm });
}
