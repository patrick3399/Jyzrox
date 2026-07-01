import type { EhGallery, EhSearchParams } from '@/lib/types'

export type Tab = 'search' | 'favorites' | 'popular' | 'toplist'

export type Cursor =
  | { kind: 'gid'; nextGid: number }
  | { kind: 'fav'; next: string }
  | { kind: 'page'; page: number }
  | null

export type Filters = {
  selectedCats: string[] // sorted; empty === all categories
  advancedOpen: boolean
  advSearch: number
  minRating: number | null
  pageFrom: number | null
  pageTo: number | null
  favCat: string // 'all' | '0'..'9'
  favSearch: string
  toplistTl: number
}

export type Status = 'idle' | 'seeding' | 'loading' | 'error'

export type EhBrowseState = {
  tab: Tab
  query: string
  filters: Filters
  items: EhGallery[]
  total: number | null
  cursor: Cursor
  hasMore: boolean
  status: Status
  error: string | null
  scrollY: number
}

export const CATEGORY_BITMASK: Record<string, number> = {
  misc: 1,
  doujinshi: 2,
  manga: 4,
  artist_cg: 8,
  game_cg: 16,
  image_set: 32,
  cosplay: 64,
  asian_porn: 128,
  'non-h': 256,
  western: 512,
}
export const ALL_CATS = Object.keys(CATEGORY_BITMASK)
export const ALL_CATS_MASK = Object.values(CATEGORY_BITMASK).reduce((a, b) => a + b, 0)
export const EH_PAGE_SIZE = 25
export const SNAPSHOT_CAP = 300

export const initialFilters: Filters = {
  selectedCats: [],
  advancedOpen: false,
  advSearch: 0,
  minRating: null,
  pageFrom: null,
  pageTo: null,
  favCat: 'all',
  favSearch: '',
  toplistTl: 11,
}

export const initialState: EhBrowseState = {
  tab: 'popular',
  query: '',
  filters: initialFilters,
  items: [],
  total: null,
  cursor: null,
  hasMore: true,
  status: 'idle',
  error: null,
  scrollY: 0,
}

const EMPTY_VIEW = {
  items: [] as EhGallery[],
  total: null,
  cursor: null as Cursor,
  hasMore: true,
  status: 'idle' as Status,
  error: null,
  scrollY: 0,
}

/** Stable identity string: tab + query + filters. Same identity === same results. */
export function queryKey(s: EhBrowseState): string {
  return JSON.stringify({
    tab: s.tab,
    query: s.query,
    f: {
      ...s.filters,
      selectedCats: [...s.filters.selectedCats].sort(),
    },
  })
}

export type Action =
  | { type: 'SET_TAB'; tab: Tab }
  | { type: 'COMMIT_QUERY'; query: string }
  | { type: 'SET_FILTER'; patch: Partial<Filters> }
  | {
      type: 'SEED'
      items: EhGallery[]
      total: number | null
      cursor: Cursor
      hasMore: boolean
    }
  | { type: 'APPEND'; items: EhGallery[]; cursor: Cursor; hasMore: boolean }
  | { type: 'LOAD_START'; seeding: boolean }
  | { type: 'LOAD_ERROR'; error: string }
  | { type: 'SET_SCROLL'; scrollY: number }
  | { type: 'RESTORE'; snapshot: Partial<EhBrowseState> }
  | { type: 'RESET' }

function withIdentityReset(prev: EhBrowseState, next: EhBrowseState): EhBrowseState {
  return queryKey(prev) === queryKey(next) ? next : { ...next, ...EMPTY_VIEW }
}

export function reducer(state: EhBrowseState, action: Action): EhBrowseState {
  switch (action.type) {
    case 'SET_TAB':
      return withIdentityReset(state, { ...state, tab: action.tab })
    case 'COMMIT_QUERY':
      return withIdentityReset(state, { ...state, query: action.query })
    case 'SET_FILTER':
      return withIdentityReset(state, {
        ...state,
        filters: { ...state.filters, ...action.patch },
      })
    case 'LOAD_START':
      return { ...state, status: action.seeding ? 'seeding' : 'loading', error: null }
    case 'SEED':
      return {
        ...state,
        items: action.items,
        total: action.total,
        cursor: action.cursor,
        hasMore: action.hasMore,
        status: 'idle',
        error: null,
      }
    case 'APPEND': {
      const seen = new Set(state.items.map((g) => g.gid))
      const fresh = action.items.filter((g) => !seen.has(g.gid))
      return {
        ...state,
        items: [...state.items, ...fresh],
        cursor: action.cursor,
        hasMore: action.hasMore,
        status: 'idle',
        error: null,
      }
    }
    case 'LOAD_ERROR':
      return { ...state, status: 'error', error: action.error }
    case 'SET_SCROLL':
      return { ...state, scrollY: action.scrollY }
    case 'RESTORE':
      return { ...state, ...action.snapshot }
    case 'RESET':
      return initialState
    default:
      return state
  }
}

