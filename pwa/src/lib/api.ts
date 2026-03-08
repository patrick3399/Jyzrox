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
} from './types'

// ── Base fetch ───────────────────────────────────────────────────────

let isRedirecting = false

async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(path, {
    credentials: 'include', // always send vault_token cookie
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })

  if (!res.ok) {
    // Stale session → redirect to login (skip if already on /login or /setup)
    if (res.status === 401 && typeof window !== 'undefined') {
      const p = window.location.pathname
      if (p !== '/login' && p !== '/setup' && !isRedirecting) {
        isRedirecting = true
        window.location.href = '/login'
      }
      throw new Error('Unauthorized')
    }
    const body = await res.json().catch(() => ({}))
    const msg = body?.detail || `HTTP ${res.status}`
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
    }>('/api/auth/profile'),

  updateProfile: (data: { email?: string | null; avatar_style?: string }) =>
    apiFetch<{ status: string }>('/api/auth/profile', {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),

  uploadAvatar: async (
    file: File,
  ): Promise<{ status: string; avatar_url: string; avatar_style: string }> => {
    const form = new FormData()
    form.append('file', file)
    const res = await fetch('/api/auth/avatar', {
      method: 'PUT',
      credentials: 'include',
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
}

// ── Library ───────────────────────────────────────────────────────────

const library = {
  getGalleries: (params: GallerySearchParams = {}) =>
    apiFetch<GalleryListResponse>(`/api/library/galleries${qs(params as Record<string, unknown>)}`),

  getGallery: (id: number) => apiFetch<Gallery>(`/api/library/galleries/${id}`),

  getImages: (id: number) =>
    apiFetch<{ gallery_id: number; images: GalleryImage[] }>(`/api/library/galleries/${id}/images`),

  updateGallery: (id: number, patch: { favorited?: boolean; rating?: number }) =>
    apiFetch<Gallery>(`/api/library/galleries/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  deleteGallery: (id: number) =>
    apiFetch<{ status: string; deleted_files: number }>(`/api/library/galleries/${id}`, {
      method: 'DELETE',
    }),

  getProgress: (id: number) => apiFetch<ReadProgress>(`/api/library/galleries/${id}/progress`),

  saveProgress: (id: number, last_page: number) =>
    apiFetch<{ status: string }>(`/api/library/galleries/${id}/progress`, {
      method: 'POST',
      body: JSON.stringify({ last_page }),
    }),
}

// ── Download ──────────────────────────────────────────────────────────

const download = {
  enqueue: (url: string, source?: string, options: Record<string, unknown> = {}, total?: number) =>
    apiFetch<{ job_id: string; status: string }>('/api/download/', {
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

  getStats: () => apiFetch<{ running: number; finished: number }>('/api/download/stats'),

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
    sk: string
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

  deleteCredential: (source: 'ehentai' | 'pixiv') =>
    apiFetch<{ status: string }>(`/api/settings/credentials/${source}`, { method: 'DELETE' }),

  getAlerts: () => apiFetch<{ alerts: string[] }>('/api/settings/alerts'),

  getRateLimit: () =>
    apiFetch<{ enabled: boolean; login_max: number; window: number }>('/api/settings/rate-limit'),

  setRateLimit: (enabled: boolean) =>
    apiFetch<{ enabled: boolean }>('/api/settings/rate-limit', {
      method: 'PATCH',
      body: JSON.stringify({ enabled }),
    }),
}

// ── System ────────────────────────────────────────────────────────────

const system = {
  health: () => apiFetch<SystemHealth>('/api/system/health'),
  info: () => apiFetch<SystemInfo>('/api/system/info'),
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

// ── Export ────────────────────────────────────────────────────────────

const exportApi = {
  kohyaUrl: (galleryId: number): string => `/api/export/kohya/${galleryId}`,
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
}
