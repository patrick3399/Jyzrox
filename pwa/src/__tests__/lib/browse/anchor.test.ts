import { describe, expect, it } from 'vitest'
import { decideAnchorRestore } from '@/lib/browse/anchor'

type Item = { id: string }
const items: Item[] = [{ id: 'a' }, { id: 'b' }, { id: 'c' }]

describe('browse anchor restoration decisions', () => {
  it('prefers an existing item anchor and preserves its viewport offset', () => {
    expect(
      decideAnchorRestore({ itemId: 'b', offset: 17, scrollY: 900 }, items, (item) => item.id),
    ).toEqual({ kind: 'anchor', index: 1, offset: 17 })
  })

  it('falls back to a finite non-negative pixel position when the item disappeared', () => {
    expect(
      decideAnchorRestore(
        { itemId: 'missing', offset: 17, scrollY: 900 },
        items,
        (item) => item.id,
      ),
    ).toEqual({ kind: 'pixel', scrollY: 900 })
  })

  it.each([Number.NaN, Number.POSITIVE_INFINITY, -1])(
    'falls back to top when neither anchor nor a valid pixel position exists (%s)',
    (scrollY) => {
      expect(
        decideAnchorRestore({ itemId: 'missing', offset: 17, scrollY }, items, (item) => item.id),
      ).toEqual({ kind: 'top' })
    },
  )

  it('uses the pixel fallback when no item anchor was captured', () => {
    expect(
      decideAnchorRestore({ itemId: null, offset: 0, scrollY: 120 }, items, (i) => i.id),
    ).toEqual({ kind: 'pixel', scrollY: 120 })
  })
})
