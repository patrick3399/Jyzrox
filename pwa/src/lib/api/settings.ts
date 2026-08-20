import { apiFetch } from './client'

import type { Credentials, EhAccount, RateLimitSettings, SiteRateConfig } from '../types'

// ── Settings ──────────────────────────────────────────────────────────

export const settings = {
  getCredentials: () => apiFetch<Credentials>('/api/settings/credentials'),

  ehLogin: (username: string, password: string) =>
    apiFetch<{ status: string; account: EhAccount }>('/api/settings/credentials/ehentai/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),

  setEhCookies: (data: {
    ipb_member_id: string
    ipb_pass_hash: string
    sk?: string
    igneous?: string
  }) =>
    apiFetch<{ status: string; account: EhAccount }>('/api/settings/credentials/ehentai', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  setPixivToken: (refresh_token: string) =>
    apiFetch<{ status: string; username: string }>('/api/settings/credentials/pixiv', {
      method: 'POST',
      body: JSON.stringify({ refresh_token }),
    }),

  setPixivCookie: (phpsessid: string) =>
    apiFetch<{ status: string; username: string }>('/api/settings/credentials/pixiv/cookie', {
      method: 'POST',
      body: JSON.stringify({ phpsessid }),
    }),

  getPixivOAuthUrl: () =>
    apiFetch<{ url: string; code_verifier: string }>('/api/settings/credentials/pixiv/oauth-url'),

  pixivOAuthCallback: (code: string, code_verifier: string) =>
    apiFetch<{ status: string; username: string }>(
      '/api/settings/credentials/pixiv/oauth-callback',
      { method: 'POST', body: JSON.stringify({ code, code_verifier }) },
    ),

  getEhAccount: () => apiFetch<EhAccount>('/api/settings/eh/account'),

  checkEhCookies: () =>
    apiFetch<{ eh_valid: boolean; ex_valid: boolean; has_igneous: boolean }>(
      '/api/settings/credentials/ehentai/cookies-check',
      { method: 'POST' },
    ),

  setGenericCookie: (source: string, cookies: Record<string, string>) =>
    apiFetch<{ status: string; source: string }>('/api/settings/credentials/generic', {
      method: 'POST',
      body: JSON.stringify({ source, cookies }),
    }),

  deleteCredential: (source: string) =>
    apiFetch<{ status: string }>(`/api/settings/credentials/${source}`, { method: 'DELETE' }),

  detectSite: (url: string) =>
    apiFetch<{ detected: boolean; source?: string; site_name?: string }>(
      `/api/settings/credentials/detect?url=${encodeURIComponent(url)}`,
    ),

  setSiteCredential: (
    source: string,
    data: { cookies?: string; username?: string; password?: string },
  ) =>
    apiFetch<{ status: string; source: string }>('/api/settings/credentials/site', {
      method: 'POST',
      body: JSON.stringify({ source, ...data }),
    }),

  setSaucenaoApiKey: (api_key: string) =>
    apiFetch<{ status: string }>('/api/settings/credentials/saucenao', {
      method: 'POST',
      body: JSON.stringify({ api_key }),
    }),

  getEhSite: () => apiFetch<{ use_ex: boolean }>('/api/settings/eh-site'),

  setEhSite: (use_ex: boolean) =>
    apiFetch<{ use_ex: boolean }>('/api/settings/eh-site', {
      method: 'PATCH',
      body: JSON.stringify({ use_ex }),
    }),

  getAlerts: () => apiFetch<{ alerts: string[] }>('/api/settings/alerts'),

  dismissAlert: (message: string) =>
    apiFetch<{ status: string; dismissed: number }>('/api/settings/alerts/dismiss', {
      method: 'POST',
      body: JSON.stringify({ message }),
    }),

  getFeatures: () =>
    apiFetch<{
      csrf_enabled: boolean
      rate_limit_enabled: boolean
      opds_enabled: boolean
      external_api_enabled: boolean
      novel_enabled: boolean
      ai_tagging_enabled: boolean
      swarmui_enabled: boolean
      captioner_enabled: boolean
      download_eh_enabled: boolean
      download_pixiv_enabled: boolean
      download_gallery_dl_enabled: boolean
      dedup_phash_enabled: boolean
      dedup_phash_threshold: number
      dedup_heuristic_enabled: boolean
      dedup_opencv_enabled: boolean
      dedup_opencv_threshold: number
      tag_translation_enabled: boolean
      trash_enabled: boolean
      trash_retention_days: number
    }>('/api/settings/features'),

  setFeature: (feature: string, enabled: boolean) =>
    apiFetch<{ feature: string; enabled: boolean }>(`/api/settings/features/${feature}`, {
      method: 'PATCH',
      body: JSON.stringify({ enabled }),
    }),

  setFeatureValue: (feature: string, value: number) =>
    apiFetch<{ feature: string; value: number }>(`/api/settings/features/${feature}`, {
      method: 'PATCH',
      body: JSON.stringify({ value }),
    }),

  getRateLimits: () => apiFetch<RateLimitSettings>('/api/settings/rate-limits'),

  patchRateLimits: (
    data: Partial<{
      sites: Record<string, Partial<SiteRateConfig>>
      schedule: Partial<import('../types').RateLimitSchedule>
    }>,
  ) =>
    apiFetch<RateLimitSettings>('/api/settings/rate-limits', {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),

  setRateLimitOverride: (unlocked: boolean) =>
    apiFetch<void>('/api/settings/rate-limits/override', {
      method: 'POST',
      body: JSON.stringify({ unlocked }),
    }),

  getRecoveryStrategy: () =>
    apiFetch<{
      running: 'auto_retry' | 'mark_failed'
      paused: 'keep_paused' | 'auto_retry' | 'mark_failed'
    }>('/api/settings/recovery-strategy'),

  patchRecoveryStrategy: (data: {
    running?: 'auto_retry' | 'mark_failed'
    paused?: 'keep_paused' | 'auto_retry' | 'mark_failed'
  }) =>
    apiFetch<{
      running: 'auto_retry' | 'mark_failed'
      paused: 'keep_paused' | 'auto_retry' | 'mark_failed'
    }>('/api/settings/recovery-strategy', {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
}
