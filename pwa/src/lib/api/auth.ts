import { apiFetch, getCookie, getIsRedirecting, setIsRedirecting } from './client'

import type { SessionInfo } from '../types'

// ── Auth ─────────────────────────────────────────────────────────────

export const auth = {
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

  updateProfile: (data: { email?: string | null; avatar_style?: string; locale?: string | null }) =>
    apiFetch<{ status: string }>('/api/auth/profile', {
      method: 'PATCH',
      body: JSON.stringify(data),
    }),

  getUiPreferences: () =>
    apiFetch<{ preferences: import('../uiPreferences').UiPreferences }>(
      '/api/auth/ui-preferences',
    ),

  updateUiPreferences: (data: import('../uiPreferences').UiPreferencesPatch) =>
    apiFetch<{ status: string; preferences: import('../uiPreferences').UiPreferences }>(
      '/api/auth/ui-preferences',
      { method: 'PATCH', body: JSON.stringify(data) },
    ),

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
        if (p !== '/login' && p !== '/setup' && !getIsRedirecting()) {
          setIsRedirecting(true)
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
