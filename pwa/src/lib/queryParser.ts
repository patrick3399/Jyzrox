// Known filter prefixes that map to structured fields
const KNOWN_FILTER_KEYS = new Set([
  'title',
  'source',
  'rating',
  'favorited',
  'sort',
  'collection',
  'artist_id',
  'category',
  'import',
  'rl',
])

export interface ParsedFilters {
  tags: string[] // "namespace:name" tokens (with colon, not a known filter prefix)
  nameOnlyTags: string[] // bare name tokens (without colon, not a known filter prefix)
  excludeTags: string[] // tokens after - prefix (without the -)
  title: string | null // title:"value" token
  source: string | null // source:xxx token
  rating: number | null // rating:>=N token (just the number)
  favorited: boolean // favorited:true token
  readingList: boolean // rl:true token
  collection: number | null // collection:N token
  artistId: string | null // artist_id:xxx token
  category: string | null // category:xxx token
  importMode: string | null // import:xxx token
  sort: string | null // sort:xxx token
}

/**
 * Tokenize a query string, respecting quoted values like title:"re zero".
 */
function tokenize(q: string): string[] {
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
      if (ch === '"') {
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
function extractValue(token: string, prefixLen: number): string {
  const raw = token.slice(prefixLen + 1) // skip "key:"
  if (raw.startsWith('"') && raw.endsWith('"') && raw.length >= 2) {
    return raw.slice(1, -1)
  }
  return raw
}

export function parseQuery(q: string): ParsedFilters {
  const result: ParsedFilters = {
    tags: [],
    nameOnlyTags: [],
    excludeTags: [],
    title: null,
    source: null,
    rating: null,
    favorited: false,
    readingList: false,
    collection: null,
    artistId: null,
    category: null,
    importMode: null,
    sort: null,
  }

  if (!q.trim()) return result

  const tokens = tokenize(q)

  for (const token of tokens) {
    if (!token) continue

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
        result.source = value || null
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
        result.category = value || null
        break
      case 'import':
        result.importMode = value || null
        break
      case 'sort':
        result.sort = value || null
        break
      default:
        // Has colon but not a known filter prefix → namespace:name tag
        result.tags.push(token)
        break
    }
  }

  return result
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
    const needsQuote = filters.title.includes(' ')
    parts.push(`title:${needsQuote ? `"${filters.title}"` : filters.title}`)
  }
  if (filters.source) {
    parts.push(`source:${filters.source}`)
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
    parts.push(`artist_id:${filters.artistId}`)
  }
  if (filters.category) {
    parts.push(`category:${filters.category}`)
  }
  if (filters.importMode) {
    parts.push(`import:${filters.importMode}`)
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
      parsed.source = value
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
      parsed.category = value
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
