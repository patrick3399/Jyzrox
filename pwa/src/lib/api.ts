import { t } from '@/lib/i18n'

import type {
  Gallery,
  GalleryImage,
  GalleryListResponse,
  GallerySearchParams,
  TagListResponse,
  EhGallery,
  EhSearchResult,
  EhFavoritesResult,
  EhImageMap,
  EhSearchParams,
  DownloadJob,
  JobListParams,
  Credentials,
  EhAccount,
  SessionInfo,
  ApiTokenInfo,
  ReadProgress,
  SystemHealth,
  SystemInfo,
  TagAlias,
  TagImplication,
  TagItem,
  EhComment,
  BrowseHistoryItem,
  SavedSearch,
  BlockedTag,
  CacheStats,
  PluginInfo,
  PixivIllust,
  PixivSearchResult,
  PixivUserResult,
  PixivUserPreview,
  FollowedArtist,
  ArtistSummary,
  ArtistImageItem,
  ArtistDetail,
  Collection,
  LibraryDirectory,
  LibraryFile,
  ScheduledTask,
  Subscription,
  SubscriptionGroup,
  DedupStats,
  DedupReviewResponse,
  DedupScanProgress,
  UserInfo,
  RateLimitSettings,
  SiteRateConfig,
  DownloadPreview,
  StorageInfo,
  LogEntry,
  LogLevelConfig,
  SiteConfigItem,
  ProbeResult,
  DashboardResponse,
} from './types'

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

// ── Base fetch ───────────────────────────────────────────────────────

