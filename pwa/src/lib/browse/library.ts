import type { SearchGalleryItem } from '@/lib/api'
import { canonicalIdentityKey } from './identity'
import { buildQuery, parseQuery, type ParsedFilters } from '../queryParser'

export const LIBRARY_BROWSE_SOURCE_ID = 'library'
export const LIBRARY_BROWSE_SCHEMA_VERSION = 1
export const LEGACY_LIBRARY_SCROLL_KEY = 'library_scrollY'

export type LibraryBrowseIdentity = ParsedFilters & {
  surface: typeof LIBRARY_BROWSE_SOURCE_ID
  sort: string
}

function uniqueSorted(values: string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))].sort()
}

export function canonicalLibraryBrowseIdentity(rawQuery: string): LibraryBrowseIdentity {
  const parsed = parseQuery(rawQuery.trim())
  return {
    surface: LIBRARY_BROWSE_SOURCE_ID,
    tags: uniqueSorted(parsed.tags),
    nameOnlyTags: uniqueSorted(parsed.nameOnlyTags),
    excludeTags: uniqueSorted(parsed.excludeTags),
    title: parsed.title,
    source: parsed.source,
    rating: parsed.rating,
    favorited: parsed.favorited,
    readingList: parsed.readingList,
    collection: parsed.collection,
    artistId: parsed.artistId,
    category: parsed.category,
    importMode: parsed.importMode,
    sort: parsed.sort ?? 'added_at',
  }
}

export function libraryBrowseIdentityKey(rawQuery: string): string {
  return canonicalIdentityKey(canonicalLibraryBrowseIdentity(rawQuery))
}

export function libraryBrowseSearchQuery(identity: LibraryBrowseIdentity): string {
  return buildQuery({
    tags: identity.tags,
    nameOnlyTags: identity.nameOnlyTags,
    excludeTags: identity.excludeTags,
    title: identity.title,
    source: identity.source,
    rating: identity.rating,
    favorited: identity.favorited,
    readingList: identity.readingList,
    collection: identity.collection,
    artistId: identity.artistId,
    category: identity.category,
    importMode: identity.importMode,
    sort: null,
  })
}

/** Remove the unscoped Library snapshot. The return value makes the migration idempotent. */
export function invalidateLegacyLibraryScroll(storage: Storage): boolean {
  try {
    if (storage.getItem(LEGACY_LIBRARY_SCROLL_KEY) === null) return false
    storage.removeItem(LEGACY_LIBRARY_SCROLL_KEY)
    return true
  } catch {
    return false
  }
}

export function isLibraryBrowseCursor(value: unknown): value is string {
  return typeof value === 'string' && value.length > 0
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === 'string'
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string')
}

export function isSearchGalleryItem(value: unknown): value is SearchGalleryItem {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false
  const item = value as Record<string, unknown>
  return (
    typeof item.id === 'number' &&
    Number.isInteger(item.id) &&
    item.id > 0 &&
    typeof item.title === 'string' &&
    isNullableString(item.title_jpn) &&
    typeof item.source === 'string' &&
    item.source.length > 0 &&
    typeof item.source_id === 'string' &&
    item.source_id.length > 0 &&
    isNullableString(item.category) &&
    isNullableString(item.language) &&
    typeof item.pages === 'number' &&
    Number.isFinite(item.pages) &&
    typeof item.rating === 'number' &&
    Number.isFinite(item.rating) &&
    typeof item.favorited === 'boolean' &&
    typeof item.is_favorited === 'boolean' &&
    (item.my_rating === null ||
      (typeof item.my_rating === 'number' && Number.isFinite(item.my_rating))) &&
    typeof item.in_reading_list === 'boolean' &&
    isNullableString(item.artist_id) &&
    isNullableString(item.import_mode) &&
    isNullableString(item.source_url) &&
    isStringArray(item.tags_array) &&
    isNullableString(item.uploader) &&
    typeof item.download_status === 'string' &&
    isNullableString(item.added_at) &&
    isNullableString(item.posted_at) &&
    isStringArray(item.tags) &&
    (item.cover_thumb === undefined || isNullableString(item.cover_thumb))
  )
}
