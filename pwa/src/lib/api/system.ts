import { apiFetch } from './client'

import type { SystemHealth, SystemInfo, CacheStats, StorageInfo } from '../types'

// ── Local types ───────────────────────────────────────────────────────

export type ReconcileStatus =
  | { status: 'never_run' }
  | {
      status: string
      completed_at: string
      removed_images: number
      removed_galleries: number
      orphan_blobs_cleaned: number
    }

// ── System ────────────────────────────────────────────────────────────

export const system = {
  health: () => apiFetch<SystemHealth>('/api/system/health'),
  info: () => apiFetch<SystemInfo>('/api/system/info'),
  getCache: () => apiFetch<CacheStats>('/api/system/cache'),
  getStorage: () => apiFetch<StorageInfo>('/api/system/storage'),
  clearCache: () => apiFetch<{ deleted_keys: number }>('/api/system/cache', { method: 'DELETE' }),
  clearCacheCategory: (category: string) =>
    apiFetch<{ deleted_keys: number }>(`/api/system/cache/${category}`, { method: 'DELETE' }),
  startReconcile: () => apiFetch<{ status: string }>('/api/system/reconcile', { method: 'POST' }),
  getReconcileStatus: () => apiFetch<ReconcileStatus>('/api/system/reconcile'),
  getEvents: (
    limit = 50,
  ): Promise<{
    events: Array<{
      event_type: string
      timestamp: string
      actor_user_id: number | null
      resource_type: string | null
      resource_id: string | null
      data: Record<string, unknown>
    }>
    count: number
  }> => apiFetch(`/api/system/events?limit=${limit}`),
}
