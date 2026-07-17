import { apiFetch } from './client'

import type { FollowedArtist } from '../types'

// ── Artists ───────────────────────────────────────────────────────────

export const artists = {
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
