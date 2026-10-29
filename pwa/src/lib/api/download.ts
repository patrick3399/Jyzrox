import { apiFetch, qs } from './client'

import type { DownloadJob, JobListParams, DownloadPreview, DashboardResponse } from '../types'

// ── Download ──────────────────────────────────────────────────────────

/** What `POST /api/download/galleries/{id}/action` queued. */
export type GalleryActionResult =
  | { kind: 'subscription_check'; subscription_id: number; status: string }
  | { kind: 'download' | 'repair'; job_id: string; status: string; warning?: string }

export const download = {
  /**
   * Queue a URL. Without `confirmSubscribed`, a URL the user already subscribes
   * to is refused with 409 `{code: "subscribed"}` (an `ApiError` whose `detail`
   * carries the subscription) so the caller can offer "check now" instead.
   */
  enqueue: (
    url: string,
    source?: string,
    options: Record<string, unknown> = {},
    total?: number,
    flags: { confirmSubscribed?: boolean } = {},
  ) =>
    apiFetch<{ job_id: string; status: string; warning?: string }>('/api/download/', {
      method: 'POST',
      body: JSON.stringify({
        url,
        ...(source && { source }),
        ...(total !== undefined && { total }),
        ...(Object.keys(options).length > 0 && { options }),
        ...(flags.confirmSubscribed && { confirm_subscribed: true }),
      }),
    }),

  /**
   * Gallery page "update" / "repair". The server decides what that means: an
   * update of a subscription's gallery is a subscription check, a repair
   * re-fetches against a shadow archive (and, with `includeExcluded`, lets
   * purged images back in).
   */
  galleryAction: (galleryId: number, action: 'repair' | 'update', includeExcluded = false) =>
    apiFetch<GalleryActionResult>(`/api/download/galleries/${galleryId}/action`, {
      method: 'POST',
      body: JSON.stringify({ action, include_excluded: includeExcluded }),
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

  /** Discard: kill the job and delete what this run fetched. A repair job treats this as a stop. */
  cancelJob: (id: string) =>
    apiFetch<{ status: string; stopping?: boolean }>(`/api/download/jobs/${id}`, {
      method: 'DELETE',
    }),

  /** Stop and keep: end the job early, keeping everything it already imported. */
  stopJob: (id: string) =>
    apiFetch<{ status: string; stopping: boolean }>(`/api/download/jobs/${id}/stop`, {
      method: 'POST',
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
    apiFetch<{
      supported: boolean
      source_id?: string
      name?: string
      category?: string
      supports_media_policy?: boolean
    }>(`/api/download/check-url${qs({ url })}`),

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
