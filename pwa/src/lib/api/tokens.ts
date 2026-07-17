import { apiFetch, qs } from './client'

import type { ApiTokenInfo } from '../types'

// ── API Tokens ───────────────────────────────────────────────────────

export const tokens = {
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
