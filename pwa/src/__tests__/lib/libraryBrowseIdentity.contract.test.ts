import { describe, expect, it } from 'vitest'
import {
  canonicalLibraryBrowseIdentity,
  invalidateLegacyLibraryScroll,
  isLibraryBrowseCursor,
  isSearchGalleryItem,
  libraryBrowseIdentityKey,
} from '@/lib/browse/library'

describe('Library browse-session canonical identity contract', () => {
  it('normalizes every URL field that changes Library results', () => {
    expect(
      canonicalLibraryBrowseIdentity(
        '  source:pixiv artist:z artist:a artist:z -language:ja -language:en ' +
          'title:"re zero" rating:>=4 favorited:true rl:true collection:5 ' +
          'artist_id:pixiv:123 category:manga import:link sort:rating  ',
      ),
    ).toEqual({
      surface: 'library',
      tags: ['artist:a', 'artist:z'],
      nameOnlyTags: [],
      excludeTags: ['language:en', 'language:ja'],
      title: 're zero',
      source: 'pixiv',
      rating: 4,
      favorited: true,
      readingList: true,
      collection: 5,
      artistId: 'pixiv:123',
      category: 'manga',
      importMode: 'link',
      sort: 'rating',
    })
  })

  it('gives reordered and duplicated filters the same key, but separates sort or filter changes', () => {
    const canonical = 'artist:a artist:z -language:en source:pixiv sort:rating'
    const reordered = 'sort:rating artist:z source:pixiv artist:a artist:z -language:en'

    expect(libraryBrowseIdentityKey(reordered)).toBe(libraryBrowseIdentityKey(canonical))
    expect(libraryBrowseIdentityKey(`${canonical} favorited:true`)).not.toBe(
      libraryBrowseIdentityKey(canonical),
    )
    expect(libraryBrowseIdentityKey(canonical.replace('sort:rating', 'sort:pages'))).not.toBe(
      libraryBrowseIdentityKey(canonical),
    )
  })

  it('uses the effective default sort when the URL omits sort', () => {
    expect(canonicalLibraryBrowseIdentity('artist:a')).toMatchObject({ sort: 'added_at' })
    expect(libraryBrowseIdentityKey('artist:a')).toBe(
      libraryBrowseIdentityKey('artist:a sort:added_at'),
    )
  })
})

describe('Library legacy snapshot migration contract', () => {
  it('invalidates library_scrollY exactly once and leaves unrelated storage intact', () => {
    localStorage.setItem('library_scrollY', JSON.stringify({ scrollY: 900 }))
    localStorage.setItem('unrelated', 'keep')

    expect(invalidateLegacyLibraryScroll(localStorage)).toBe(true)
    expect(localStorage.getItem('library_scrollY')).toBeNull()
    expect(localStorage.getItem('unrelated')).toBe('keep')
    expect(invalidateLegacyLibraryScroll(localStorage)).toBe(false)
  })

  it('treats inaccessible storage as an already-invalidated best-effort migration', () => {
    const inaccessible = {
      getItem: () => {
        throw new DOMException('Storage is blocked', 'SecurityError')
      },
      removeItem: () => {
        throw new DOMException('Storage is blocked', 'SecurityError')
      },
    } as Pick<Storage, 'getItem' | 'removeItem'> as Storage

    expect(() => invalidateLegacyLibraryScroll(inaccessible)).not.toThrow()
    expect(invalidateLegacyLibraryScroll(inaccessible)).toBe(false)
  })
})

describe('Library snapshot runtime validation', () => {
  const item = {
    id: 1,
    title: 'Gallery',
    title_jpn: null,
    source: 'local',
    source_id: 'gallery-1',
    category: null,
    language: null,
    pages: 10,
    rating: 4,
    favorited: false,
    is_favorited: false,
    my_rating: null,
    in_reading_list: false,
    artist_id: null,
    import_mode: null,
    source_url: null,
    tags_array: [],
    uploader: null,
    download_status: 'completed',
    added_at: null,
    posted_at: null,
    tags: [],
  }

  it('accepts only non-empty cursor strings', () => {
    expect(isLibraryBrowseCursor('next-page')).toBe(true)
    expect(isLibraryBrowseCursor('')).toBe(false)
    expect(isLibraryBrowseCursor(3)).toBe(false)
  })

  it('rejects corrupt gallery snapshots before hydration', () => {
    expect(isSearchGalleryItem(item)).toBe(true)
    expect(isSearchGalleryItem({ ...item, id: '1' })).toBe(false)
    expect(isSearchGalleryItem({ ...item, tags: [null] })).toBe(false)
    expect(isSearchGalleryItem({ ...item, source_id: '' })).toBe(false)
  })
})