function getCookie(name: string): string | undefined {
  if (typeof document === 'undefined') return undefined
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`))
  return match ? decodeURIComponent(match[1]) : undefined
}

let isRedirecting = false
// Reset redirect guard on successful navigation
if (typeof window !== 'undefined') {
  window.addEventListener('pageshow', () => {
    isRedirecting = false
  })
}

async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  }

  const method = (options.method || 'GET').toUpperCase()
  if (method !== 'GET' && method !== 'HEAD') {
    const csrf = getCookie('csrf_token')
    if (csrf) headers['X-CSRF-Token'] = csrf
  }

  const res = await fetch(path, {
    credentials: 'include', // always send vault_token cookie
    headers: { ...headers, ...(options.headers as Record<string, string>) },
    ...options,
  })

  if (!res.ok) {
    if (res.status === 429) {
      throw new Error(t('common.rateLimited'))
    }
    // Stale session → redirect to login (skip if already on /login or /setup)
    if (res.status === 401 && typeof window !== 'undefined') {
      const p = window.location.pathname
      if (p !== '/login' && p !== '/setup' && !isRedirecting) {
        isRedirecting = true
        window.location.href = '/login'
      }
      throw new Error('Unauthorized')
    }
    // Forbidden → redirect to /forbidden
    if (res.status === 403 && typeof window !== 'undefined') {
      const p = window.location.pathname
      if (p !== '/forbidden' && !isRedirecting) {
        isRedirecting = true
        window.location.href = '/forbidden'
      }
      throw new Error('Forbidden')
    }
    const body = await res.json().catch(() => ({}))
    const raw = body?.detail
    let msg: string
    if (typeof raw === 'object' && raw !== null && raw.code) {
      const i18nKey = `error.${raw.code}`
      const translated = t(i18nKey)
      msg = translated !== i18nKey ? translated : raw.message || `HTTP ${res.status}`
    } else if (typeof raw === 'string') {
      msg = raw
    } else {
      msg = raw ? JSON.stringify(raw) : `HTTP ${res.status}`
    }
    throw new Error(msg)
  }

  // Some endpoints return no body (204)
  const text = await res.text()
  return text ? JSON.parse(text) : ({} as T)
}

function qs(params: Record<string, unknown>): string {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null) continue
    if (Array.isArray(v)) v.forEach((item) => p.append(k, String(item)))
    else p.set(k, String(v))
  }
  const s = p.toString()
  return s ? `?${s}` : ''
}

// ── Auth ─────────────────────────────────────────────────────────────

const auth = {
  login: (username: string, password: string) =>
    apiFetch<{ status: string; role: string }>('/api/auth/login', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),

  logout: () => apiFetch<{ status: string }>('/api/auth/logout', { method: 'POST' }),

  needsSetup: () => apiFetch<{ needs_setup: boolean }>('/api/auth/needs-setup'),

  setup: (username: string, password: string) =>
    apiFetch<{ status: string }>('/api/auth/setup', {
      method: 'POST',
      body: JSON.stringify({ username, password }),
    }),

  getSessions: () => apiFetch<{ sessions: SessionInfo[] }>('/api/auth/sessions'),

  revokeSession: (tokenPrefix: string) =>
    apiFetch<{ status: string }>(`/api/auth/sessions/${tokenPrefix}`, {
      method: 'DELETE',
    }),

  check: () => apiFetch<{ status: string }>('/api/auth/check'),

  getProfile: () =>
    apiFetch<{
      username: string
      email: string | null
      role: string
      created_at: string | null
      avatar_url: string
      avatar_style: string
      locale: string | null
    }>('/api/auth/profile'),

  updateProfile: (data: { email?: string | null; avatar_style?: string; locale?: string }) =>
    apiFetch<{ status: string }>('/api/auth/profile', {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),

  uploadAvatar: async (
    file: File,
  ): Promise<{ status: string; avatar_url: string; avatar_style: string }> => {
    const form = new FormData()
    form.append('file', file)
    const csrfHeaders: Record<string, string> = {}
    const csrf = getCookie('csrf_token')
    if (csrf) csrfHeaders['X-CSRF-Token'] = csrf

    const res = await fetch('/api/auth/avatar', {
      method: 'PUT',
      credentials: 'include',
      headers: csrfHeaders,
      body: form,
    })
    if (!res.ok) {
      if (res.status === 401 && typeof window !== 'undefined') {
        const p = window.location.pathname
        if (p !== '/login' && p !== '/setup' && !isRedirecting) {
          isRedirecting = true
          window.location.href = '/login'
        }
        throw new Error('Unauthorized')
      }
      const body = await res.json().catch(() => ({}))
      throw new Error(body?.detail || `HTTP ${res.status}`)
    }
    return res.json()
  },

  deleteAvatar: () =>
    apiFetch<{ status: string; avatar_url: string; avatar_style: string }>('/api/auth/avatar', {
      method: 'DELETE',
    }),

  changePassword: (current_password: string, new_password: string) =>
    apiFetch<{ status: string }>('/api/auth/change-password', {
      method: 'POST',
      body: JSON.stringify({ current_password, new_password }),
    }),
}

// ── E-Hentai ─────────────────────────────────────────────────────────

const eh = {
  search: (params: EhSearchParams = {}) =>
    apiFetch<EhSearchResult>(`/api/eh/search${qs(params as Record<string, unknown>)}`),

  getGallery: (gid: number, token: string) =>
    apiFetch<EhGallery>(`/api/eh/gallery/${gid}/${token}`),

  getImages: (gid: number, token: string) =>
    apiFetch<EhImageMap>(`/api/eh/gallery/${gid}/${token}/images`),

  /** Lightweight: only scrapes page 0 for ~20 preview thumbnails */
  getPreviews: (gid: number, token: string) =>
    apiFetch<{ gid: number; previews: Record<string, string> }>(
      `/api/eh/gallery/${gid}/${token}/previews`,
    ),

  /** Returns the URL string — caller uses it as <img src> */
  imageProxyUrl: (gid: number, page: number): string => `/api/eh/image-proxy/${gid}/${page}`,

  /** Proxy an EH CDN thumbnail through our server */
  thumbProxyUrl: (url: string): string => `/api/eh/thumb-proxy?url=${encodeURIComponent(url)}`,

  getFavorites: (params: { favcat?: string; q?: string; next?: string; prev?: string } = {}) =>
    apiFetch<EhFavoritesResult>(`/api/eh/favorites${qs(params as Record<string, unknown>)}`),

  addFavorite: (gid: number, token: string, favcat?: number, note?: string) =>
    apiFetch<{ status: string }>(`/api/eh/favorites/${gid}/${token}${qs({ favcat, note })}`, {
      method: 'POST',
    }),

  removeFavorite: (gid: number, token: string) =>
    apiFetch<{ status: string }>(`/api/eh/favorites/${gid}/${token}`, {
      method: 'DELETE',
    }),

  getPopular: () => apiFetch<EhSearchResult>('/api/eh/popular'),

  getToplist: (params: { tl?: number; page?: number } = {}) =>
    apiFetch<EhSearchResult>(`/api/eh/toplists${qs(params as Record<string, unknown>)}`),

  getComments: (gid: number, token: string) =>
    apiFetch<{ comments: EhComment[] }>(`/api/eh/gallery/${gid}/${token}/comments`),

  /** Paginated image token fetch — avoids loading all tokens upfront for large galleries */
  getImagesPaginated: (gid: number, token: string, startPage: number = 0, count: number = 20) =>
    apiFetch<{
      images: Array<{ page: number; token: string }>
      previews: Record<string, string>
      has_more: boolean
      total: number
    }>(`/api/eh/gallery/${gid}/${token}/images-paginated?start_page=${startPage}&count=${count}`),
}

// ── Library ───────────────────────────────────────────────────────────

const library = {
  getSources: () => apiFetch<{ value: string; label: string }[]>('/api/library/galleries/sources'),

  getCategories: () => apiFetch<{ categories: string[] }>('/api/library/galleries/categories'),

  getGalleries: (params: GallerySearchParams = {}) =>
    apiFetch<GalleryListResponse>(`/api/library/galleries${qs(params as Record<string, unknown>)}`),

  getGallery: (source: string, sourceId: string) =>
    apiFetch<Gallery>(
      `/api/library/galleries/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}`,
    ),

  getImages: (source: string, sourceId: string, opts?: { page?: number; limit?: number }) => {
    const params = new URLSearchParams()
    if (opts?.page) params.set('page', String(opts.page))
    if (opts?.limit) params.set('limit', String(opts.limit))
    const qs = params.toString()
    return apiFetch<{
      gallery_id: number
      images: GalleryImage[]
      total?: number
      page?: number
      has_next?: boolean
      favorited_image_ids?: number[]
    }>(
      `/api/library/galleries/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}/images${qs ? `?${qs}` : ''}`,
    )
  },

  updateGallery: (
    source: string,
    sourceId: string,
    patch: {
      favorited?: boolean
      rating?: number
      title?: string
      title_jpn?: string
      category?: string
      in_reading_list?: boolean
    },
  ) =>
    apiFetch<Gallery>(
      `/api/library/galleries/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}`,
      {
        method: 'PATCH',
        body: JSON.stringify(patch),
      },
    ),

  batchGalleries: (body: {
    action:
      | 'delete'
      | 'favorite'
      | 'unfavorite'
      | 'rate'
      | 'add_to_collection'
      | 'add_tags'
      | 'remove_tags'
      | 'add_to_reading_list'
      | 'remove_from_reading_list'
    gallery_ids: number[]
    rating?: number
    collection_id?: number
    tags?: string[]
  }) =>
    apiFetch<{ status: string; affected: number; deleted_dirs?: number }>(
      '/api/library/galleries/batch',
      {
        method: 'POST',
        body: JSON.stringify(body),
      },
    ),

  deleteGallery: (source: string, sourceId: string) =>
    apiFetch<{ status: string; deleted_files: number }>(
      `/api/library/galleries/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}`,
      {
        method: 'DELETE',
      },
    ),

  getProgress: (source: string, sourceId: string) =>
    apiFetch<ReadProgress>(
      `/api/library/galleries/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}/progress`,
    ),

  saveProgress: (source: string, sourceId: string, last_page: number) =>
    apiFetch<{ status: string }>(
      `/api/library/galleries/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}/progress`,
      {
        method: 'POST',
        body: JSON.stringify({ last_page }),
      },
    ),

  getGalleryTags: (source: string, sourceId: string) =>
    apiFetch<{
      gallery_id: number
      tags: Array<{
        namespace: string
        name: string
        confidence: number
        source: string
      }>
    }>(`/api/library/galleries/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}/tags`),

  getArtists: (
    params: { q?: string; source?: string; sort?: string; page?: number; limit?: number } = {},
  ) =>
    apiFetch<{ artists: ArtistSummary[]; total: number }>(
      `/api/library/artists${qs(params as Record<string, unknown>)}`,
    ),

  getArtistSummary: (artistId: string) =>
    apiFetch<ArtistDetail>(`/api/library/artists/${encodeURIComponent(artistId)}/summary`),

  getArtistImages: (
    artistId: string,
    params: { page?: number; limit?: number; sort?: 'newest' | 'oldest' } = {},
  ) =>
    apiFetch<{
      artist_id: string
      images: ArtistImageItem[]
      total: number
      page: number
      has_next: boolean
    }>(
      `/api/library/artists/${encodeURIComponent(artistId)}/images${qs(params as Record<string, unknown>)}`,
    ),

  listFiles: (params: { q?: string; page?: number; limit?: number } = {}) =>
    apiFetch<{ directories: LibraryDirectory[]; total: number; page: number }>(
      `/api/library/files${qs(params as Record<string, unknown>)}`,
    ),

  listGalleryFiles: (source: string, sourceId: string) =>
    apiFetch<{
      gallery_id: number
      source: string
      source_id: string
      title: string
      category: string | null
      files: LibraryFile[]
      total_files: number
    }>(`/api/library/files/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}`),

  deleteImage: (source: string, sourceId: string, pageNum: number) =>
    apiFetch<{ status: string; remaining_pages: number }>(
      `/api/library/galleries/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}/delete-image`,
      { method: 'POST', body: JSON.stringify({ page_num: pageNum }) },
    ),

  listExcluded: (source: string, sourceId: string) =>
    apiFetch<{
      gallery_id: number
      excluded: Array<{ blob_sha256: string; excluded_at: string | null }>
    }>(
      `/api/library/galleries/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}/excluded`,
    ),

  restoreExcluded: (source: string, sourceId: string, sha256: string) =>
    apiFetch<{ status: string }>(
      `/api/library/galleries/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}/excluded/${encodeURIComponent(sha256)}`,
      { method: 'DELETE' },
    ),

  favoriteImage: (imageId: number) =>
    apiFetch<{ status: string }>(`/api/library/images/${imageId}/favorite`, { method: 'POST' }),

  unfavoriteImage: (imageId: number) =>
    apiFetch<{ status: string }>(`/api/library/images/${imageId}/favorite`, { method: 'DELETE' }),

  browseImages: (
    params: {
      tags?: string[]
      exclude_tags?: string[]
      cursor?: string
      limit?: number
      sort?: 'newest' | 'oldest'
      gallery_id?: number
      source?: string
      category?: string
      jump_at?: string
      favorited?: boolean
    } = {},
  ) =>
    apiFetch<import('./types').ImageBrowserResponse>(
      `/api/library/images${qs(params as Record<string, unknown>)}`,
    ),

  imageTimeRange: (
    params: {
      tags?: string[]
      exclude_tags?: string[]
      source?: string
      category?: string
      gallery_id?: number
      favorited?: boolean
    } = {},
  ) =>
    apiFetch<import('./types').ImageTimeRangeResponse>(
      `/api/library/images/time_range${qs(params as Record<string, unknown>)}`,
    ),

  imageTimelinePercentiles: (
    params: {
      tags?: string[]
      exclude_tags?: string[]
      source?: string
      category?: string
      gallery_id?: number
      buckets?: number
      favorited?: boolean
    } = {},
  ) =>
    apiFetch<import('./types').TimelinePercentilesResponse>(
      `/api/library/images/timeline_percentiles${qs(params as Record<string, unknown>)}`,
    ),

  trashList: (params: { limit?: number; offset?: number } = {}) =>
    apiFetch<{ total: number; galleries: Gallery[] }>(
      `/api/library/trash${qs(params as Record<string, unknown>)}`,
    ),

  trashCount: () => apiFetch<{ count: number }>('/api/library/trash/count'),

  restore: (source: string, sourceId: string) =>
    apiFetch<{ status: string }>(
      `/api/library/galleries/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}/restore`,
      {
        method: 'POST',
      },
    ),

  permanentDelete: (source: string, sourceId: string) =>
    apiFetch<{ status: string; affected: number; deleted_dirs: number }>(
      `/api/library/galleries/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}/permanent-delete`,
      {
        method: 'POST',
      },
    ),

  emptyTrash: () =>
    apiFetch<{ status: string; affected: number }>('/api/library/trash/empty', {
      method: 'POST',
    }),

  checkUpdate: (source: string, sourceId: string) =>
    apiFetch<{
      status: string
      reason?: string
      gallery?: Gallery
      changed_fields?: string[]
      pages_diff?: { old: number; new: number } | null
    }>(
      `/api/library/galleries/${encodeURIComponent(source)}/${encodeURIComponent(sourceId)}/check-update`,
      { method: 'POST' },
    ),
}

// ── Download ──────────────────────────────────────────────────────────

const download = {
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

// ── Settings ──────────────────────────────────────────────────────────

const settings = {
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

  getEhSite: () => apiFetch<{ use_ex: boolean }>('/api/settings/eh-site'),

  setEhSite: (use_ex: boolean) =>
    apiFetch<{ use_ex: boolean }>('/api/settings/eh-site', {
      method: 'PATCH',
      body: JSON.stringify({ use_ex }),
    }),

  getAlerts: () => apiFetch<{ alerts: string[] }>('/api/settings/alerts'),

  getFeatures: () =>
    apiFetch<{
      csrf_enabled: boolean
      rate_limit_enabled: boolean
      opds_enabled: boolean
      external_api_enabled: boolean
      ai_tagging_enabled: boolean
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
      schedule: Partial<import('./types').RateLimitSchedule>
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

// ── History ───────────────────────────────────────────────────────────

const history = {
  list: (params: { limit?: number; offset?: number } = {}) =>
    apiFetch<{ items: BrowseHistoryItem[]; total: number }>(
      `/api/history/${qs(params as Record<string, unknown>)}`,
    ),

  record: (data: {
    source: string
    source_id: string
    title: string
    thumb?: string
    gid?: number
    token?: string
  }) =>
    apiFetch<{ status: string }>('/api/history/', { method: 'POST', body: JSON.stringify(data) }),

  clear: () => apiFetch<{ status: string }>('/api/history/', { method: 'DELETE' }),

  delete: (id: number) => apiFetch<{ status: string }>(`/api/history/${id}`, { method: 'DELETE' }),
}

// ── Saved Searches ────────────────────────────────────────────────────

const savedSearches = {
  list: () => apiFetch<{ searches: SavedSearch[] }>('/api/search/saved'),

  create: (data: { name: string; query: string; params: Record<string, unknown> }) =>
    apiFetch<SavedSearch>('/api/search/saved', { method: 'POST', body: JSON.stringify(data) }),

  delete: (id: number) =>
    apiFetch<{ status: string }>(`/api/search/saved/${id}`, { method: 'DELETE' }),

  rename: (id: number, name: string) =>
    apiFetch<{ status: string }>(`/api/search/saved/${id}`, {
      method: 'PATCH',
      body: JSON.stringify({ name }),
    }),
}

// ── System ────────────────────────────────────────────────────────────

const system = {
  health: () => apiFetch<SystemHealth>('/api/system/health'),
  info: () => apiFetch<SystemInfo>('/api/system/info'),
  getCache: () => apiFetch<CacheStats>('/api/system/cache'),
  getStorage: () => apiFetch<StorageInfo>('/api/system/storage'),
  clearCache: () => apiFetch<{ deleted_keys: number }>('/api/system/cache', { method: 'DELETE' }),
  clearCacheCategory: (category: string) =>
    apiFetch<{ deleted_keys: number }>(`/api/system/cache/${category}`, { method: 'DELETE' }),
  startReconcile: () => apiFetch<{ status: string }>('/api/system/reconcile', { method: 'POST' }),
  getReconcileStatus: () => apiFetch<ReconcileStatus>('/api/system/reconcile'),
}

// ── Tags ─────────────────────────────────────────────────────────────

const tags = {
  list: (
    params: {
      prefix?: string
      namespace?: string
      limit?: number
      offset?: number
      cursor?: string
    } = {},
  ) => apiFetch<TagListResponse>(`/api/tags/${qs(params as Record<string, unknown>)}`),

  listAliases: (params: { tag_id?: number; limit?: number } = {}) =>
    apiFetch<TagAlias[]>(`/api/tags/aliases${qs(params as Record<string, unknown>)}`),

  createAlias: (alias_namespace: string, alias_name: string, canonical_id: number) =>
    apiFetch<{ status: string }>('/api/tags/aliases', {
      method: 'POST',
      body: JSON.stringify({ alias_namespace, alias_name, canonical_id }),
    }),

  deleteAlias: (alias_namespace: string, alias_name: string) =>
    apiFetch<{ status: string }>(`/api/tags/aliases${qs({ alias_namespace, alias_name })}`, {
      method: 'DELETE',
    }),

  listImplications: (params: { tag_id?: number; limit?: number } = {}) =>
    apiFetch<TagImplication[]>(`/api/tags/implications${qs(params as Record<string, unknown>)}`),

  createImplication: (antecedent_id: number, consequent_id: number) =>
    apiFetch<{ status: string }>('/api/tags/implications', {
      method: 'POST',
      body: JSON.stringify({ antecedent_id, consequent_id }),
    }),

  deleteImplication: (antecedent_id: number, consequent_id: number) =>
    apiFetch<{ status: string }>(`/api/tags/implications${qs({ antecedent_id, consequent_id })}`, {
      method: 'DELETE',
    }),

  autocomplete: (q: string, limit = 10) =>
    apiFetch<TagItem[]>(`/api/tags/autocomplete${qs({ q, limit })}`),

  getTranslations: (tags: string[], language = 'zh') =>
    apiFetch<Record<string, string>>(
      `/api/tags/translations${qs({ tags: tags.join(','), language })}`,
    ),

  listBlocked: () => apiFetch<BlockedTag[]>('/api/tags/blocked'),

  addBlocked: (namespace: string, name: string) =>
    apiFetch<{ status: string }>('/api/tags/blocked', {
      method: 'POST',
      body: JSON.stringify({ namespace, name }),
    }),

  removeBlocked: (id: number) =>
    apiFetch<{ status: string }>(`/api/tags/blocked/${id}`, { method: 'DELETE' }),

  retag: (galleryId: number) =>
    apiFetch<{ status: string; gallery_id: number }>(`/api/tags/retag/${galleryId}`, {
      method: 'POST',
    }),

  retagAll: () =>
    apiFetch<{ status: string; total: number }>('/api/tags/retag-all', { method: 'POST' }),

  importEhtag: () =>
    apiFetch<{ status: string; count: number }>('/api/tags/import-ehtag', { method: 'POST' }),

  updateGalleryTags: (galleryId: number, body: { tags: string[]; action: 'add' | 'remove' }) =>
    apiFetch<{ status: string; affected: number }>(`/api/tags/gallery/${galleryId}`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  upsertTranslation: (body: {
    namespace: string
    name: string
    language: string
    translation: string
  }) =>
    apiFetch<{ status: string }>('/api/tags/translations', {
      method: 'POST',
      body: JSON.stringify(body),
    }),

  batchImportTranslations: (
    translations: Array<{ namespace: string; name: string; language: string; translation: string }>,
  ) =>
    apiFetch<{ status: string; count: number }>('/api/tags/translations/batch', {
      method: 'POST',
      body: JSON.stringify({ translations }),
    }),
}

// ── API Tokens ───────────────────────────────────────────────────────

const tokens = {
  list: () => apiFetch<{ tokens: ApiTokenInfo[] }>('/api/settings/tokens'),

  create: (name: string, expires_days?: number) =>
    apiFetch<ApiTokenInfo>('/api/settings/tokens', {
      method: 'POST',
      body: JSON.stringify({ name, expires_days: expires_days || null }),
    }),

  delete: (tokenId: string) =>
    apiFetch<{ status: string }>(`/api/settings/tokens/${tokenId}`, {
      method: 'DELETE',
    }),

  update: (tokenId: string, name: string) =>
    apiFetch<{ status: string }>(`/api/settings/tokens/${tokenId}${qs({ name })}`, {
      method: 'PATCH',
    }),
}

// ── Import ────────────────────────────────────────────────────────────

const import_ = {
  batchScan: (rootDir: string, pattern: string) =>
    apiFetch<{
      matches: Array<{
        rel_path: string
        abs_path: string
        artist: string | null
        title: string
        file_count: number
      }>
      unmatched: Array<{ rel_path: string; file_count: number }>
    }>('/api/import/batch/scan', {
      method: 'POST',
      body: JSON.stringify({ root_dir: rootDir, pattern }),
    }),

  batchStart: (
    rootDir: string,
    mode: string,
    galleries: Array<{ path: string; artist: string | null; title: string }>,
  ) =>
    apiFetch<{ batch_id: string; total: number }>('/api/import/batch/start', {
      method: 'POST',
      body: JSON.stringify({ root_dir: rootDir, mode, galleries }),
    }),

  batchProgress: (batchId: string) =>
    apiFetch<{
      total: number
      completed: number
      failed: number
      current_gallery_id: number | null
      status: string
    }>(`/api/import/batch/progress/${batchId}`),

  rescanLibraryPath: (libraryId: number) =>
    apiFetch<{ status: string }>(`/api/import/rescan/path/${libraryId}`, { method: 'POST' }),

  progress: (galleryId: number) =>
    apiFetch<{ gallery_id: number; processed: number; total: number; status: string }>(
      `/api/import/progress/${galleryId}`,
    ),

  rescan: () => apiFetch<{ status: string }>('/api/import/rescan', { method: 'POST' }),

  rescanGallery: (id: number) =>
    apiFetch<{ status: string; gallery_id: number }>(`/api/import/rescan/${id}`, {
      method: 'POST',
    }),

  rescanStatus: () =>
    apiFetch<{
      running: boolean
      processed?: number
      total?: number
      current_gallery?: string
      status?: string
    }>('/api/import/rescan/status'),

  rescanCancel: () => apiFetch<{ status: string }>('/api/import/rescan/cancel', { method: 'POST' }),

  libraries: () =>
    apiFetch<
      Array<{
        id: number | null
        path: string
        label: string
        enabled: boolean
        monitor: boolean
        is_primary: boolean
        exists: boolean
        added_at: string | null
      }>
    >('/api/import/libraries'),

  addLibrary: (path: string, label?: string) =>
    apiFetch<{ status: string; path: string }>('/api/import/libraries', {
      method: 'POST',
      body: JSON.stringify({ path, label }),
    }),

  removeLibrary: (id: number) =>
    apiFetch<{ status: string }>(`/api/import/libraries/${id}`, { method: 'DELETE' }),

  monitorStatus: () =>
    apiFetch<{ enabled: boolean; running: boolean; watched_paths: string[] }>(
      '/api/import/monitor/status',
    ),

  toggleMonitor: (enabled: boolean) =>
    apiFetch<{ status: string }>('/api/import/monitor/toggle', {
      method: 'POST',
      body: JSON.stringify({ enabled }),
    }),

  browseFs: (path?: string) =>
    apiFetch<{ path: string; parent: string | null; entries: { name: string; type: string }[] }>(
      `/api/import/browse-fs${path ? `?path=${encodeURIComponent(path)}` : ''}`,
    ),

  mountPoints: () =>
    apiFetch<{ mounts: { name: string; path: string; type: string }[] }>(
      '/api/import/mount-points',
    ),
}

// ── Export ────────────────────────────────────────────────────────────

const exportApi = {
  kohyaUrl: (galleryId: number): string => `/api/export/kohya/${galleryId}`,
}

// ── Plugins ──────────────────────────────────────────────────────────

const plugins = {
  list: () => apiFetch<{ plugins: PluginInfo[] }>('/api/plugins/'),
}

// ── Pixiv ─────────────────────────────────────────────────────────────

const pixiv = {
  search: (
    params: {
      word?: string
      sort?: string
      search_target?: string
      duration?: string
      offset?: number
    } = {},
  ) => {
    const p = new URLSearchParams()
    if (params.word) p.set('word', params.word)
    if (params.sort) p.set('sort', params.sort)
    if (params.search_target) p.set('search_target', params.search_target)
    if (params.duration) p.set('duration', params.duration)
    if (params.offset) p.set('offset', String(params.offset))
    return apiFetch<PixivSearchResult>(`/api/pixiv/search?${p}`)
  },

  searchPublic: (
    params: {
      word?: string
      order?: string
      mode?: string
      page?: number
      s_mode?: string
      type?: string
    } = {},
  ) => {
    const p = new URLSearchParams()
    if (params.word) p.set('word', params.word)
    if (params.order) p.set('order', params.order)
    if (params.mode) p.set('mode', params.mode)
    if (params.page) p.set('page', String(params.page))
    if (params.s_mode) p.set('s_mode', params.s_mode)
    if (params.type) p.set('type', params.type)
    return apiFetch<PixivSearchResult & { popular?: PixivIllust[]; related_tags?: string[] }>(
      `/api/pixiv/search-public?${p}`,
    )
  },

  getIllust: (id: number) => apiFetch<PixivIllust>(`/api/pixiv/illust/${id}`),

  getIllustPages: (id: number) =>
    apiFetch<{ pages: Array<{ page_num: number; url: string }>; page_count: number }>(
      `/api/pixiv/illust/${id}/pages`,
    ),

  getUser: (id: number) => apiFetch<PixivUserResult>(`/api/pixiv/user/${id}`),

  getUserIllusts: (id: number, offset = 0) =>
    apiFetch<PixivSearchResult>(`/api/pixiv/user/${id}/illusts?offset=${offset}`),

  getUserBookmarks: (id: number, offset = 0) =>
    apiFetch<PixivSearchResult>(`/api/pixiv/user/${id}/bookmarks?offset=${offset}`),

  getMyBookmarks: (restrict = 'public', offset = 0) =>
    apiFetch<PixivSearchResult>(`/api/pixiv/bookmarks?restrict=${restrict}&offset=${offset}`),

  getFollowingFeed: (offset = 0) =>
    apiFetch<PixivSearchResult>(`/api/pixiv/following/feed?offset=${offset}`),

  getFollowing: (restrict = 'public', offset = 0) =>
    apiFetch<{ user_previews: PixivUserPreview[]; next_offset: number | null }>(
      `/api/pixiv/following?restrict=${restrict}&offset=${offset}`,
    ),

  imageProxyUrl: (url: string) => `/api/pixiv/image-proxy?url=${encodeURIComponent(url)}`,

  addBookmark: (id: number, restrict: 'public' | 'private' = 'public') =>
    apiFetch<{ ok: boolean }>(`/api/pixiv/illust/${id}/bookmark?restrict=${restrict}`, {
      method: 'POST',
    }),

  deleteBookmark: (id: number) =>
    apiFetch<{ ok: boolean }>(`/api/pixiv/illust/${id}/bookmark`, { method: 'DELETE' }),

  getBookmarkStatus: (id: number) =>
    apiFetch<{ is_bookmarked: boolean }>(`/api/pixiv/illust/${id}/bookmark`),

  followUser: (id: number) =>
    apiFetch<{ ok: boolean }>(`/api/pixiv/user/${id}/follow`, { method: 'POST' }),

  unfollowUser: (id: number) =>
    apiFetch<{ ok: boolean }>(`/api/pixiv/user/${id}/follow`, { method: 'DELETE' }),

  ranking: (params: { mode?: string; content?: string; date?: string; page?: number } = {}) => {
    const p = new URLSearchParams()
    if (params.mode) p.set('mode', params.mode)
    if (params.content) p.set('content', params.content)
    if (params.date) p.set('date', params.date)
    if (params.page) p.set('page', String(params.page))
    return apiFetch<{
      contents: Array<Record<string, unknown>>
      mode: string
      content: string
      date: string
      page: number
      prev_date: string | null
      next_date: string | null
      rank_total: number
    }>(`/api/pixiv/ranking?${p}`)
  },
}

// ── Artists ───────────────────────────────────────────────────────────

const artists = {
  listFollowed: (params: { source?: string; limit?: number; offset?: number } = {}) => {
    const p = new URLSearchParams()
    if (params.source) p.set('source', params.source)
    if (params.limit) p.set('limit', String(params.limit))
    if (params.offset) p.set('offset', String(params.offset))
    return apiFetch<{ artists: FollowedArtist[]; total: number }>(`/api/artists/followed?${p}`)
  },

  follow: (data: {
    source: string
    artist_id: string
    artist_name?: string
    artist_avatar?: string
    auto_download?: boolean
  }) =>
    apiFetch<{ status: string; id: number }>('/api/artists/follow', {
      method: 'POST',
      body: JSON.stringify(data),
    }),

  unfollow: (artistId: string, source = 'pixiv') =>
    apiFetch<{ status: string }>(`/api/artists/follow/${artistId}?source=${source}`, {
      method: 'DELETE',
    }),

  patchFollow: (artistId: string, data: { auto_download?: boolean }, source = 'pixiv') =>
    apiFetch<{ status: string }>(`/api/artists/follow/${artistId}?source=${source}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),

  checkUpdates: () =>
    apiFetch<{ status: string }>('/api/artists/check-updates', { method: 'POST' }),
}

