import { describe, it, expect } from 'vitest'
import {
  buildQuery,
  facetSelection,
  isFilterToken,
  parseQuery,
  queryText,
  setFacet,
  tagNameSearchTerm,
  updateFilter,
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

  it('test_isFilterToken_negatedFacetPrefix_isFilter', () => {
    expect(isFilterToken('-source:pixiv')).toBe(true)
    expect(isFilterToken('-category:manga')).toBe(true)
  })

  it('test_isFilterToken_negatedNonFacetKey_isNotFilter', () => {
    expect(isFilterToken('-rating:4')).toBe(false)
    expect(isFilterToken('-general:sketch')).toBe(false)
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
    expect(next.sources).toEqual(['pixiv'])
    expect(next.sort).toBe('rating')
  })

  it('test_withText_typedSourceAndBaseSource_typedWins', () => {
    const next = parseQuery(withText('source:pixiv', 'rem source:ehentai'))
    expect(next.sources).toEqual(['ehentai'])
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
    expect(next.sources).toEqual(['pixiv'])
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

describe('multi-select facets', () => {
  it('parseQuery_repeated_source_tokens_collects_all', () => {
    const parsed = parseQuery('source:pixiv source:ehentai source:pixiv')
    expect(parsed.sources).toEqual(['pixiv', 'ehentai'])
    expect(parsed.excludeSources).toEqual([])
  })

  it('parseQuery_excluded_category_goes_to_excludeCategories_not_excludeTags', () => {
    const parsed = parseQuery('-category:"Model Photobook" -source:local:link -general:sketch')
    expect(parsed.excludeCategories).toEqual(['Model Photobook'])
    expect(parsed.excludeSources).toEqual(['local:link'])
    expect(parsed.excludeTags).toEqual(['general:sketch'])
  })

  it('buildQuery_roundtrips_quoted_multi_category', () => {
    const q = 'category:Cosplay category:"Model Photobook" -category:Misc'
    const parsed = parseQuery(q)
    expect(parsed.categories).toEqual(['Cosplay', 'Model Photobook'])
    expect(buildQuery(parsed)).toBe(q)
  })

  it('parseQuery_legacy_source_local_import_link_normalizes_to_compound', () => {
    const parsed = parseQuery('source:local import:link')
    expect(parsed.sources).toEqual(['local:link'])
    expect(parsed.importMode).toBeNull()
    expect(buildQuery(parsed)).toBe('source:local:link')
  })

  it('parseQuery_legacy_import_with_excluded_source_is_not_normalized', () => {
    const parsed = parseQuery('source:local import:link -source:pixiv')
    expect(parsed.sources).toEqual(['local'])
    expect(parsed.importMode).toBe('link')
  })

  it('queryText_hides_excluded_facet_tokens', () => {
    expect(queryText('rem -source:local:link -category:Misc -general:sketch')).toBe(
      'rem -general:sketch',
    )
    expect(withoutFilters('rem -source:pixiv -category:Misc')).toBe('rem')
  })

  it('facetSelection_exclude_only_when_exclude_without_include', () => {
    expect(facetSelection(parseQuery('-category:A -category:B'), 'category')).toEqual({
      mode: 'exclude',
      values: ['A', 'B'],
    })
    expect(facetSelection(parseQuery('category:A -category:B'), 'category')).toEqual({
      mode: 'include',
      values: ['A'],
    })
    expect(facetSelection(parseQuery('rem'), 'source')).toEqual({ mode: 'include', values: [] })
  })

  it('setFacet_replaces_facet_and_keeps_text_and_other_filters', () => {
    const next = setFacet('rem rating:>=3 category:Old', 'category', {
      mode: 'exclude',
      values: ['A B', 'C'],
    })
    expect(parseQuery(next)).toMatchObject({
      nameOnlyTags: ['rem'],
      rating: 3,
      categories: [],
      excludeCategories: ['A B', 'C'],
    })
  })

  it('setFacet_empty_values_clears_source_include_exclude_and_import_mode', () => {
    expect(setFacet('rem source:pixiv -source:local:link import:x', 'source', { mode: 'include', values: [] })).toBe('rem')
  })

  it('updateFilter_source_sets_single_include_and_null_clears_both_modes', () => {
    expect(updateFilter('source:a -source:b rem', 'source', 'pixiv')).toBe('rem source:pixiv')
    expect(updateFilter('category:a category:b', 'category', null)).toBe('')
    expect(updateFilter('-category:a', 'category', null)).toBe('')
  })

  it('withText_typed_facet_replaces_base_facet_only', () => {
    const next = parseQuery(withText('source:pixiv category:A', 'rem -category:B'))
    expect(next.sources).toEqual(['pixiv'])
    expect(next.categories).toEqual([])
    expect(next.excludeCategories).toEqual(['B'])
  })
})
