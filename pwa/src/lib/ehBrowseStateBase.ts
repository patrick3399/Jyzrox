import type { EhGallery } from '@/lib/types'
import type { BrowseAnchor } from '@/lib/browse/anchor'
import type { BrowseLayoutSnapshot } from '@/lib/browse/snapshotStore'
import { ehIdentityKey } from '@/lib/browse/ehentai'

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
  language: string
  favCat: string // 'all' | '0'..'9'
  favSearch: string
  toplistTl: number
}

export type Status = 'idle' | 'seeding' | 'loading' | 'error' | 'expired'

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
  anchor: BrowseAnchor | null
  layout: BrowseLayoutSnapshot | null
  /** Unique, non-replayable identity for reverse-image results. */
  ephemeralSession: string | null
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

/**
 * Toggle one category in the browse filter, using positive-selection semantics:
 * an empty list means "all", and the first explicit pick from that state narrows
 * to just that category rather than deselecting it out of a full set. Selecting
 * every category collapses back to the empty "all" representation.
 */
export function toggleSelectedCategory(current: string[], val: string): string[] {
  const next = current.includes(val) ? current.filter((c) => c !== val) : [...current, val]
  return next.length === ALL_CATS.length ? [] : next
}
export const EH_PAGE_SIZE = 25

export const EH_ADVANCED_SEARCH_BITS = {
  name: 0x1,
  tags: 0x2,
  description: 0x4,
  torrentFilenames: 0x8,
  onlyTorrents: 0x10,
  lowPowerTags: 0x20,
  downvotedTags: 0x40,
  showExpunged: 0x80,
  disableLanguageFilter: 0x100,
  disableUploaderFilter: 0x200,
  disableTagFilter: 0x400,
} as const

export const initialFilters: Filters = {
  selectedCats: [],
  advancedOpen: false,
  advSearch: 0,
  minRating: null,
  pageFrom: null,
  pageTo: null,
  language: '',
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
  anchor: null,
  layout: null,
  ephemeralSession: null,
}

export const EMPTY_VIEW = {
  items: [] as EhGallery[],
  total: null,
  cursor: null as Cursor,
  hasMore: true,
  status: 'idle' as Status,
  error: null,
  scrollY: 0,
  anchor: null as BrowseAnchor | null,
  layout: null as BrowseLayoutSnapshot | null,
}

/** Stable identity string: tab + query + filters. Same identity === same results. */
export function queryKey(s: EhBrowseState): string {
  return ehIdentityKey(s)
}
