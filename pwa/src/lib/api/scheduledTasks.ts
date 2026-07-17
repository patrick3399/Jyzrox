import { apiFetch } from './client'

import type { ScheduledTask, DatabaseBackup } from '../types'

// ── Scheduled Tasks / Backups ────────────────────────────────────────

export const scheduledTasks = {
  list: () => apiFetch<{ tasks: ScheduledTask[] }>('/api/scheduled-tasks/'),

  update: (taskId: string, data: { enabled?: boolean; cron_expr?: string }) =>
    apiFetch<{ status: string }>(`/api/scheduled-tasks/${taskId}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),

  run: (taskId: string) =>
    apiFetch<{ status: string }>(`/api/scheduled-tasks/${taskId}/run`, {
      method: 'POST',
    }),
}

export const backups = {
  list: () => apiFetch<{ backups: DatabaseBackup[]; path: string }>('/api/admin/backups/'),

  run: () =>
    apiFetch<{ status: string; job: string }>('/api/admin/backups/run', {
      method: 'POST',
    }),

  delete: (backupId: string) =>
    apiFetch<{ status: string; deleted: string[] }>(
      `/api/admin/backups/${encodeURIComponent(backupId)}`,
      {
        method: 'DELETE',
      },
    ),
}
