import { canonicalIdentityKey } from './identity'
import type { BrowseListPatch } from './patch'
import type { EhGallery } from '@/lib/types'

export type EhIdentityFilters = {
  selectedCats: string[]
  advancedOpen: boolean
  advSearch: number
  minRating: number | null
  pageFrom: number | null
  pageTo: number | null
  language: string
  favCat: string
  favSearch: string
  toplistTl: number
}

export type EhIdentityInput = {
  tab: 'search' | 'favorites' | 'popular' | 'toplist'
  query: string
  filters: EhIdentityFilters
  ephemeralSession?: string | null
}

export type EhCanonicalIdentity =
  | { surface: 'popular' }
  | {
      surface: 'latest' | 'search'
      query: string
      categories: string[]
      advSearch: number
      minRating: number | null
      pageFrom: number | null
      pageTo: number | null
      language: string
    }
  | { surface: 'favorites'; category: string; query: string }
  | { surface: 'toplist'; period: number }
  | { surface: 'image-search'; session: string }

const TOPLIST_PERIODS = new Set([11, 12, 13, 15])
const EH_ADVANCED_SEARCH_MASK = 0x7ff

export function normalizeEhToplistPeriod(value: unknown): number {
  return typeof value === 'number' && Number.isInteger(value) && TOPLIST_PERIODS.has(value)
    ? value
    : 11
}

export function normalizeEhFavoriteCategory(value: unknown): string {
  return value === 'all' || (typeof value === 'string' && /^[0-9]$/.test(value)) ? value : 'all'
}

export function normalizeEhRating(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 2 && value <= 5
    ? value
    : null
}

export function normalizeEhPageBound(value: unknown): number | null {
  return typeof value === 'number' && Number.isInteger(value) && value > 0 ? value : null
}

export function normalizeEhAdvancedSearch(value: unknown): number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0 && value <= EH_ADVANCED_SEARCH_MASK
    ? value
    : 0
}

export function normalizeEhCategories(values: readonly string[]): string[] {
  return [...new Set(values)].sort()
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

export function isEhGallery(value: unknown): value is EhGallery {
  if (!isRecord(value)) return false
  return (
    typeof value.gid === 'number' &&
    Number.isInteger(value.gid) &&
    value.gid > 0 &&
    typeof value.token === 'string' &&
    value.token.length > 0
  )
}

export function isEhFavCategoryMeta(value: unknown): boolean {
  if (value === undefined || value === null) return true
  return (
    Array.isArray(value) &&
    value.every(
      (category) =>
        isRecord(category) &&
        typeof category.index === 'number' &&
        Number.isInteger(category.index) &&
        category.index >= 0 &&
        category.index <= 9 &&
        typeof category.name === 'string' &&
        typeof category.count === 'number' &&
        Number.isFinite(category.count) &&
        category.count >= 0,
    )
  )
}

/**
 * Project the legacy EH view state onto a canonical, surface-specific identity.
 * Fields belonging to another surface and panel expansion state are deliberately
 * excluded: they cannot change the fetched result set for the active surface.
 */
export function canonicalEhIdentity(input: EhIdentityInput): EhCanonicalIdentity {
  if (input.ephemeralSession) {
    return { surface: 'image-search', session: input.ephemeralSession }
  }
  if (input.tab === 'popular') return { surface: 'popular' }
  if (input.tab === 'favorites') {
    return {
      surface: 'favorites',
      category: normalizeEhFavoriteCategory(input.filters.favCat),
      query: input.filters.favSearch,
    }
  }
  if (input.tab === 'toplist') {
    return { surface: 'toplist', period: normalizeEhToplistPeriod(input.filters.toplistTl) }
  }
  return {
    surface: input.query ? 'search' : 'latest',
    query: input.query,
    categories: normalizeEhCategories(input.filters.selectedCats),
    advSearch: normalizeEhAdvancedSearch(input.filters.advSearch),
    minRating: normalizeEhRating(input.filters.minRating),
    pageFrom: normalizeEhPageBound(input.filters.pageFrom),
    pageTo: normalizeEhPageBound(input.filters.pageTo),
    language: input.filters.language,
  }
}

export function ehIdentityKey(input: EhIdentityInput): string {
  return canonicalIdentityKey(canonicalEhIdentity(input))
}

export const ehentaiBrowseAdapter = {
  sourceId: 'ehentai',
  schemaVersion: 1,
  identity: canonicalEhIdentity,
  identityKey: ehIdentityKey,
  getItemKey: (item: { gid: number }) => item.gid,
  historyMode: {
    searchInput: 'replace',
    filter: 'replace',
    tab: 'replace',
    savedSearch: 'replace',
  },
} as const

/** The category of a Favorites list identity key, or null for other surfaces. */
function favoritesCategoryOf(identityKey: string): string | null {
  let identity: unknown
  try {
    identity = JSON.parse(identityKey)
  } catch {
    return null
  }
  return isRecord(identity) &&
    identity.surface === 'favorites' &&
    typeof identity.category === 'string'
    ? identity.category
    : null
}

/**
 * A favourite change on `gid` (`category` null when it was removed), for the
 * saved and mounted E-Hentai lists. List cards do not show favourite state, so
 * a gallery that left a Favorites list is dropped from it (and from its total)
 * instead of reading as still favourited. One that joined a Favorites list
 * cannot be placed in it, so a saved list lacking it is discarded and loads
 * fresh on its next visit. Other surfaces are untouched.
 */
export function ehFavoritePatch(gid: number, category: number | null): BrowseListPatch<EhGallery> {
  const target = category === null ? null : String(category)
  const keeps = (listCategory: string) =>
    target !== null && (listCategory === 'all' || listCategory === target)
  return {
    updateItem: (item, identityKey) => {
      if (item.gid !== gid) return item
      const listCategory = favoritesCategoryOf(identityKey)
      if (listCategory === null || keeps(listCategory)) return item
      return null
    },
    invalidates: (identityKey, items) => {
      const listCategory = favoritesCategoryOf(identityKey)
      return (
        listCategory !== null && keeps(listCategory) && !items.some((item) => item.gid === gid)
      )
    },
  }
}
