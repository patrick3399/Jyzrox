import { apiFetch } from './client'

import type { PluginInfo, PluginServiceHealth } from '../types'

// ── Plugins ──────────────────────────────────────────────────────────

export const plugins = {
  list: () => apiFetch<{ plugins: PluginInfo[] }>('/api/plugins/'),
  health: () =>
    apiFetch<{ services: Record<string, PluginServiceHealth> }>('/api/plugins/health'),
}

export const processing = {
  processImage: (imageId: number, data: { processor_id: string; model: string; scale: number }) =>
    apiFetch<{ status: string; job_id: string; image_id: number }>(`/api/process/images/${imageId}`, {
      method: 'POST',
      body: JSON.stringify(data),
    }),
}
