import { getLocale, t } from '@/lib/i18n'

// ── Base fetch ───────────────────────────────────────────────────────

export function getCookie(name: string): string | undefined {
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

// Exposed so other modules (e.g. auth.uploadAvatar, which bypasses apiFetch
// to stream a FormData body) can share the same redirect-once guard.
export function getIsRedirecting(): boolean {
  return isRedirecting
}

export function setIsRedirecting(value: boolean): void {
  isRedirecting = value
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'Accept-Language': getLocale(),
  }
  if (typeof FormData !== 'undefined' && options.body instanceof FormData) {
    delete headers['Content-Type']
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
    const body = await res.json().catch(() => ({}))
    const raw = body?.detail
    // Forbidden → redirect to /forbidden, but only for app-level RBAC denials.
    // Source-specific 403s (e.g. eh_access_denied / eh_bandwidth_exceeded) carry
    // a recognized error code and must surface as a normal error instead of
    // hijacking the whole page with a generic "Access Denied" message.
    const hasSourceErrorCode =
      typeof raw === 'object' && raw !== null && typeof raw.code === 'string'
    if (res.status === 403 && !hasSourceErrorCode && typeof window !== 'undefined') {
      const p = window.location.pathname
      if (p !== '/forbidden' && !isRedirecting) {
        isRedirecting = true
        window.location.href = '/forbidden'
      }
      throw new Error('Forbidden')
    }
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

export function qs(params: Record<string, unknown>): string {
  const p = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null) continue
    if (Array.isArray(v)) v.forEach((item) => p.append(k, String(item)))
    else p.set(k, String(v))
  }
  const s = p.toString()
  return s ? `?${s}` : ''
}

export function encodeOpaquePathId(value: string): string {
  return encodeURIComponent(encodeURIComponent(value))
}

export function galleryApiPath(source: string, sourceId: string, suffix = ''): string {
  return `/api/library/galleries/${encodeURIComponent(source)}/${encodeOpaquePathId(sourceId)}${suffix}`
}
