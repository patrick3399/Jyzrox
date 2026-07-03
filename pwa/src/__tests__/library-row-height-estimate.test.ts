/**
 * Library grid row-height estimate — focus-ring bottom-clip regression
 *
 * Bug: `estimateLibraryGridRowHeight` reserved only +72px below the cover for the
 * card's info block (title + rating + padding), whose real height is ~85-87px. It
 * also capped the result at 280px. Because the grid runs with `measureRows={false}`,
 * the next virtual row is positioned at `rowHeight + gap`; an under-reserved height
 * therefore let each next row overlap the previous card's bottom edge, covering its
 * focus ring. (Removing `paint` containment fixed the TOP edge; this fixes the
 * BOTTOM edge, which is a genuine row overlap.)
 *
 * These tests pin the reserve to at least the measured info-block height and assert
 * the estimate is never truncated below the real card height.
 */

import { describe, it, expect } from 'vitest'
import { estimateLibraryGridRowHeight } from '@/app/library/page'

// Measured info block: p-2.5 (20) + 2-line title (~39) + gap-1.5 (6)
// + rating/pages row (~20) = ~85px. The reserve must be at least this.
const MIN_INFO_RESERVE = 85

describe('estimateLibraryGridRowHeight', () => {
  it('test_estimate_reserves_full_info_block_height_below_cover', () => {
    const gap = 12
    const colCount = 4
    const containerWidth = 640

    const cardWidth = (containerWidth - gap * (colCount - 1)) / colCount
    const coverHeight = cardWidth * (4 / 3)
    const est = estimateLibraryGridRowHeight({ colCount, containerWidth, gap })

    // Under-reserving here is exactly what let the next row cover the ring.
    expect(est - coverHeight).toBeGreaterThanOrEqual(MIN_INFO_RESERVE)
  })

  it('test_estimate_is_not_truncated_below_real_card_height_for_wide_cards', () => {
    const gap = 12
    const colCount = 4
    const containerWidth = 640

    const cardWidth = (containerWidth - gap * (colCount - 1)) / colCount
    const coverHeight = cardWidth * (4 / 3)
    const est = estimateLibraryGridRowHeight({ colCount, containerWidth, gap })

    // coverHeight (~201) + info (~85) exceeds the old 280 cap; the cap must not
    // clip it back down to 280, which would reintroduce the overlap.
    expect(coverHeight + MIN_INFO_RESERVE).toBeGreaterThan(280)
    expect(est).toBeGreaterThanOrEqual(coverHeight + MIN_INFO_RESERVE)
  })
})
