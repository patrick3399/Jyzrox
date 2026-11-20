import type { EhGallery, EhSearchParams } from '@/lib/types'
import type { BrowseAnchor } from '@/lib/browse/anchor'
import type { BrowseLayoutSnapshot } from '@/lib/browse/snapshotStore'
import { canonicalEhIdentity, type EhCanonicalIdentity } from '@/lib/browse/ehentai'

import {
  Tab,
  Cursor,
  Filters,
  EhBrowseState,
  CATEGORY_BITMASK,
  ALL_CATS,
  ALL_CATS_MASK,
  initialState,
  EMPTY_VIEW,
  queryKey,
} from './ehBrowseStateBase'

export type Action =
  | { type: 'SET_TAB'; tab: Tab }
  | { type: 'COMMIT_QUERY'; query: string }
  | { type: 'SET_FILTER'; patch: Partial<Filters> }
  | {
      type: 'APPLY_IDENTITY'
      identity: Pick<EhBrowseState, 'tab' | 'query' | 'filters'> &
        Partial<Pick<EhBrowseState, 'ephemeralSession'>>
    }
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
  | { type: 'SET_ANCHOR'; anchor: BrowseAnchor | null }
  | { type: 'SET_LAYOUT'; layout: BrowseLayoutSnapshot | null }
  | { type: 'SHOW_EXTERNAL_RESULTS'; session: string; items: EhGallery[]; total: number }
  | { type: 'RESTORE'; snapshot: Partial<EhBrowseState> }
  | { type: 'RESET' }

function withIdentityReset(prev: EhBrowseState, next: EhBrowseState): EhBrowseState {
  return queryKey(prev) === queryKey(next) ? next : { ...next, ...EMPTY_VIEW }
}

export function reducer(state: EhBrowseState, action: Action): EhBrowseState {
  switch (action.type) {
    case 'SET_TAB':
      return withIdentityReset(state, { ...state, tab: action.tab, ephemeralSession: null })
    case 'COMMIT_QUERY':
      return withIdentityReset(state, { ...state, query: action.query, ephemeralSession: null })
    case 'SET_FILTER':
      return withIdentityReset(state, {
        ...state,
        ephemeralSession: null,
        filters: { ...state.filters, ...action.patch },
      })
    case 'APPLY_IDENTITY':
      return withIdentityReset(state, {
        ...state,
        ...action.identity,
        ephemeralSession: action.identity.ephemeralSession ?? null,
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
    case 'SET_ANCHOR':
      return { ...state, anchor: action.anchor }
    case 'SET_LAYOUT':
      return { ...state, layout: action.layout }
    case 'SHOW_EXTERNAL_RESULTS':
      return {
        ...state,
        ...EMPTY_VIEW,
        tab: 'search',
        query: '',
        ephemeralSession: action.session,
        items: action.items,
        total: action.total,
        cursor: null,
        hasMore: false,
      }
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

function computeFCats(selectedCats: readonly string[]): number | undefined {
  // Category selection is always active (independent of the advanced panel).
  // Empty === all categories === no filter.
  const sel = selectedCats
  if (sel.length === 0 || sel.length === ALL_CATS.length) return undefined
  let mask = 0
  for (const c of sel) mask |= CATEGORY_BITMASK[c] ?? 0
  return ALL_CATS_MASK ^ mask
}

export function buildParamsFromIdentity(identity: EhCanonicalIdentity, cursor: Cursor): FetchPlan {
  const nextGid = cursor?.kind === 'gid' ? cursor.nextGid : undefined
  switch (identity.surface) {
    case 'favorites':
      return {
        kind: 'favorites',
        args: {
          favcat: identity.category,
          q: identity.query || undefined,
          ...(cursor?.kind === 'fav' ? { next: cursor.next } : {}),
        },
      }
    case 'toplist':
      return {
        kind: 'toplist',
        args: {
          tl: identity.period,
          page: cursor?.kind === 'page' ? cursor.page : 0,
        },
      }
    case 'popular':
      return { kind: 'popular', args: {} }
    case 'latest':
    case 'search': {
      const advanced =
        identity.advSearch !== 0 ||
        identity.minRating !== null ||
        identity.pageFrom !== null ||
        identity.pageTo !== null ||
        !!identity.language
      return {
        kind: 'search',
        args: {
          q: identity.query || undefined,
          ...(nextGid != null ? { next_gid: nextGid } : {}),
          f_cats: computeFCats(identity.categories),
          ...(advanced
            ? {
                advance: true,
                adv_search: identity.advSearch || undefined,
                min_rating: identity.minRating ?? undefined,
                page_from: identity.pageFrom ?? undefined,
                page_to: identity.pageTo ?? undefined,
                language: identity.language || undefined,
              }
            : {}),
        },
      }
    }
    case 'image-search':
      throw new Error('Image-search sessions cannot be fetched from E-Hentai')
  }
}

export function buildParams(s: EhBrowseState): FetchPlan {
  return buildParamsFromIdentity(canonicalEhIdentity(s), s.cursor)
}
