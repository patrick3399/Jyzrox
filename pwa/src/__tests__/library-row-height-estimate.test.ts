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

import { afterEach, describe, it, expect } from 'vitest'
import {
  estimateLibraryGridRowHeight,
  getLibraryGridColumns,
  getLibraryGridGap,
} from '@/lib/libraryLayout'

// Info block: p-2 (16) + 1-line title leading-5 (20) + gap-1 (4)
// + rating/pages row h-4 (16) = 56px. The reserve must be at least this.
const MIN_INFO_RESERVE = 56

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

    // coverHeight (~201) + info (56) exceeds the old 280 cap; the cap must not
    // clip it back down to 280, which would reintroduce the overlap.
    expect(coverHeight + MIN_INFO_RESERVE).toBeGreaterThan(200)
    expect(est).toBeGreaterThanOrEqual(coverHeight + MIN_INFO_RESERVE)
  })

  it('test_estimate_does_not_reserve_an_empty_second_title_line_below_one_line_titles', () => {
    // The card title is one truncated line. Reserving a second line (~20px) left a
    // blank band under every card on top of the grid gap.
    const gap = 12
    const colCount = 4
    const containerWidth = 640
    const cardWidth = (containerWidth - gap * (colCount - 1)) / colCount
    const coverHeight = cardWidth * (4 / 3)
    const est = estimateLibraryGridRowHeight({ colCount, containerWidth, gap })

    expect(est - coverHeight).toBeLessThan(MIN_INFO_RESERVE + 2 + 1)
  })
})

describe('estimateLibraryGridRowHeight text reserve and the root font size', () => {
  afterEach(() => {
    document.documentElement.style.fontSize = ''
  })

  it('test_estimate_is_unchanged_at_a_16px_root_font', () => {
    // Tallest card at a 16px root: 179.333 cover + 56 text + 2 border = 237.333.
    expect(estimateLibraryGridRowHeight({ colCount: 8, containerWidth: 1160, gap: 12 })).toBe(238)
  })

  it('test_estimate_reserve_grows_with_a_20_8px_root_font_so_larger_text_does_not_overlap_next_row', () => {
    const layout = { colCount: 8, containerWidth: 1160, gap: 12 }
    document.documentElement.style.fontSize = '20.8px'

    // The info text is rem-based and grows with the root font, so the reserve
    // must too: 179.333 cover + 3.5rem (72.8) + 2px border = 254.133. A fixed
    // 58px reserve returns 238 here and the next row covers this card.
    const tallestCard = 179.333 + 3.5 * 20.8 + 2
    const est = estimateLibraryGridRowHeight(layout)

    expect(est).toBeGreaterThanOrEqual(tallestCard)
    expect(est - tallestCard).toBeLessThan(1)
  })

  it('test_estimate_reserve_shrinks_with_a_12_8px_root_font', () => {
    const layout = { colCount: 8, containerWidth: 1160, gap: 12 }
    document.documentElement.style.fontSize = '12.8px'

    const tallestCard = 179.333 + 3.5 * 12.8 + 2
    const est = estimateLibraryGridRowHeight(layout)

    expect(est).toBeGreaterThanOrEqual(tallestCard)
    expect(est - tallestCard).toBeLessThan(1)
  })
})

describe('library grid preferences', () => {
  it('uses distinct responsive density presets', () => {
    expect(getLibraryGridColumns('spacious')).toEqual({
      base: 2,
      sm: 3,
      md: 4,
      lg: 5,
      xl: 6,
      xxl: 7,
    })
    expect(getLibraryGridColumns('compact').lg).toBeGreaterThan(
      getLibraryGridColumns('comfortable').lg ?? 0,
    )
    expect(getLibraryGridGap('spacious')).toBe(16)
    expect(getLibraryGridGap('compact')).toBe(8)
  })

  it('treats a manual column value as a desktop maximum', () => {
    const columns = getLibraryGridColumns('comfortable', 9)
    expect(columns.base).toBe(2)
    expect(columns.md).toBe(4)
    expect(columns.xxl).toBe(9)
  })
})
