import { apiFetch, qs } from './client'

import type { DedupStats, DedupReviewResponse, DedupScanProgress } from '../types'

// ── Dedup ────────────────────────────────────────────────────────────

export const dedup = {
  getStats: () => apiFetch<DedupStats>('/api/dedup/stats'),

  getReview: (params: { relationship?: string; cursor?: string } = {}) =>
    apiFetch<DedupReviewResponse>(`/api/dedup/review${qs(params as Record<string, unknown>)}`),

  keep: (id: number, keepSha: string) =>
    apiFetch<{ status: string }>(`/api/dedup/review/${id}/keep`, {
      method: 'POST',
      body: JSON.stringify({ keep_sha: keepSha }),
    }),

  whitelist: (id: number) =>
    apiFetch<{ status: string }>(`/api/dedup/review/${id}/whitelist`, { method: 'POST' }),

  dismiss: (id: number) =>
    apiFetch<{ status: string }>(`/api/dedup/review/${id}`, { method: 'DELETE' }),

  getScanProgress: () => apiFetch<DedupScanProgress>('/api/dedup/scan/progress'),

  startScan: (mode: 'reset' | 'pending') =>
    apiFetch<{ status: string }>('/api/dedup/scan/start', {
      method: 'POST',
      body: JSON.stringify({ mode }),
    }),

  sendSignal: (signal: 'pause' | 'resume' | 'stop') =>
    apiFetch<{ status: string }>('/api/dedup/scan/signal', {
      method: 'POST',
      body: JSON.stringify({ signal }),
    }),
}
