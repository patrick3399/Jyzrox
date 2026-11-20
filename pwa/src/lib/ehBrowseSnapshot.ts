import type { EhGallery } from '@/lib/types'
import type { BrowseAnchor } from '@/lib/browse/anchor'
import type { BrowseLayoutSnapshot } from '@/lib/browse/snapshotStore'
import {
  normalizeEhAdvancedSearch,
  normalizeEhCategories,
  normalizeEhFavoriteCategory,
  normalizeEhPageBound,
  normalizeEhRating,
  normalizeEhToplistPeriod,
} from '@/lib/browse/ehentai'

import { Tab, Cursor, EhBrowseState, ALL_CATS, initialFilters, queryKey } from './ehBrowseStateBase'

type Snapshot = {
  queryKey: string
  items: EhGallery[]
  total: number | null
  cursor: Cursor
  hasMore: boolean
  scrollY: number
  anchor?: BrowseAnchor | null
  layout?: BrowseLayoutSnapshot | null
}

// The active snapshot must keep its item buffer, cursor, and scroll position as
// one consistent unit. The former 300-item slice paired an early item buffer
// with a later cursor/scroll offset, which could skip results after back-nav.
// Keep the current view whole and evict older identities to stay within a
// conservative sessionStorage budget.
type SnapshotStore = { version: 2; snaps: Snapshot[] }
export const SNAPSHOT_HISTORY_CAP = 8
export const SNAPSHOT_STORE_CHAR_CAP = 2_000_000

function parseStore(raw: string | null): Snapshot[] {
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw) as SnapshotStore
    // Version 1 snapshots may contain the inconsistent 300-item head + latest
    // cursor combination. Discard them rather than restoring a view that can skip.
    if (!parsed || parsed.version !== 2 || !Array.isArray(parsed.snaps)) return []
    return parsed.snaps.filter((x) => x && typeof x.queryKey === 'string' && Array.isArray(x.items))
  } catch {
    return []
  }
}

/** Upsert this state's view into the snapshot store (MRU-first, capped). */
export function serializeSnapshot(s: EhBrowseState, prevRaw: string | null = null): string {
  const snap: Snapshot = {
    queryKey: queryKey(s),
    items: s.items,
    total: s.total,
    cursor: s.cursor,
    hasMore: s.hasMore,
    scrollY: s.scrollY,
    anchor: s.anchor,
    layout: s.layout,
  }
  const rest = parseStore(prevRaw).filter((x) => x.queryKey !== snap.queryKey)
  const selected: Snapshot[] = []
  for (const candidate of [snap, ...rest].slice(0, SNAPSHOT_HISTORY_CAP)) {
    const next = [...selected, candidate]
    const serialized = JSON.stringify({ version: 2, snaps: next } satisfies SnapshotStore)
    if (serialized.length <= SNAPSHOT_STORE_CHAR_CAP) {
      selected.push(candidate)
      continue
    }
    if (selected.length === 0) {
      // An exceptionally large active view cannot be saved safely. Restarting
      // from page one is preferable to restoring stale cursor/scroll metadata.
      const reset: Snapshot = {
        ...candidate,
        items: [],
        total: null,
        cursor: null,
        hasMore: true,
        scrollY: 0,
        anchor: null,
        layout: null,
      }
      return JSON.stringify({ version: 2, snaps: [reset] } satisfies SnapshotStore)
    }
    break
  }
  return JSON.stringify({ version: 2, snaps: selected } satisfies SnapshotStore)
}

/** Returns the view slice to RESTORE for `currentKey`, or null when absent / malformed. */
export function parseSnapshot(
  raw: string | null,
  currentKey: string,
): Partial<EhBrowseState> | null {
  const snap = parseStore(raw).find((x) => x.queryKey === currentKey)
  if (!snap) return null
  return {
    items: snap.items,
    total: snap.total,
    cursor: snap.cursor,
    hasMore: snap.hasMore,
    scrollY: snap.scrollY,
    anchor: snap.anchor ?? null,
    layout: snap.layout ?? null,
    status: 'idle',
  }
}

