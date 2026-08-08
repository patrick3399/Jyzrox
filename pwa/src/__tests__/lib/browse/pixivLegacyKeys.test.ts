import { describe, expect, it } from 'vitest'
import { clearBrowseSessionStorage } from '@/lib/browse/snapshotStore'

const PIXIV_LEGACY_KEYS = [
  'pixiv_ranking_scrollY',
  'pixiv_feed_scrollY',
  'pixiv_bookmarks_scrollY',
  'pixiv_search_scrollY',
]

describe('Pixiv legacy browse-key invalidation', () => {
  it('removes all four fixed keys without touching unrelated session state', () => {
    for (const key of PIXIV_LEGACY_KEYS) sessionStorage.setItem(key, '{"pages":[]}')
    sessionStorage.setItem('pixiv_view_mode', 'grid')

    clearBrowseSessionStorage(sessionStorage)

    for (const key of PIXIV_LEGACY_KEYS) expect(sessionStorage.getItem(key)).toBeNull()
    expect(sessionStorage.getItem('pixiv_view_mode')).toBe('grid')
  })

  it('continues best-effort invalidation when one remove operation throws', () => {
    const values = new Map(PIXIV_LEGACY_KEYS.map((key) => [key, 'legacy']))
    const storage: Storage = {
      get length() {
        return values.size
      },
      clear: () => values.clear(),
      getItem: (key) => values.get(key) ?? null,
      key: (index) => [...values.keys()][index] ?? null,
      removeItem: (key) => {
        if (key === 'pixiv_feed_scrollY') throw new DOMException('blocked', 'SecurityError')
        values.delete(key)
      },
      setItem: (key, value) => values.set(key, value),
    }

    expect(() => clearBrowseSessionStorage(storage)).not.toThrow()
    expect(values.has('pixiv_ranking_scrollY')).toBe(false)
    expect(values.has('pixiv_bookmarks_scrollY')).toBe(false)
    expect(values.has('pixiv_search_scrollY')).toBe(false)
  })
})
