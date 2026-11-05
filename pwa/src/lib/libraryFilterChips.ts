import { t } from '@/lib/i18n'
import { facetSelection, type FacetKey, type ParsedFilters } from '@/lib/queryParser'

export type LibraryFilterChipKey =
  | 'title'
  | 'source'
  | 'rating'
  | 'category'
  | 'collection'
  | 'sort'
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

function facetChipLabel(
  title: string,
  parsed: ParsedFilters,
  key: FacetKey,
  display: (value: string) => string,
): string | null {
  const { mode, values } = facetSelection(parsed, key)
  if (values.length === 0) return null
  const shown = values.map(display)
  return mode === 'exclude'
    ? `${title}: ${t('library.facetNotPrefix')} ${shown.join(', ')}`
    : `${title}: ${shown.join(` ${t('library.facetOr')} `)}`
}

/**
 * Active filters as removable chips, in a fixed order. Count = result length.
 * Favorites and reading list have toggle buttons that show their state instead.
 */
export function libraryFilterChips(
  parsed: ParsedFilters,
  ctx: LibraryFilterChipContext,
): LibraryFilterChip[] {
  const chips: LibraryFilterChip[] = []

  if (parsed.title) {
    chips.push({ key: 'title', label: `${t('library.titleFilter')}: ${parsed.title}` })
  }
  // A leftover `import:` next to a single plain source still means that combination.
  const sourceParsed =
    parsed.importMode && parsed.sources.length === 1 && !parsed.sources[0].includes(':')
      ? { ...parsed, sources: [`${parsed.sources[0]}:${parsed.importMode}`] }
      : parsed
  const sourceLabel = facetChipLabel(t('library.source'), sourceParsed, 'source', ctx.sourceLabel)
  if (sourceLabel) chips.push({ key: 'source', label: sourceLabel })
  if (parsed.rating !== null) {
    chips.push({ key: 'rating', label: `★≥${parsed.rating}` })
  }
  const categoryLabel = facetChipLabel(
    t('library.filterCategory'),
    parsed,
    'category',
    (value) => (value === '__uncategorized__' ? t('library.categoryUncategorized') : value),
  )
  if (categoryLabel) chips.push({ key: 'category', label: categoryLabel })
  if (parsed.collection !== null) {
    const value = ctx.collectionName(parsed.collection) ?? `#${parsed.collection}`
    chips.push({ key: 'collection', label: `${t('collections.filterByCollection')}: ${value}` })
  }
  if (parsed.sort && parsed.sort !== 'added_at') {
    chips.push({ key: 'sort', label: `${t('library.sort')}: ${ctx.sortLabel(parsed.sort)}` })
  }
  if (parsed.artistId) {
    chips.push({ key: 'artist_id', label: `${t('library.artistFilter')}: ${parsed.artistId}` })
  }

  return chips
}
