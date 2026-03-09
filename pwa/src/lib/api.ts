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
} from './types'

// ── Base fetch ───────────────────────────────────────────────────────

function getCookie(name: string): string | undefined {
  if (typeof document === 'undefined') return undefined
  const match = document.cookie.match(new RegExp(`(?:^|; )${name}=([^;]*)`))
  return match ? decodeURIComponent(match[1]) : undefined
}

let isRedirecting = false

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
    const raw = body?.detail
    const msg = typeof raw === 'string' ? raw : raw ? JSON.stringify(raw) : `HTTP ${res.status}`
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
  getImagesPaginated: (
    gid: number,
    token: string,
    startPage: number = 0,
    count: number = 20,
  ) =>
    apiFetch<{
      images: Array<{ page: number; token: string }>
      previews: Record<string, string>
      has_more: boolean
      total: number
    }>(`/api/eh/gallery/${gid}/${token}/images-paginated?start_page=${startPage}&count=${count}`),
}

// ── Library ───────────────────────────────────────────────────────────

const library = {
  getGalleries: (params: GallerySearchParams = {}) =>
    apiFetch<GalleryListResponse>(`/api/library/galleries${qs(params as Record<string, unknown>)}`),

  getGallery: (id: number) => apiFetch<Gallery>(`/api/library/galleries/${id}`),

  getImages: (id: number, opts?: { page?: number; limit?: number }) => {
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
    }>(`/api/library/galleries/${id}/images${qs ? `?${qs}` : ''}`)
  },

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

  getEhSite: () =>
    apiFetch<{ use_ex: boolean }>('/api/settings/eh-site'),

  setEhSite: (use_ex: boolean) =>
    apiFetch<{ use_ex: boolean }>('/api/settings/eh-site', {
      method: 'PATCH',
      body: JSON.stringify({ use_ex }),
    }),

  getAlerts: () => apiFetch<{ alerts: string[] }>('/api/settings/alerts'),

  getRateLimit: () =>
    apiFetch<{ enabled: boolean; login_max: number; window: number }>('/api/settings/rate-limit'),

  setRateLimit: (enabled: boolean) =>
    apiFetch<{ enabled: boolean }>('/api/settings/rate-limit', {
      method: 'PATCH',
      body: JSON.stringify({ enabled }),
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
  clearCache: () => apiFetch<{ deleted_keys: number }>('/api/system/cache', { method: 'DELETE' }),
  clearCacheCategory: (category: string) =>
    apiFetch<{ deleted_keys: number }>(`/api/system/cache/${category}`, { method: 'DELETE' }),
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

  getTranslations: (tags: string[]) =>
    apiFetch<Record<string, string>>(`/api/tags/translations${qs({ tags: tags.join(',') })}`),

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
  browse: (path = '', library = '') => {
    const params = new URLSearchParams()
    if (path) params.set('path', path)
    if (library) params.set('library', library)
    return apiFetch<{
      path: string
      base: string
      entries: Array<{ name: string; type: 'dir' | 'file'; file_count?: number; size?: number; imported?: boolean }>
    }>(`/api/import/browse?${params}`)
  },

  start: (sourceDir: string, title?: string) =>
    apiFetch<{ status: string; gallery_id: number }>('/api/import/', {
      method: 'POST',
      body: JSON.stringify({
        source_dir: sourceDir,
        mode: 'copy',
        metadata: title ? { title } : undefined,
      }),
    }),

  rescanLibraryPath: (libraryId: number) =>
    apiFetch<{ status: string }>(`/api/import/rescan/path/${libraryId}`, { method: 'POST' }),

  progress: (galleryId: number) =>
    apiFetch<{ gallery_id: number; processed: number; total: number; status: string }>(
      `/api/import/progress/${galleryId}`,
    ),

  recent: () =>
    apiFetch<Array<{ id: number; title: string; pages: number; status: string; added_at: string }>>(
      '/api/import/recent',
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

  rescanCancel: () =>
    apiFetch<{ status: string }>('/api/import/rescan/cancel', { method: 'POST' }),

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

  discover: () =>
    apiFetch<{ status: string }>('/api/import/discover', { method: 'POST' }),

  monitorStatus: () =>
    apiFetch<{ enabled: boolean; running: boolean; watched_paths: string[] }>(
      '/api/import/monitor/status',
    ),

  toggleMonitor: (enabled: boolean) =>
    apiFetch<{ status: string }>('/api/import/monitor/toggle', {
      method: 'POST',
      body: JSON.stringify({ enabled }),
    }),

  scanSettings: () =>
    apiFetch<{ enabled: boolean; interval_hours: number; last_run: string | null }>(
      '/api/import/scan-settings',
    ),

  updateScanSettings: (settings: { enabled?: boolean; interval_hours?: number }) =>
    apiFetch<{ enabled: boolean; interval_hours: number; last_run: string | null }>(
      '/api/import/scan-settings',
      {
        method: 'PATCH',
        body: JSON.stringify(settings),
      },
    ),

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
}
