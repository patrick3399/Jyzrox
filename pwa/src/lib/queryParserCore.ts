export interface ParsedFilters {
  tags: string[] // "namespace:name" tokens (with colon, not a known filter prefix)
  nameOnlyTags: string[] // bare name tokens (without colon, not a known filter prefix)
  excludeTags: string[] // tokens after - prefix (without the -)
  title: string | null // title:"value" token
  sources: string[] // source:xxx tokens (OR); local import modes use "local:link"
  excludeSources: string[] // -source:xxx tokens
  rating: number | null // rating:>=N token (just the number)
  favorited: boolean // favorited:true token
  readingList: boolean // rl:true token
  collection: number | null // collection:N token
  artistId: string | null // artist_id:xxx token
  categories: string[] // category:xxx tokens (OR)
  excludeCategories: string[] // -category:xxx tokens
  importMode: string | null // import:xxx token
  sort: string | null // sort:xxx token
  dir: 'asc' | 'desc' | null // dir:asc|desc token (null = the sort's default direction)
}

/** Direction a sort uses when no `dir:` is given (mirrors the backend). */
export function defaultSortDirection(sort: string | null | undefined): 'asc' | 'desc' {
  return sort === 'title' ? 'asc' : 'desc'
}

/**
 * Tokenize a query string, respecting quoted values like title:"re zero".
 */
export function tokenize(q: string): string[] {
  const tokens: string[] = []
  let i = 0
  const s = q.trim()

  while (i < s.length) {
    // Skip leading whitespace
    while (i < s.length && s[i] === ' ') i++
    if (i >= s.length) break

    let token = ''

    // Collect characters until whitespace, handling quoted values
    let inQuote = false
    while (i < s.length) {
      const ch = s[i]
      if (inQuote && ch === '\\' && (s[i + 1] === '"' || s[i + 1] === '\\')) {
        // Escaped quote or backslash inside a quoted value: keep the pair, do
        // not let the quote end the value (see formatValue).
        token += ch + s[i + 1]
        i += 2
      } else if (ch === '"') {
        inQuote = !inQuote
        token += ch
        i++
      } else if (ch === ' ' && !inQuote) {
        break
      } else {
        token += ch
        i++
      }
    }

    if (token) tokens.push(token)
  }

  return tokens
}

/**
 * Extract the value of a key:value token, handling quoted values.
 * E.g., 'title:"re zero"' → 're zero'
 *       'source:ehentai' → 'ehentai'
 */
export function extractValue(token: string, prefixLen: number): string {
  const raw = token.slice(prefixLen + 1) // skip "key:"
  if (raw.startsWith('"') && raw.endsWith('"') && raw.length >= 2) {
    return raw.slice(1, -1).replace(/\\(["\\])/g, '$1')
  }
  return raw
}

/**
 * Inverse of extractValue. A value with whitespace or a quote is wrapped in
 * quotes, with `"` and `\` escaped so the tokenizer reads it back unchanged.
 * Anything else is emitted as typed (a bare backslash is literal).
 */
export function formatValue(value: string): string {
  if (!/[\s"]/.test(value)) return value
  return `"${value.replace(/["\\]/g, '\\$&')}"`
}

/**
 * Bare-name search term for a tag. Names with whitespace are quoted so the
 * query tokenizer keeps them as one term: jun ye tako → "jun ye tako".
 */
export function tagNameSearchTerm(name: string): string {
  return formatValue(name)
}

export function parseQuery(q: string): ParsedFilters {
  const result: ParsedFilters = {
    tags: [],
    nameOnlyTags: [],
    excludeTags: [],
    title: null,
    sources: [],
    excludeSources: [],
    rating: null,
    favorited: false,
    readingList: false,
    collection: null,
    artistId: null,
    categories: [],
    excludeCategories: [],
    importMode: null,
    sort: null,
    dir: null,
  }

  if (!q.trim()) return result

  const tokens = tokenize(q)

  for (const token of tokens) {
    if (!token) continue

    // -source: / -category: are facet excludes, not excluded tags.
    if (token.startsWith('-')) {
      const facetColon = token.indexOf(':')
      const facetKey = facetColon > 1 ? token.slice(1, facetColon).toLowerCase() : ''
      if (facetKey === 'source' || facetKey === 'category') {
        const facetValue = extractValue(token, facetColon)
        if (facetValue) {
          const list = facetKey === 'source' ? result.excludeSources : result.excludeCategories
          if (!list.includes(facetValue)) list.push(facetValue)
        }
        continue
      }
    }

    // Negation prefix: -tag:value or -tagname
    if (token.startsWith('-') && token.length > 1) {
      result.excludeTags.push(token.slice(1))
      continue
    }

    const colonIdx = token.indexOf(':')

    if (colonIdx === -1) {
      // Bare word — nameOnlyTag
      result.nameOnlyTags.push(token)
      continue
    }

    const key = token.slice(0, colonIdx).toLowerCase()
    const value = extractValue(token, colonIdx - 1 + 1) // value after colon

    switch (key) {
      case 'title':
        result.title = extractValue(token, key.length)
        break
      case 'source':
        if (value && !result.sources.includes(value)) result.sources.push(value)
        break
      case 'rating': {
        // Accept: rating:>=4, rating:>4, rating:4
        const numStr = value.replace(/^[><=]+/, '')
        const num = parseFloat(numStr)
        result.rating = isNaN(num) ? null : num
        break
      }
      case 'favorited':
        result.favorited = value === 'true' || value === '1'
        break
      case 'rl':
        result.readingList = value === 'true' || value === '1'
        break
      case 'collection': {
        const num = parseInt(value, 10)
        result.collection = isNaN(num) ? null : num
        break
      }
      case 'artist_id':
        result.artistId = value || null
        break
      case 'category':
        if (value && !result.categories.includes(value)) result.categories.push(value)
        break
      case 'import':
        result.importMode = value || null
        break
      case 'sort':
        result.sort = value || null
        break
      case 'dir': {
        const dir = value.toLowerCase()
        result.dir = dir === 'asc' || dir === 'desc' ? dir : null
        break
      }
      default:
        // Has colon but not a known filter prefix → namespace:name tag
        result.tags.push(token)
        break
    }
  }

  // Legacy `source:local import:link` is the same filter as `source:local:link`.
  if (
    result.sources.length === 1 &&
    result.sources[0] === 'local' &&
    result.importMode &&
    result.excludeSources.length === 0
  ) {
    result.sources = [`local:${result.importMode}`]
    result.importMode = null
  }

  return result
}
