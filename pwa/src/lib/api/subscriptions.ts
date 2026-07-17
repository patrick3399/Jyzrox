import { apiFetch, qs } from './client'

import type { DownloadJob, Subscription, SubscriptionGroup } from '../types'

// ── Subscriptions ────────────────────────────────────────────────────

export const subscriptions = {
  list: (params: { source?: string; enabled?: boolean; limit?: number; offset?: number } = {}) =>
    apiFetch<{ subscriptions: Subscription[]; total: number }>(
      `/api/subscriptions/${qs(params as Record<string, unknown>)}`,
    ),

  create: (data: {
    url: string
    name?: string
    cron_expr?: string
    auto_download?: boolean
    group_id?: number | null
    download_options?: Record<string, unknown>
  }) =>
    apiFetch<{ status: string; id: number; source: string | null; duplicate?: boolean }>(
      '/api/subscriptions/',
      {
        method: 'POST',
        body: JSON.stringify(data),
      },
    ),

  get: (id: number) => apiFetch<Subscription>(`/api/subscriptions/${id}`),

  update: (
    id: number,
    data: {
      name?: string
      enabled?: boolean
      auto_download?: boolean
      cron_expr?: string
      group_id?: number | null
      download_options?: Record<string, unknown>
    },
  ) =>
    apiFetch<{ status: string }>(`/api/subscriptions/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),

  delete: (id: number) =>
    apiFetch<{ status: string }>(`/api/subscriptions/${id}`, {
      method: 'DELETE',
    }),

  check: (id: number) =>
    apiFetch<{ status: string }>(`/api/subscriptions/${id}/check`, {
      method: 'POST',
    }),

  backfill: (id: number) =>
    apiFetch<{ status: string; mode?: string }>(`/api/subscriptions/${id}/backfill`, {
      method: 'POST',
    }),

  jobs: (id: number, limit = 10) =>
    apiFetch<{ jobs: DownloadJob[] }>(`/api/subscriptions/${id}/jobs${qs({ limit })}`),
}

// ── Subscription Groups ──────────────────────────────────────────────

export const subscriptionGroups = {
  list: () => apiFetch<{ groups: SubscriptionGroup[] }>('/api/subscription-groups/'),

  create: (data: { name: string; schedule?: string; concurrency?: number; priority?: number }) =>
    apiFetch<{ status: string; id: number }>('/api/subscription-groups/', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  get: (id: number) => apiFetch<SubscriptionGroup>(`/api/subscription-groups/${id}`),

  update: (
    id: number,
    data: {
      name?: string
      schedule?: string
      concurrency?: number
      priority?: number
      enabled?: boolean
    },
  ) =>
    apiFetch<{ status: string }>(`/api/subscription-groups/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),

  delete: (id: number) =>
    apiFetch<{ status: string }>(`/api/subscription-groups/${id}`, {
      method: 'DELETE',
    }),

  run: (id: number) =>
    apiFetch<{ status: string }>(`/api/subscription-groups/${id}/run`, {
      method: 'POST',
    }),

  pause: (id: number) =>
    apiFetch<{ status: string }>(`/api/subscription-groups/${id}/pause`, {
      method: 'POST',
    }),

  resume: (id: number) =>
    apiFetch<{ status: string }>(`/api/subscription-groups/${id}/resume`, {
      method: 'POST',
    }),

  bulkMove: (sub_ids: number[], group_id: number | null) =>
    apiFetch<{ status: string; updated: number }>('/api/subscriptions/bulk-move', {
      method: 'POST',
      body: JSON.stringify({ sub_ids, group_id }),
    }),
}