const CATEGORY_KEYS = new Set(ALL_CATS)

export function identityToUrlParams(s: EhBrowseState): URLSearchParams {
  const p = new URLSearchParams()
  if (s.ephemeralSession) {
    p.set('tab', 'search')
    p.set('image_session', s.ephemeralSession)
    return p
  }
  if (s.tab === 'search' && s.query) p.set('q', s.query)
  // The Latest tab is `search` + empty query. `q=` alone implies the search tab,
  // so a query search omits `tab`; but with no query we MUST still mark the tab,
  // otherwise it serializes to a bare URL — indistinguishable from the popular
  // home default, which useEhBrowse treats as an external "reset to popular".
  if (s.tab !== 'search' || !s.query) p.set('tab', s.tab)
  const f = s.filters
  if (s.tab === 'search') {
    if (f.advancedOpen) p.set('adv_open', '1')
    const categories = normalizeEhCategories(f.selectedCats)
    if (categories.length > 0 && categories.length < ALL_CATS.length) {
      p.set('cat', categories.join(','))
    }
    const advSearch = normalizeEhAdvancedSearch(f.advSearch)
    if (advSearch !== 0) p.set('adv', String(advSearch))
    if (f.minRating !== null) p.set('minrating', String(f.minRating))
    if (f.pageFrom !== null) p.set('pfrom', String(f.pageFrom))
    if (f.pageTo !== null) p.set('pto', String(f.pageTo))
    if (f.language) p.set('language', f.language)
  }
  if (s.tab === 'favorites' && f.favCat !== 'all') p.set('favcat', f.favCat)
  if (s.tab === 'favorites' && f.favSearch) p.set('favsearch', f.favSearch)
  if (s.tab === 'toplist' && f.toplistTl !== 11) p.set('tl', String(f.toplistTl))
  return p
}

export function parseUrlToIdentity(
  sp: URLSearchParams,
): Pick<EhBrowseState, 'tab' | 'query' | 'filters'> {
  const rawTab = sp.get('tab')
  const q = sp.get('q') || ''
  const tab: Tab =
    rawTab === 'favorites' || rawTab === 'toplist' || rawTab === 'search'
      ? rawTab
      : q
        ? 'search'
        : 'popular'
  const catParam = sp.get('cat')
  const selectedCats = normalizeEhCategories(
    catParam ? catParam.split(',').filter((k) => CATEGORY_KEYS.has(k)) : [],
  )
  const num = (v: string | null): number | null => (v != null && v !== '' ? Number(v) : null)
  return {
    tab,
    query: tab === 'search' ? q : '',
    filters: {
      ...initialFilters,
      advancedOpen: sp.get('adv_open') === '1',
      selectedCats,
      advSearch: normalizeEhAdvancedSearch(sp.get('adv') ? Number(sp.get('adv')) : 0),
      minRating: normalizeEhRating(num(sp.get('minrating'))),
      pageFrom: normalizeEhPageBound(num(sp.get('pfrom'))),
      pageTo: normalizeEhPageBound(num(sp.get('pto'))),
      language: sp.get('language') || '',
      favCat: normalizeEhFavoriteCategory(sp.get('favcat') || 'all'),
      favSearch: sp.get('favsearch') || '',
      toplistTl: normalizeEhToplistPeriod(sp.get('tl') ? Number(sp.get('tl')) : 11),
    },
  }
}

export function serializeEhSavedSearchParams(state: EhBrowseState): Record<string, unknown> {
  return {
    source: 'ehentai',
    version: 1,
    identity: identityToUrlParams(state).toString(),
  }
}

export function parseEhSavedSearch(
  query: string,
  params: Record<string, unknown>,
): Pick<EhBrowseState, 'tab' | 'query' | 'filters'> {
  if (params.source === 'ehentai' && typeof params.identity === 'string') {
    const searchParams = new URLSearchParams(params.identity)
    searchParams.set('q', query)
    return parseUrlToIdentity(searchParams)
  }
  return parseUrlToIdentity(new URLSearchParams(query ? { q: query } : { tab: 'search' }))
}
