import { describe, it, expect } from 'vitest'
import {
  buildQuery,
  isFilterToken,
  parseQuery,
  queryText,
  tagNameSearchTerm,
  withText,
  withoutFilters,
} from '@/lib/queryParser'

describe('tagNameSearchTerm', () => {
  it('test_tagNameSearchTerm_multiWordName_isQuotedSoItStaysOneToken', () => {
    expect(tagNameSearchTerm('jun ye tako')).toBe('"jun ye tako"')
  })

  it('test_tagNameSearchTerm_singleWordName_isUnchanged', () => {
    expect(tagNameSearchTerm('pantyhose')).toBe('pantyhose')
  })

  it('test_tagNameSearchTerm_multiWordName_parsesAsSingleBareTerm', () => {
    const parsed = parseQuery(tagNameSearchTerm('jun ye tako'))
    expect(parsed.nameOnlyTags).toEqual(['"jun ye tako"'])
    expect(buildQuery(parsed)).toBe('"jun ye tako"')
  })
})

describe('isFilterToken', () => {
  it.each(['title:x', 'source:pixiv', 'rating:>=4', 'favorited:true', 'rl:true', 'collection:3',
    'artist_id:a:b', 'category:manga', 'import:link', 'sort:rating', 'SOURCE:pixiv'])(
    'test_isFilterToken_knownPrefix_%s_isFilter',
    (token) => expect(isFilterToken(token)).toBe(true),
  )

  it('test_isFilterToken_negatedFilterPrefix_isNotFilter', () => {
    expect(isFilterToken('-source:pixiv')).toBe(false)
  })

  it('test_isFilterToken_plainTagNamespaceOrBareName_isNotFilter', () => {
    expect(isFilterToken('character:rem')).toBe(false)
    expect(isFilterToken('rem')).toBe(false)
    expect(isFilterToken(':source')).toBe(false)
  })
})

describe('queryText', () => {
  it('test_queryText_mixedTokens_dropsFilterTokensKeepsExcludes', () => {
    expect(queryText('rem source:pixiv -general:sketch rating:>=4')).toBe('rem -general:sketch')
  })

  it('test_queryText_tagBeforeBareName_keepsOriginalOrder', () => {
    expect(queryText('character:rem rem')).toBe('character:rem rem')
  })

  it('test_queryText_quotedFilterValueWithSpace_isDroppedAsOneToken', () => {
    expect(queryText('rem title:"re zero"')).toBe('rem')
  })

  it('test_queryText_onlyFilters_returnsEmptyString', () => {
    expect(queryText('source:pixiv sort:rating')).toBe('')
  })
})

describe('withText', () => {
  it('test_withText_replacingText_keepsBothActiveFilters', () => {
    const next = parseQuery(withText('rem source:pixiv sort:rating', 'ram'))
    expect(next.nameOnlyTags).toEqual(['ram'])
    expect(next.source).toBe('pixiv')
    expect(next.sort).toBe('rating')
  })

  it('test_withText_typedSourceAndBaseSource_typedWins', () => {
    const next = parseQuery(withText('source:pixiv', 'rem source:ehentai'))
    expect(next.source).toBe('ehentai')
    expect(next.nameOnlyTags).toEqual(['rem'])
  })

  it('test_withText_emptyText_keepsOnlyFilters', () => {
    expect(withText('rem source:pixiv', '')).toBe('source:pixiv')
  })

  it('test_withText_typedBooleanUnset_baseBooleanKept', () => {
    expect(parseQuery(withText('favorited:true rl:true', 'rem')).favorited).toBe(true)
    expect(parseQuery(withText('favorited:true rl:true', 'rem')).readingList).toBe(true)
  })

  it('test_withText_typedFilterTokenWithBaseOfDifferentField_mergesBoth', () => {
    const next = parseQuery(withText('source:pixiv', 'rating:>=4'))
    expect(next.source).toBe('pixiv')
    expect(next.rating).toBe(4)
  })
})

describe('withoutFilters', () => {
  it('test_withoutFilters_textAndFilters_keepsText', () => {
    expect(withoutFilters('rem source:pixiv favorited:true')).toBe('rem')
  })

  it('test_withoutFilters_onlyFilters_returnsEmptyString', () => {
    expect(withoutFilters('source:pixiv sort:rating')).toBe('')
  })
})
