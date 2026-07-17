import { apiFetch, qs } from './client'

import type { DownloadJob, JobListParams, DownloadPreview, DashboardResponse } from '../types'

// ── Download ──────────────────────────────────────────────────────────

export const download = {
  enqueue: (url: string, source?: string, options: Record<string, unknown> = {}, total?: number) =>
    apiFetch<{ job_id: string; status: string; warning?: string }>('/api/download/', {
      method: 'POST',
      body: JSON.stringify({
        url,
        ...(source && { source }),
        ...(total !== undefined && { total }),
        ...(Object.keys(options).length > 0 && { options }),
      }),
    }),

  quickDownload: (url: string) =>
    apiFetch<{ job_id: string; status: string }>('/api/download/quick', {
      method: 'POST',
      body: JSON.stringify({ url }),
    }),

  getJobs: (params: JobListParams = {}) =>
    apiFetch<{ total: number; jobs: DownloadJob[] }>(
      `/api/download/jobs${qs(params as Record<string, unknown>)}`,
    ),

  getJob: (id: string) => apiFetch<DownloadJob>(`/api/download/jobs/${id}`),

  cancelJob: (id: string) =>
    apiFetch<{ status: string }>(`/api/download/jobs/${id}`, {
      method: 'DELETE',
    }),

  clearFinishedJobs: () =>
    apiFetch<{ deleted: number }>('/api/download/jobs', {
      method: 'DELETE',
    }),

  getStats: (params: { exclude_subscription?: boolean } = {}) =>
    apiFetch<{ running: number; finished: number }>(
      `/api/download/stats${qs(params as Record<string, unknown>)}`,
    ),

  pauseJob: (id: string) =>
    apiFetch<{ status: string }>(`/api/download/jobs/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ action: 'pause' }),
    }),

  resumeJob: (id: string) =>
    apiFetch<{ status: string }>(`/api/download/jobs/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ action: 'resume' }),
    }),

  retryJob: (id: string) =>
    apiFetch<{ status: string; retry_count: number; max_retries: number }>(
      `/api/download/jobs/${id}/retry`,
      { method: 'POST' },
    ),

  checkUrl: (url: string) =>
    apiFetch<{ supported: boolean; source_id?: string; name?: string; category?: string }>(
      `/api/download/check-url${qs({ url })}`,
    ),

  supportedSites: () =>
    apiFetch<{
      categories: Record<
        string,
        Array<{ source_id: string; name: string; domain: string; has_tags: boolean }>
      >
    }>('/api/download/supported-sites'),

  preview: (url: string) => apiFetch<DownloadPreview>(`/api/download/preview${qs({ url })}`),

  getDashboard: () => apiFetch<DashboardResponse>('/api/download/dashboard'),
}
