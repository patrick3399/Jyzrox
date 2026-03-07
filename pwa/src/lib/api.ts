import type {
  Gallery, GalleryImage, GallerySearchParams,
  EhGallery, EhSearchResult, EhImageMap, EhSearchParams,
  DownloadJob, JobListParams,
  Credentials, EhAccount,
  ReadProgress,
  SystemHealth, SystemInfo,
} from './types'

// ── Base fetch ───────────────────────────────────────────────────────

async function apiFetch<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const res = await fetch(path, {
    credentials: 'include',   // always send vault_token cookie
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })

  if (!res.ok) {
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

  logout: () =>
    apiFetch<{ status: string }>('/api/auth/logout', { method: 'POST' }),

  needsSetup: () =>
    apiFetch<{ needs_setup: boolean }>('/api/auth/needs-setup'),
}

// ── E-Hentai ─────────────────────────────────────────────────────────

const eh = {
  search: (params: EhSearchParams = {}) =>
    apiFetch<EhSearchResult>(`/api/eh/search${qs(params as Record<string, unknown>)}`),

  getGallery: (gid: number, token: string) =>
    apiFetch<EhGallery>(`/api/eh/gallery/${gid}/${token}`),

  getImages: (gid: number, token: string) =>
    apiFetch<EhImageMap>(`/api/eh/gallery/${gid}/${token}/images`),

  /** Returns the URL string — caller uses it as <img src> */
  imageProxyUrl: (gid: number, page: number): string =>
    `/api/eh/image-proxy/${gid}/${page}`,
}

// ── Library ───────────────────────────────────────────────────────────

const library = {
  getGalleries: (params: GallerySearchParams = {}) =>
    apiFetch<{ total: number; page: number; galleries: Gallery[] }>(
      `/api/library/galleries${qs(params as Record<string, unknown>)}`
    ),

  getGallery: (id: number) =>
    apiFetch<Gallery>(`/api/library/galleries/${id}`),

  getImages: (id: number) =>
    apiFetch<{ gallery_id: number; images: GalleryImage[] }>(
      `/api/library/galleries/${id}/images`
    ),

  updateGallery: (id: number, patch: { favorited?: boolean; rating?: number }) =>
    apiFetch<Gallery>(`/api/library/galleries/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(patch),
    }),

  getProgress: (id: number) =>
    apiFetch<ReadProgress>(`/api/library/galleries/${id}/progress`),

  saveProgress: (id: number, last_page: number) =>
    apiFetch<{ status: string }>(`/api/library/galleries/${id}/progress`, {
      method: 'POST',
      body: JSON.stringify({ last_page }),
    }),
}

// ── Download ──────────────────────────────────────────────────────────

const download = {
  enqueue: (url: string, source = '', options: Record<string, unknown> = {}) =>
    apiFetch<{ job_id: string; status: string }>('/api/download/', {
      method: 'POST',
      body: JSON.stringify({ url, source, options }),
    }),

  getJobs: (params: JobListParams = {}) =>
    apiFetch<{ total: number; jobs: DownloadJob[] }>(
      `/api/download/jobs${qs(params as Record<string, unknown>)}`
    ),

  getJob: (id: string) =>
    apiFetch<DownloadJob>(`/api/download/jobs/${id}`),

  cancelJob: (id: string) =>
    apiFetch<{ status: string }>(`/api/download/jobs/${id}`, {
      method: 'DELETE',
    }),
}

// ── Settings ──────────────────────────────────────────────────────────

const settings = {
  getCredentials: () =>
    apiFetch<Credentials>('/api/settings/credentials'),

  ehLogin: (username: string, password: string) =>
    apiFetch<{ status: string; account: EhAccount }>(
      '/api/settings/credentials/ehentai/login',
      { method: 'POST', body: JSON.stringify({ username, password }) }
    ),

  setEhCookies: (data: {
    ipb_member_id: string
    ipb_pass_hash: string
    sk: string
  }) =>
    apiFetch<{ status: string; account: EhAccount }>(
      '/api/settings/credentials/ehentai',
      { method: 'POST', body: JSON.stringify(data) }
    ),

  setPixivToken: (refresh_token: string) =>
    apiFetch<{ status: string; username: string }>(
      '/api/settings/credentials/pixiv',
      { method: 'POST', body: JSON.stringify({ refresh_token }) }
    ),

  getEhAccount: () =>
    apiFetch<EhAccount>('/api/settings/eh/account'),

  getAlerts: () =>
    apiFetch<{ alerts: string[] }>('/api/settings/alerts'),
}

// ── System ────────────────────────────────────────────────────────────

const system = {
  health: () => apiFetch<SystemHealth>('/api/system/health'),
  info: () => apiFetch<SystemInfo>('/api/system/info'),
}

// ── Exported API ──────────────────────────────────────────────────────

export const api = { auth, eh, library, download, settings, system }
