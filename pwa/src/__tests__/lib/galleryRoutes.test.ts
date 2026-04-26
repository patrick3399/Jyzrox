/**
 * galleryRoutes — Vitest test suite
 *
 * Covers:
 *   decodeRouteSegment — null input returns null
 *   decodeRouteSegment — undefined input returns null
 *   decodeRouteSegment — empty string returns null (falsy)
 *   decodeRouteSegment — percent-encoded ASCII returns decoded string
 *   decodeRouteSegment — percent-encoded multibyte returns decoded string
 *   decodeRouteSegment — malformed URI returns original value (catch branch)
 *   galleryHref        — simple source and sourceId produces correct path
 *   galleryHref        — special characters in args are encoded
 *   readerHref         — no page argument produces path without suffix
 *   readerHref         — page > 0 appends ?page= suffix
 *   readerHref         — page = 0 is falsy, no suffix appended
 */

import { describe, it, expect } from 'vitest'
import {
  decodeRouteSegment,
  galleryHref,
  readerHref,
} from '@/lib/galleryRoutes'

// ── decodeRouteSegment ────────────────────────────────────────────────

describe('decodeRouteSegment', () => {
  it('test_decodeRouteSegment_null_returnsNull', () => {
    expect(decodeRouteSegment(null)).toBeNull()
  })

  it('test_decodeRouteSegment_undefined_returnsNull', () => {
    expect(decodeRouteSegment(undefined)).toBeNull()
  })

  it('test_decodeRouteSegment_emptyString_returnsNull', () => {
    expect(decodeRouteSegment('')).toBeNull()
  })

  it('test_decodeRouteSegment_encodedAscii_returnsDecodedString', () => {
    expect(decodeRouteSegment('hello%20world')).toBe('hello world')
  })

  it('test_decodeRouteSegment_encodedMultibyte_returnsDecodedString', () => {
    expect(decodeRouteSegment('%E4%B8%AD%E6%96%87')).toBe('中文')
  })

  it('test_decodeRouteSegment_malformedUri_returnsOriginalValue', () => {
    expect(decodeRouteSegment('invalid%2')).toBe('invalid%2')
  })
})

// ── galleryHref ───────────────────────────────────────────────────────

describe('galleryHref', () => {
  it('test_galleryHref_simpleArgs_producesCorrectPath', () => {
    expect(galleryHref('pixiv', '123')).toBe('/library/pixiv/123')
  })

  it('test_galleryHref_specialChars_encodesSourceAndSourceId', () => {
    const result = galleryHref('e-hentai', 'g/1234/abcdef')
    expect(result).toBe('/library/e-hentai/g%2F1234%2Fabcdef')
  })
})

// ── readerHref ────────────────────────────────────────────────────────

describe('readerHref', () => {
  it('test_readerHref_noPage_producesPathWithoutSuffix', () => {
    expect(readerHref('pixiv', '123')).toBe('/reader/pixiv/123')
  })

  it('test_readerHref_pageGreaterThanZero_appendsPageSuffix', () => {
    expect(readerHref('pixiv', '123', 5)).toBe('/reader/pixiv/123?page=5')
  })

  it('test_readerHref_pageZero_isFalsyNoSuffix', () => {
    expect(readerHref('pixiv', '123', 0)).toBe('/reader/pixiv/123')
  })
})
