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

export const training = {
  listLoras: () =>
    apiFetch<{
      loras: Array<{
        id: number
        dataset_id: number | null
        name: string
        file_size: number
        sha256: string
        trigger_words: string[]
        training_params: Record<string, unknown>
        created_at: string
      }>
    }>('/api/training/loras'),
  uploadLora: (form: FormData) =>
    apiFetch<{ id: number; name: string }>('/api/training/loras', { method: 'POST', body: form }),
  deleteLora: (id: number) =>
    apiFetch<{ status: string }>(`/api/training/loras/${id}`, { method: 'DELETE' }),
  importComfy: (form: FormData) =>
    apiFetch<{ status: string; gallery_id: number; image_id: number }>('/api/training/comfyui/import', {
      method: 'POST',
      body: form,
    }),
}
