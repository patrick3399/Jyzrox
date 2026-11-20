import { formatValue, parseQuery, tokenize, type ParsedFilters } from './queryParserCore'

export { parseQuery, tagNameSearchTerm } from './queryParserCore'
export type { ParsedFilters } from './queryParserCore'

export type FacetKey = 'source' | 'category'
export type FacetMode = 'include' | 'exclude'
export interface FacetSelection {
  mode: FacetMode
  values: string[]
}

/** Current selection of a facet: exclude only when there is an exclude and no include. */
export function facetSelection(parsed: ParsedFilters, key: FacetKey): FacetSelection {
  const include = key === 'source' ? parsed.sources : parsed.categories
  const exclude = key === 'source' ? parsed.excludeSources : parsed.excludeCategories
  if (exclude.length > 0 && include.length === 0) return { mode: 'exclude', values: [...exclude] }
  return { mode: 'include', values: [...include] }
}

/** Replace a facet's selection. Empty values clear the facet (source also clears importMode). */
export function setFacet(query: string, key: FacetKey, selection: FacetSelection): string {
  const parsed = parseQuery(query)
  const values = [...new Set(selection.values.filter(Boolean))]
  const include = selection.mode === 'include' ? values : []
  const exclude = selection.mode === 'exclude' ? values : []
  if (key === 'source') {
    parsed.sources = include
    parsed.excludeSources = exclude
    // Compound `local:<mode>` values carry the import mode; a leftover one would AND.
    parsed.importMode = null
  } else {
    parsed.categories = include
    parsed.excludeCategories = exclude
  }
  return buildQuery(parsed)
}

/**
 * Reconstruct a query string from parsed filters.
 * Order: tags, nameOnlyTags, filter tokens, excludeTags last.
 */
export function buildQuery(filters: Partial<ParsedFilters>): string {
  const parts: string[] = []

  // Tags (namespace:name)
  if (filters.tags) {
    for (const tag of filters.tags) {
      parts.push(tag)
    }
  }

  // Bare name tags
  if (filters.nameOnlyTags) {
    for (const tag of filters.nameOnlyTags) {
      parts.push(tag)
    }
  }

  // Filter tokens
  if (filters.title) {
    parts.push(`title:${formatValue(filters.title)}`)
  }
  for (const value of filters.sources ?? []) {
    parts.push(`source:${formatValue(value)}`)
  }
  for (const value of filters.excludeSources ?? []) {
    parts.push(`-source:${formatValue(value)}`)
  }
  if (filters.rating !== null && filters.rating !== undefined) {
    parts.push(`rating:>=${filters.rating}`)
  }
  if (filters.favorited) {
    parts.push('favorited:true')
  }
  if (filters.readingList) {
    parts.push('rl:true')
  }
  if (filters.collection !== null && filters.collection !== undefined) {
    parts.push(`collection:${filters.collection}`)
  }
  if (filters.artistId) {
    parts.push(`artist_id:${formatValue(filters.artistId)}`)
  }
  for (const value of filters.categories ?? []) {
    parts.push(`category:${formatValue(value)}`)
  }
  for (const value of filters.excludeCategories ?? []) {
    parts.push(`-category:${formatValue(value)}`)
  }
  if (filters.importMode) {
    parts.push(`import:${formatValue(filters.importMode)}`)
  }
  if (filters.sort) {
    parts.push(`sort:${filters.sort}`)
  }

  // Exclude tags last
  if (filters.excludeTags) {
    for (const tag of filters.excludeTags) {
      parts.push(`-${tag}`)
    }
  }

  return parts.join(' ')
}

/**
 * Replace or remove a single filter key in a query string.
 * E.g., updateFilter("rem source:ehentai", "source", "pixiv") → "rem source:pixiv"
 * E.g., updateFilter("rem source:ehentai", "source", null) → "rem"
 */
export function updateFilter(query: string, key: string, value: string | null): string {
  const parsed = parseQuery(query)

  switch (key) {
    case 'title':
      parsed.title = value
      break
    case 'source':
      parsed.sources = value ? [value] : []
      parsed.excludeSources = []
      break
    case 'rating':
      parsed.rating = value !== null ? parseFloat(value) : null
      break
    case 'favorited':
      parsed.favorited = value === 'true' || value === '1'
      break
    case 'rl':
      parsed.readingList = value === 'true' || value === '1'
      break
    case 'collection':
      parsed.collection = value !== null ? parseInt(value, 10) : null
      break
    case 'artist_id':
      parsed.artistId = value
      break
    case 'category':
      parsed.categories = value ? [value] : []
      parsed.excludeCategories = []
      break
    case 'import':
      parsed.importMode = value
      break
    case 'sort':
      parsed.sort = value
      break
    default:
      break
  }

  return buildQuery(parsed)
}

const FILTER_KEYS = new Set([
  'title',
  'source',
  'rating',
  'favorited',
  'rl',
  'collection',
  'artist_id',
  'category',
  'import',
  'sort',
])

/** True for a `key:value` token whose key is one of the structured filters. */
export function isFilterToken(token: string): boolean {
  if (token.startsWith('-')) {
    const facetColon = token.indexOf(':')
    if (facetColon <= 1) return false
    const facetKey = token.slice(1, facetColon).toLowerCase()
    return facetKey === 'source' || facetKey === 'category'
  }
  const colon = token.indexOf(':')
  return colon > 0 && FILTER_KEYS.has(token.slice(0, colon).toLowerCase())
}

/** The free-text part of a query: every non-filter token, in original order. */
export function queryText(q: string): string {
  return tokenize(q)
    .filter((token) => !isFilterToken(token))
    .join(' ')
}

/**
 * Replace the free-text part of `q` with `text`, keeping `q`'s filters. A filter
 * typed inside `text` wins over the same filter already in `q`.
 */
export function withText(q: string, text: string): string {
  const base = parseQuery(q)
  const typed = parseQuery(text)
  const typedSource = typed.sources.length > 0 || typed.excludeSources.length > 0
  const typedCategory = typed.categories.length > 0 || typed.excludeCategories.length > 0
  return buildQuery({
    tags: typed.tags,
    nameOnlyTags: typed.nameOnlyTags,
    excludeTags: typed.excludeTags,
    title: typed.title ?? base.title,
    sources: typedSource ? typed.sources : base.sources,
    excludeSources: typedSource ? typed.excludeSources : base.excludeSources,
    rating: typed.rating ?? base.rating,
    favorited: typed.favorited || base.favorited,
    readingList: typed.readingList || base.readingList,
    collection: typed.collection ?? base.collection,
    artistId: typed.artistId ?? base.artistId,
    categories: typedCategory ? typed.categories : base.categories,
    excludeCategories: typedCategory ? typed.excludeCategories : base.excludeCategories,
    importMode: typedSource ? typed.importMode : (typed.importMode ?? base.importMode),
    sort: typed.sort ?? base.sort,
  })
}

/** Drop every filter token, keeping only the free-text part (normalised). */
export function withoutFilters(q: string): string {
  return withText('', queryText(q))
}