// ── Collections ──────────────────────────────────────────────────────

const collections = {
  list: () => apiFetch<{ collections: Collection[] }>('/api/collections/'),

  get: (id: number, params: { page?: number; limit?: number } = {}) =>
    apiFetch<{
      id: number
      name: string
      description: string | null
      cover_gallery_id: number | null
      gallery_count: number
      galleries: Array<Gallery & { position: number; added_to_collection_at: string | null }>
      page: number
      has_next: boolean
      created_at: string | null
      updated_at: string | null
    }>(`/api/collections/${id}${qs(params as Record<string, unknown>)}`),

  create: (data: { name: string; description?: string }) =>
    apiFetch<{ id: number; name: string; description: string | null; created_at: string | null }>(
      '/api/collections/',
      {
        method: 'POST',
        body: JSON.stringify(data),
      },
    ),

  update: (id: number, patch: { name?: string; description?: string; cover_gallery_id?: number }) =>
    apiFetch<{ status: string }>(`/api/collections/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  delete: (id: number) =>
    apiFetch<{ status: string }>(`/api/collections/${id}`, {
      method: 'DELETE',
    }),

  addGalleries: (id: number, gallery_ids: number[]) =>
    apiFetch<{ status: string; added: number }>(`/api/collections/${id}/galleries`, {
      method: 'POST',
      body: JSON.stringify({ gallery_ids }),
    }),

  removeGallery: (id: number, galleryId: number) =>
    apiFetch<{ status: string }>(`/api/collections/${id}/galleries/${galleryId}`, {
      method: 'DELETE',
    }),
}

// ── Scheduled Tasks ──────────────────────────────────────────────────

const scheduledTasks = {
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

// ── Subscriptions ────────────────────────────────────────────────────

const subscriptions = {
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

  jobs: (id: number, limit = 10) =>
    apiFetch<{ jobs: DownloadJob[] }>(`/api/subscriptions/${id}/jobs${qs({ limit })}`),
}

// ── Subscription Groups ──────────────────────────────────────────────

const subscriptionGroups = {
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

// ── Dedup ────────────────────────────────────────────────────────────

const dedup = {
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

// ── Users ─────────────────────────────────────────────────────────────

const users = {
  list: () => apiFetch<{ users: UserInfo[] }>('/api/users'),
  create: (data: { username: string; password: string; role: string; email?: string }) =>
    apiFetch<{ id: number; username: string; role: string; email: string | null }>('/api/users', {
      method: 'POST',
      body: JSON.stringify(data),
    }),
  update: (id: number, data: { role?: string; email?: string; password?: string }) =>
    apiFetch<{ status: string }>(`/api/users/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
  delete: (id: number) => apiFetch<{ status: string }>(`/api/users/${id}`, { method: 'DELETE' }),
}

// ── Admin Sites ──────────────────────────────────────────────────────

const adminSites = {
  list: () => apiFetch<SiteConfigItem[]>('/api/admin/sites'),
  get: (sourceId: string) => apiFetch<SiteConfigItem>(`/api/admin/sites/${sourceId}`),
  update: (sourceId: string, data: { download?: Record<string, unknown> }) =>
    apiFetch<SiteConfigItem>(`/api/admin/sites/${sourceId}`, {
      method: 'PUT',
      body: JSON.stringify(data),
    }),
  probe: (url: string) =>
    apiFetch<ProbeResult>('/api/admin/sites/probe', {
      method: 'POST',
      body: JSON.stringify({ url }),
    }),
  updateFieldMapping: (sourceId: string, fieldMapping: Record<string, string | null>) =>
    apiFetch<SiteConfigItem>(`/api/admin/sites/${sourceId}/field-mapping`, {
      method: 'PUT',
      body: JSON.stringify({ field_mapping: fieldMapping }),
    }),
  reset: (sourceId: string, fieldPath: string) =>
    apiFetch<SiteConfigItem>(`/api/admin/sites/${sourceId}/reset`, {
      method: 'POST',
      body: JSON.stringify({ field_path: fieldPath }),
    }),
  resetAdaptive: (sourceId: string) =>
    apiFetch<SiteConfigItem>(`/api/admin/sites/${sourceId}/reset-adaptive`, {
      method: 'POST',
    }),
}

// ── Logs ──────────────────────────────────────────────────────────────

const logs = {
  list: (params?: {
    level?: string[]
    source?: string
    search?: string
    limit?: number
    offset?: number
  }) => {
    const sp = new URLSearchParams()
    if (params?.level) params.level.forEach((l) => sp.append('level', l))
    if (params?.source) sp.set('source', params.source)
    if (params?.search) sp.set('search', params.search)
    if (params?.limit) sp.set('limit', String(params.limit))
    if (params?.offset) sp.set('offset', String(params.offset))
    const qs = sp.toString()
    return apiFetch<{ logs: LogEntry[]; total: number; has_more: boolean }>(
      `/api/logs/${qs ? `?${qs}` : ''}`,
    )
  },
  clear: () => apiFetch<{ status: string; deleted: number }>('/api/logs/', { method: 'DELETE' }),
  getLevels: () => apiFetch<LogLevelConfig>('/api/logs/levels'),
  setLevel: (source: string, level: string) =>
    apiFetch<{ source: string; level: string }>('/api/logs/levels', {
      method: 'PATCH',
      body: JSON.stringify({ source, level }),
    }),
  getRetention: () => apiFetch<{ max_entries: number }>('/api/logs/retention'),
  setRetention: (data: { max_entries: number }) =>
    apiFetch<{ max_entries: number }>('/api/logs/retention', {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),
}

const galleryDl = {
  getVersion: () =>
    apiFetch<{ current: string | null; latest: string | null }>('/api/admin/gallery-dl/version'),
  upgrade: (version?: string) =>
    apiFetch<{ job_id: string }>('/api/admin/gallery-dl/upgrade', {
      method: 'POST',
      body: JSON.stringify(version ? { version } : {}),
    }),
  rollback: () =>
    apiFetch<{ job_id: string }>('/api/admin/gallery-dl/rollback', { method: 'POST' }),
}

// ── Exported API ──────────────────────────────────────────────────────

export const api = {
  auth,
  eh,
  library,
  download,
  settings,
  system,
  tags,
  tokens,
  export: exportApi,
  import_,
  history,
  savedSearches,
  plugins,
  pixiv,
  artists,
  collections,
  scheduledTasks,
  subscriptions,
  subscriptionGroups,
  dedup,
  users,
  logs,
  adminSites,
  galleryDl,
}
