import { canonicalIdentityKey } from './identity'

export const PIXIV_BROWSE_SOURCE_ID = 'pixiv'
export const PIXIV_BROWSE_SCHEMA_VERSION = 1

export type PixivSearchBackend = 'authenticated' | 'public'

export type PixivBrowseIdentity = { backend?: PixivSearchBackend } & (
  | { surface: 'ranking'; mode: string; content: string; r18: boolean }
  | { surface: 'feed' }
  | { surface: 'following'; restrict: 'public' }
  | { surface: 'bookmarks'; restrict: 'public' | 'private' }
  | {
      surface: 'search'
      query: string
      sort: string
      duration: string
      backend: PixivSearchBackend
    }
)

export type PixivCursor = { kind: 'offset'; value: number } | { kind: 'page'; value: number }

export type PixivBrowseItem =
  | { kind: 'illust'; illust: { id: number } & Record<string, unknown> }
  | { kind: 'ranking'; entry: { illust_id: number } & Record<string, unknown> }
  | {
      kind: 'user'
      preview: { user: { id: number } & Record<string, unknown> } & Record<string, unknown>
    }

const RANKING_MODES = new Set(['daily', 'weekly', 'monthly', 'rookie'])
const RANKING_CONTENT = new Set(['all', 'illust', 'manga', 'ugoira'])
const SEARCH_SORTS = new Set(['date_desc', 'date_asc', 'popular_desc'])
const SEARCH_DURATIONS = new Set(['', 'within_last_day', 'within_last_week', 'within_last_month'])

const DEFAULT_RANKING: PixivBrowseIdentity = {
  surface: 'ranking',
  mode: 'daily',
  content: 'all',
  r18: false,
}

function oneOf(value: unknown, allowed: Set<string>, fallback: string): string {
  return typeof value === 'string' && allowed.has(value) ? value : fallback
}

export function canonicalPixivIdentity(identity: PixivBrowseIdentity): PixivBrowseIdentity {
  switch (identity.surface) {
    case 'ranking': {
      const r18 = identity.r18 === true
      const requestedMode = oneOf(identity.mode, RANKING_MODES, 'daily')
      return {
        surface: 'ranking',
        mode:
          r18 && requestedMode !== 'daily' && requestedMode !== 'weekly' ? 'daily' : requestedMode,
        content: r18 ? 'all' : oneOf(identity.content, RANKING_CONTENT, 'all'),
        r18,
      }
    }
    case 'feed':
      return { surface: 'feed' }
    case 'following':
      return { surface: 'following', restrict: 'public' }
    case 'bookmarks':
      return {
        surface: 'bookmarks',
        restrict: identity.restrict === 'private' ? 'private' : 'public',
      }
    case 'search': {
      const query = identity.query.trim()
      if (!query) return DEFAULT_RANKING
      return {
        surface: 'search',
        query,
        sort: oneOf(identity.sort, SEARCH_SORTS, 'date_desc'),
        duration: oneOf(identity.duration, SEARCH_DURATIONS, ''),
        backend: identity.backend === 'public' ? 'public' : 'authenticated',
      }
    }
  }
}

export function parsePixivIdentity(
  params: URLSearchParams,
  backend: PixivSearchBackend,
): PixivBrowseIdentity {
  const tab = params.get('tab')
  if (tab === 'search') {
    return canonicalPixivIdentity({
      surface: 'search',
      query: params.get('q') ?? '',
      sort: params.get('sort') ?? 'date_desc',
      duration: params.get('duration') ?? '',
      backend,
    })
  }
  if (tab === 'feed') return { surface: 'feed' }
  if (tab === 'following') return { surface: 'following', restrict: 'public' }
  if (tab === 'bookmarks') {
    return canonicalPixivIdentity({
      surface: 'bookmarks',
      restrict: params.get('restrict') === 'private' ? 'private' : 'public',
    })
  }
  if (tab !== null && tab !== 'ranking') return DEFAULT_RANKING
  return canonicalPixivIdentity({
    surface: 'ranking',
    mode: params.get('mode') ?? 'daily',
    content: params.get('content') ?? 'all',
    r18: params.get('r18') === '1',
  })
}

export function serializePixivIdentity(identity: PixivBrowseIdentity): URLSearchParams {
  const canonical = canonicalPixivIdentity(identity)
  const params = new URLSearchParams()
  params.set('tab', canonical.surface)
  switch (canonical.surface) {
    case 'ranking':
      if (canonical.mode !== 'daily') params.set('mode', canonical.mode)
      if (canonical.content !== 'all') params.set('content', canonical.content)
      if (canonical.r18) params.set('r18', '1')
      break
    case 'bookmarks':
      if (canonical.restrict !== 'public') params.set('restrict', canonical.restrict)
      break
    case 'search':
      params.set('q', canonical.query)
      if (canonical.sort !== 'date_desc') params.set('sort', canonical.sort)
      if (canonical.duration) params.set('duration', canonical.duration)
      break
  }
  return params
}

export function pixivIdentityKey(identity: PixivBrowseIdentity): string {
  return canonicalIdentityKey(canonicalPixivIdentity(identity))
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value > 0
}

export function isPixivCursor(value: unknown): value is PixivCursor {
  if (!isRecord(value)) return false
  return (
    (value.kind === 'offset' &&
      typeof value.value === 'number' &&
      Number.isInteger(value.value) &&
      value.value >= 0) ||
    (value.kind === 'page' && isPositiveInteger(value.value))
  )
}

export function isPixivBrowseItem(value: unknown): value is PixivBrowseItem {
  if (!isRecord(value)) return false
  if (value.kind === 'illust') return isRecord(value.illust) && isPositiveInteger(value.illust.id)
  if (value.kind === 'ranking') {
    return isRecord(value.entry) && isPositiveInteger(value.entry.illust_id)
  }
  return (
    value.kind === 'user' &&
    isRecord(value.preview) &&
    isRecord(value.preview.user) &&
    isPositiveInteger(value.preview.user.id)
  )
}

const PIXIV_LEGACY_KEYS = [
  'pixiv_ranking_scrollY',
  'pixiv_feed_scrollY',
  'pixiv_bookmarks_scrollY',
  'pixiv_search_scrollY',
] as const

export function clearPixivLegacyBrowseState(storage: Storage): void {
  for (const key of PIXIV_LEGACY_KEYS) {
    try {
      storage.removeItem(key)
    } catch {
      // Legacy cleanup is best effort; continue invalidating the remaining keys.
    }
  }
}
