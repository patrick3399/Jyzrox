import type { EhGallery } from '@/lib/types'

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
