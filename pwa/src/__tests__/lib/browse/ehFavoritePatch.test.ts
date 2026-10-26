import { describe, expect, it } from 'vitest'
import { ehFavoritePatch, ehIdentityKey } from '@/lib/browse/ehentai'
import { initialFilters } from '@/lib/ehBrowseState'
import type { EhGallery } from '@/lib/types'

const favorites = (favCat: string, favSearch = '') =>
  ehIdentityKey({ tab: 'favorites', query: '', filters: { ...initialFilters, favCat, favSearch } })
const LATEST = ehIdentityKey({ tab: 'search', query: '', filters: initialFilters })
const POPULAR = ehIdentityKey({ tab: 'popular', query: '', filters: initialFilters })

function gallery(gid: number): EhGallery {
  return {
    gid,
    token: `t${gid}`,
    title: `G${gid}`,
    title_jpn: '',
    category: 'Manga',
    thumb: '',
    uploader: 'u',
    posted_at: 0,
    pages: 1,
    rating: 0,
    tags: [],
    expunged: false,
  }
}

describe('ehFavoritePatch', () => {
  it('drops an un-favourited gallery from every Favorites list, whatever its category or search', () => {
    const patch = ehFavoritePatch(5, null)

    expect(patch.updateItem(gallery(5), favorites('all'))).toBeNull()
    expect(patch.updateItem(gallery(5), favorites('3', 'artist:x'))).toBeNull()
  })

  it('leaves other galleries and other surfaces untouched', () => {
    const patch = ehFavoritePatch(5, null)
    const other = gallery(6)
    const same = gallery(5)

    expect(patch.updateItem(other, favorites('all'))).toBe(other)
    expect(patch.updateItem(same, LATEST)).toBe(same)
    expect(patch.updateItem(same, POPULAR)).toBe(same)
  })

  it('moves a gallery out of the category it left and keeps it in All and its new category', () => {
    const patch = ehFavoritePatch(5, 2)
    const item = gallery(5)

    expect(patch.updateItem(item, favorites('3'))).toBeNull()
    expect(patch.updateItem(item, favorites('all'))).toBe(item)
    expect(patch.updateItem(item, favorites('2'))).toBe(item)
  })

  it('discards a saved All or target-category list that lacks a newly added favourite', () => {
    const patch = ehFavoritePatch(5, 2)

    expect(patch.invalidates?.(favorites('all'), [gallery(1)])).toBe(true)
    expect(patch.invalidates?.(favorites('2'), [gallery(1)])).toBe(true)
    expect(patch.invalidates?.(favorites('all'), [gallery(5)])).toBe(false)
    expect(patch.invalidates?.(favorites('3'), [gallery(1)])).toBe(false)
    expect(patch.invalidates?.(LATEST, [gallery(1)])).toBe(false)
  })

  it('never discards a list for a removal', () => {
    expect(ehFavoritePatch(5, null).invalidates?.(favorites('all'), [gallery(1)])).toBe(false)
  })
})