export type FetchPlan =
  | { kind: 'search'; args: EhSearchParams }
  | { kind: 'favorites'; args: { favcat?: string; q?: string; next?: string } }
  | { kind: 'toplist'; args: { tl: number; page: number } }
  | { kind: 'popular'; args: Record<string, never> }

function computeFCats(f: Filters): number | undefined {
  // Category selection is always active (independent of the advanced panel).
  // Empty === all categories === no filter.
  const sel = f.selectedCats
  if (sel.length === 0 || sel.length === ALL_CATS.length) return undefined
  let mask = 0
  for (const c of sel) mask |= CATEGORY_BITMASK[c] ?? 0
  return ALL_CATS_MASK ^ mask
}

export function buildParams(s: EhBrowseState): FetchPlan {
  const nextGid = s.cursor?.kind === 'gid' ? s.cursor.nextGid : undefined
  switch (s.tab) {
    case 'favorites':
      return {
        kind: 'favorites',
        args: {
          favcat: s.filters.favCat,
          q: s.filters.favSearch || undefined,
          ...(s.cursor?.kind === 'fav' ? { next: s.cursor.next } : {}),
        },
      }
    case 'toplist':
      return {
        kind: 'toplist',
        args: {
          tl: s.filters.toplistTl,
          page: s.cursor?.kind === 'page' ? s.cursor.page : 0,
        },
      }
    case 'popular':
      return { kind: 'popular', args: {} }
    case 'search':
    default: {
      const f = s.filters
      const advanced =
        f.advancedOpen &&
        (f.advSearch !== 0 || f.minRating !== null || f.pageFrom !== null || f.pageTo !== null)
      return {
        kind: 'search',
        args: {
          q: s.query || undefined,
          ...(nextGid != null ? { next_gid: nextGid } : {}),
          f_cats: computeFCats(f),
          ...(advanced
            ? {
                advance: true,
                adv_search: f.advSearch || undefined,
                min_rating: f.minRating ?? undefined,
                page_from: f.pageFrom ?? undefined,
                page_to: f.pageTo ?? undefined,
              }
            : {}),
        },
      }
    }
  }
}

type Snapshot = {
  queryKey: string
  items: EhGallery[]
  total: number | null
  cursor: Cursor
  hasMore: boolean
  scrollY: number
}

export function serializeSnapshot(s: EhBrowseState): string {
  const snap: Snapshot = {
    queryKey: queryKey(s),
    items: s.items.slice(0, SNAPSHOT_CAP),
    total: s.total,
    cursor: s.cursor,
    hasMore: s.hasMore,
    scrollY: s.scrollY,
  }
  return JSON.stringify(snap)
}

/** Returns the view slice to RESTORE, or null when absent / stale / malformed. */
export function parseSnapshot(
  raw: string | null,
  currentKey: string,
): Partial<EhBrowseState> | null {
  if (!raw) return null
  try {
    const snap = JSON.parse(raw) as Snapshot
    if (!snap || snap.queryKey !== currentKey || !Array.isArray(snap.items)) return null
    return {
      items: snap.items,
      total: snap.total,
      cursor: snap.cursor,
      hasMore: snap.hasMore,
      scrollY: snap.scrollY,
      status: 'idle',
    }
  } catch {
    return null
  }
}

const CATEGORY_KEYS = new Set(ALL_CATS)

export function identityToUrlParams(s: EhBrowseState): URLSearchParams {
  const p = new URLSearchParams()
  if (s.query) p.set('q', s.query)
  if (s.tab !== 'search') p.set('tab', s.tab)
  const f = s.filters
  if (f.advancedOpen) p.set('adv_open', '1')
  if (f.selectedCats.length > 0 && f.selectedCats.length < ALL_CATS.length) {
    p.set('cat', [...f.selectedCats].sort().join(','))
  }
  if (f.advSearch !== 0) p.set('adv', String(f.advSearch))
  if (f.minRating !== null) p.set('minrating', String(f.minRating))
  if (f.pageFrom !== null) p.set('pfrom', String(f.pageFrom))
  if (f.pageTo !== null) p.set('pto', String(f.pageTo))
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
  const selectedCats = catParam ? catParam.split(',').filter((k) => CATEGORY_KEYS.has(k)) : []
  const num = (v: string | null): number | null => (v != null && v !== '' ? Number(v) : null)
  return {
    tab,
    query: q,
    filters: {
      ...initialFilters,
      advancedOpen: sp.get('adv_open') === '1',
      selectedCats,
      advSearch: sp.get('adv') ? Number(sp.get('adv')) : 0,
      minRating: num(sp.get('minrating')),
      pageFrom: num(sp.get('pfrom')),
      pageTo: num(sp.get('pto')),
      favCat: sp.get('favcat') || 'all',
      favSearch: sp.get('favsearch') || '',
      toplistTl: sp.get('tl') ? Number(sp.get('tl')) : 11,
    },
  }
}
