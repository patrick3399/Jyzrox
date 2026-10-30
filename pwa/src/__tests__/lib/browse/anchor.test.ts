import { describe, expect, it } from 'vitest'
import { decideAnchorRestore, restoreAnchorOffset } from '@/lib/browse/anchor'

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

describe('restoreAnchorOffset', () => {
  it('test_offset_deeper_than_the_current_card_height_aligns_the_card_top_instead_of_hiding_it', () => {
    // Captured 290px into a 300px card; after the card shrank to 270px the same
    // offset would leave the anchor card fully above the viewport.
    expect(restoreAnchorOffset(-290, 270)).toBe(0)
    expect(restoreAnchorOffset(-270, 270)).toBe(0)
  })

  it('test_offset_within_the_current_card_height_is_kept', () => {
    expect(restoreAnchorOffset(-200, 270)).toBe(-200)
    expect(restoreAnchorOffset(120, 270)).toBe(120)
  })

  it('test_unmeasured_card_keeps_the_stored_offset', () => {
    // A zero height means no layout yet; do not guess.
    expect(restoreAnchorOffset(-290, 0)).toBe(-290)
  })
})
