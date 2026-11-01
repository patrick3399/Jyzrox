import { beforeEach, describe, expect, it } from 'vitest'
import {
  clearEhDetailViews,
  EH_DETAIL_VIEW_LIMIT,
  ehDetailViewKey,
  readEhDetailView,
  saveEhDetailView,
} from '@/lib/ehDetailView'

beforeEach(() => clearEhDetailViews())

describe('ehDetailView cache', () => {
  it('merges patches into the stored view instead of replacing it', () => {
    const key = ehDetailViewKey(1, 'a')
    saveEhDetailView(key, { extraPreviews: { '3': 'u3' }, infiniteScroll: true })
    saveEhDetailView(key, { scrollY: 900, thumbCount: 30 })

    expect(readEhDetailView(key)).toMatchObject({
      extraPreviews: { '3': 'u3' },
      infiniteScroll: true,
      scrollY: 900,
      thumbCount: 30,
    })
  })

  it('keys by gid and token together', () => {
    saveEhDetailView(ehDetailViewKey(1, 'a'), { hasMore: false })

    expect(readEhDetailView(ehDetailViewKey(1, 'b'))).toBeUndefined()
    expect(readEhDetailView(ehDetailViewKey(2, 'a'))).toBeUndefined()
  })

  it('evicts the least recently used gallery past the limit', () => {
    for (let gid = 1; gid <= EH_DETAIL_VIEW_LIMIT; gid++) {
      saveEhDetailView(ehDetailViewKey(gid, 't'), { hasMore: false })
    }
    // Touch gallery 1 so gallery 2 becomes the oldest.
    saveEhDetailView(ehDetailViewKey(1, 't'), { showComments: true })
    saveEhDetailView(ehDetailViewKey(EH_DETAIL_VIEW_LIMIT + 1, 't'), { hasMore: false })

    expect(readEhDetailView(ehDetailViewKey(2, 't'))).toBeUndefined()
    expect(readEhDetailView(ehDetailViewKey(1, 't'))?.showComments).toBe(true)
    expect(readEhDetailView(ehDetailViewKey(EH_DETAIL_VIEW_LIMIT + 1, 't'))).toBeDefined()
  })
})
