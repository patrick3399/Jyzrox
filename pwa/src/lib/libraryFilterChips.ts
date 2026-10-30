import { t } from '@/lib/i18n'
import type { ParsedFilters } from '@/lib/queryParser'

export type LibraryFilterChipKey =
  | 'title'
  | 'source'
  | 'rating'
  | 'category'
  | 'collection'
  | 'sort'
  | 'favorited'
  | 'rl'
  | 'artist_id'

export interface LibraryFilterChip {
  key: LibraryFilterChipKey
  label: string
}

export interface LibraryFilterChipContext {
  /** Display label for a combined source value, e.g. "local:link". */
  sourceLabel: (combined: string) => string
  collectionName: (id: number) => string | undefined
  sortLabel: (value: string) => string
}

/** Active filters as removable chips, in a fixed order. Count = result length. */
export function libraryFilterChips(
  parsed: ParsedFilters,
  ctx: LibraryFilterChipContext,
): LibraryFilterChip[] {
  const chips: LibraryFilterChip[] = []

  if (parsed.title) {
    chips.push({ key: 'title', label: `${t('library.titleFilter')}: ${parsed.title}` })
  }
  if (parsed.source) {
    const combined = parsed.importMode ? `${parsed.source}:${parsed.importMode}` : parsed.source
    chips.push({ key: 'source', label: `${t('library.source')}: ${ctx.sourceLabel(combined)}` })
  }
  if (parsed.rating !== null) {
    chips.push({ key: 'rating', label: `★≥${parsed.rating}` })
  }
  if (parsed.category) {
    const value =
      parsed.category === '__uncategorized__' ? t('library.categoryUncategorized') : parsed.category
    chips.push({ key: 'category', label: `${t('library.filterCategory')}: ${value}` })
  }
  if (parsed.collection !== null) {
    const value = ctx.collectionName(parsed.collection) ?? `#${parsed.collection}`
    chips.push({ key: 'collection', label: `${t('collections.filterByCollection')}: ${value}` })
  }
  if (parsed.sort && parsed.sort !== 'added_at') {
    chips.push({ key: 'sort', label: `${t('library.sort')}: ${ctx.sortLabel(parsed.sort)}` })
  }
  if (parsed.favorited) {
    chips.push({ key: 'favorited', label: t('library.favoritesOnly') })
  }
  if (parsed.readingList) {
    chips.push({ key: 'rl', label: t('library.readingListOnly') })
  }
  if (parsed.artistId) {
    chips.push({ key: 'artist_id', label: `${t('library.artistFilter')}: ${parsed.artistId}` })
  }

  return chips
}
