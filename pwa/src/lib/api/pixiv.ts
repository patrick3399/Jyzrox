import { apiFetch } from './client'

import type { PixivIllust, PixivSearchResult, PixivUserResult, PixivCollectionState, PixivUserPreview } from '../types'

// ── Pixiv ─────────────────────────────────────────────────────────────

export const pixiv = {
  search: (
    params: {
      word?: string
      sort?: string
      search_target?: string
      duration?: string
      offset?: number
    } = {},
    init?: RequestInit,
  ) => {
    const p = new URLSearchParams()
    if (params.word) p.set('word', params.word)
    if (params.sort) p.set('sort', params.sort)
    if (params.search_target) p.set('search_target', params.search_target)
    if (params.duration) p.set('duration', params.duration)
    if (params.offset) p.set('offset', String(params.offset))
    return apiFetch<PixivSearchResult>(`/api/pixiv/search?${p}`, init)
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
    init?: RequestInit,
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
      init,
    )
  },

  getIllust: (id: number, init?: RequestInit) =>
    apiFetch<PixivIllust>(`/api/pixiv/illust/${id}`, init),

  getIllustPages: (id: number, init?: RequestInit) =>
    apiFetch<{ pages: Array<{ page_num: number; url: string }>; page_count: number }>(
      `/api/pixiv/illust/${id}/pages`,
      init,
    ),

  getUser: (id: number, init?: RequestInit) =>
    apiFetch<PixivUserResult>(`/api/pixiv/user/${id}`, init),

  getUserCollection: (id: number, init?: RequestInit) =>
    apiFetch<PixivCollectionState>(`/api/pixiv/user/${id}/collection`, init),

  syncUserCollection: (id: number, fullReconcile = false, init?: RequestInit) =>
    apiFetch<{ status: string; job_id: string }>(
      `/api/pixiv/user/${id}/collection/sync?full_reconcile=${fullReconcile}`,
      { method: 'POST', ...init },
    ),

  subscribeUserCollection: (id: number, init?: RequestInit) =>
    apiFetch<{ status: string; subscription_id: number }>(
      `/api/pixiv/user/${id}/collection/subscription`,
      { method: 'POST', ...init },
    ),

  unsubscribeUserCollection: (id: number, init?: RequestInit) =>
    apiFetch<{ status: string }>(`/api/pixiv/user/${id}/collection/subscription`, {
      method: 'DELETE',
      ...init,
    }),

  getUserIllusts: (id: number, offset = 0, init?: RequestInit) =>
    apiFetch<PixivSearchResult>(`/api/pixiv/user/${id}/illusts?offset=${offset}`, init),

  getUserBookmarks: (id: number, offset = 0, init?: RequestInit) =>
    apiFetch<PixivSearchResult>(`/api/pixiv/user/${id}/bookmarks?offset=${offset}`, init),

  getMyBookmarks: (restrict = 'public', offset = 0, init?: RequestInit) =>
    apiFetch<PixivSearchResult>(`/api/pixiv/bookmarks?restrict=${restrict}&offset=${offset}`, init),

  getFollowingFeed: (offset = 0, init?: RequestInit) =>
    apiFetch<PixivSearchResult>(`/api/pixiv/following/feed?offset=${offset}`, init),

  getFollowing: (restrict = 'public', offset = 0, init?: RequestInit) =>
    apiFetch<{ user_previews: PixivUserPreview[]; next_offset: number | null }>(
      `/api/pixiv/following?restrict=${restrict}&offset=${offset}`,
      init,
    ),

  imageProxyUrl: (url: string) => `/api/pixiv/image-proxy?url=${encodeURIComponent(url)}`,

  addBookmark: (id: number, restrict: 'public' | 'private' = 'public', init?: RequestInit) =>
    apiFetch<{ ok: boolean }>(`/api/pixiv/illust/${id}/bookmark?restrict=${restrict}`, {
      method: 'POST',
      ...init,
    }),

  deleteBookmark: (id: number, init?: RequestInit) =>
    apiFetch<{ ok: boolean }>(`/api/pixiv/illust/${id}/bookmark`, { method: 'DELETE', ...init }),

  getBookmarkStatus: (id: number, init?: RequestInit) =>
    apiFetch<{ is_bookmarked: boolean }>(`/api/pixiv/illust/${id}/bookmark`, init),

  followUser: (id: number, init?: RequestInit) =>
    apiFetch<{ ok: boolean }>(`/api/pixiv/user/${id}/follow`, { method: 'POST', ...init }),

  unfollowUser: (id: number, init?: RequestInit) =>
    apiFetch<{ ok: boolean }>(`/api/pixiv/user/${id}/follow`, { method: 'DELETE', ...init }),

  ranking: (
    params: { mode?: string; content?: string; date?: string; page?: number } = {},
    init?: RequestInit,
  ) => {
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
    }>(`/api/pixiv/ranking?${p}`, init)
  },
}
