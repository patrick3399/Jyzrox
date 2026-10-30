import { describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/i18n')>()),
  t: (key: string) => key,
}))

import { libraryFilterChips, type LibraryFilterChipContext } from '@/lib/libraryFilterChips'
import { parseQuery } from '@/lib/queryParser'

const ctx: LibraryFilterChipContext = {
  sourceLabel: (combined) => `SRC<${combined}>`,
  collectionName: (id) => (id === 7 ? 'Faves' : undefined),
  sortLabel: (value) => `SORT<${value}>`,
}

const chips = (q: string) => libraryFilterChips(parseQuery(q), ctx)
const keys = (q: string) => chips(q).map((c) => c.key)

describe('libraryFilterChips', () => {
  it('test_no_filters_produces_no_chips', () => {
    expect(chips('')).toEqual([])
    expect(chips('rem character:ram -x:y')).toEqual([])
  })

  it('test_source_with_import_mode_is_one_chip_using_combined_value', () => {
    const result = chips('source:local import:link')
    expect(result.map((c) => c.key)).toEqual(['source'])
    expect(result[0].label).toContain('SRC<local:link>')
  })

  it('test_source_without_import_mode_uses_plain_source', () => {
    expect(chips('source:pixiv')[0].label).toContain('SRC<pixiv>')
  })

  it('test_default_added_at_sort_produces_no_chip', () => {
    expect(keys('sort:added_at')).toEqual([])
  })

  it('test_non_default_sort_produces_chip_with_sort_label', () => {
    const result = chips('sort:rating')
    expect(result.map((c) => c.key)).toEqual(['sort'])
    expect(result[0].label).toContain('SORT<rating>')
  })

  it('test_content_updated_at_sort_token_produces_sort_chip_not_dropped_as_default', () => {
    const result = chips('sort:content_updated_at')
    expect(result.map((c) => c.key)).toEqual(['sort'])
    expect(result[0].label).toContain('SORT<content_updated_at>')
  })

  it('test_rating_chip_label_is_star_at_least_n', () => {
    expect(chips('rating:>=4')[0]).toMatchObject({ key: 'rating', label: '★≥4' })
  })

  it('test_uncategorized_category_uses_translated_label', () => {
    const label = chips('category:__uncategorized__')[0].label
    expect(label).toContain('library.categoryUncategorized')
    expect(label).not.toContain('__uncategorized__')
  })

  it('test_regular_category_shows_raw_value', () => {
    expect(chips('category:manga')[0].label).toContain('manga')
  })

  it('test_collection_chip_uses_name_or_falls_back_to_hash_id', () => {
    expect(chips('collection:7')[0].label).toContain('Faves')
    expect(chips('collection:9')[0].label).toContain('#9')
  })

  it('test_title_chip_shows_title_value', () => {
    const c = chips('title:"re zero"')[0]
    expect(c.key).toBe('title')
    expect(c.label).toContain('re zero')
  })

  it('test_favorited_and_reading_list_chips_are_label_only', () => {
    const result = chips('favorited:true rl:true')
    expect(result.map((c) => c.key)).toEqual(['favorited', 'rl'])
    for (const c of result) expect(c.label).not.toContain(':')
  })

  it('test_artist_id_chip_shows_value', () => {
    const c = chips('artist_id:ehentai:someone')[0]
    expect(c.key).toBe('artist_id')
    expect(c.label).toContain('ehentai:someone')
  })

  it('test_chip_order_is_pinned_regardless_of_query_order', () => {
    const q =
      'artist_id:a rl:true favorited:true sort:rating collection:7 category:manga rating:>=3 source:pixiv title:x'
    expect(keys(q)).toEqual([
      'title',
      'source',
      'rating',
      'category',
      'collection',
      'sort',
      'favorited',
      'rl',
      'artist_id',
    ])
  })

  it('test_active_count_equals_chip_count_with_source_import_pair_counted_once', () => {
    expect(chips('source:local import:link rating:>=2')).toHaveLength(2)
  })
})
