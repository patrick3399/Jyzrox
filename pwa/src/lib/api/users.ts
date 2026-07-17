import { apiFetch } from './client'

import type { UserInfo } from '../types'

// ── Users ─────────────────────────────────────────────────────────────

export const users = {
  list: () => apiFetch<{ users: UserInfo[] }>('/api/users/'),
  create: (data: { username: string; password: string; role: string; email?: string }) =>
    apiFetch<{ id: number; username: string; role: string; email: string | null }>('/api/users/', {
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
