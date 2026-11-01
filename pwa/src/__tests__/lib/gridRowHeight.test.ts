/**
 * Row heights for the grids that run with `measureRows={false}`.
 *
 * Lists that hand the virtualizer a hard-coded numeric estimate and let rows be
 * measured leave every row above a restored scroll position at the guess;
 * scrolling up then corrects scrollTop by the guess error once per row. The
 * pages therefore pass a width-derived function and fixed rows.
 *
 * Fixed rows are placed exactly `rowHeight + gap` apart, so each estimator must
 * return at least the TALLEST possible card (a shortfall makes the next row
 * overlap that card) and less than one pixel more (more is a visible gap).
 * Card heights below were measured on the live page at a 16px root font.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  estimateArtistGalleryRowHeight,
  estimateArtistRowHeight,
  estimateGalleryThumbRowHeight,
  estimateHistoryRowHeight,
  gridCardWidth,
  rootFontSize,
} from '@/lib/gridRowHeight'

const SM_QUERY = '(min-width: 40rem)'

const originalMatchMediaDescriptor = Object.getOwnPropertyDescriptor(window, 'matchMedia')

function stubMatchMedia(matches: boolean) {
  const matchMedia = vi.fn((query: string) => ({ matches, media: query }) as MediaQueryList)
  Object.defineProperty(window, 'matchMedia', {
    value: matchMedia,
    configurable: true,
    writable: true,
  })
  return matchMedia
}

function removeMatchMedia() {
  Object.defineProperty(window, 'matchMedia', {
    value: undefined,
    configurable: true,
    writable: true,
  })
}

afterEach(() => {
  document.documentElement.style.fontSize = ''
  if (originalMatchMediaDescriptor) {
    Object.defineProperty(window, 'matchMedia', originalMatchMediaDescriptor)
  } else {
    Reflect.deleteProperty(window, 'matchMedia')
  }
})

/** Both bounds that fixed-row layout needs. */
function expectTightFit(rowHeight: number, tallestCard: number) {
  // Fixed rows are placed rowHeight + gap apart: any shortfall makes the next
  // row overlap this one, and more than a pixel of slack is a visible gap.
  expect(rowHeight).toBeGreaterThanOrEqual(tallestCard)
  expect(rowHeight - tallestCard).toBeLessThan(1)
}

describe('gridCardWidth', () => {
  it('splits the container width evenly across columns after subtracting the gaps', () => {
    expect(gridCardWidth({ colCount: 7, containerWidth: 1160, gap: 8 })).toBeCloseTo(158.857, 3)
    expect(gridCardWidth({ colCount: 1, containerWidth: 300, gap: 12 })).toBe(300)
  })
})

describe('rootFontSize', () => {
  it('reads the computed root font size in pixels', () => {
    document.documentElement.style.fontSize = '20px'

    expect(rootFontSize()).toBe(20)
  })

  it('falls back to 16 when the root font size is not a usable number', () => {
    document.documentElement.style.fontSize = ''
    const spy = vi
      .spyOn(window, 'getComputedStyle')
      .mockReturnValue({ fontSize: '' } as CSSStyleDeclaration)
    try {
      expect(rootFontSize()).toBe(16)
    } finally {
      spy.mockRestore()
    }
  })
})

describe('estimateArtistRowHeight', () => {
  it.each([
    {
      name: 'all artists in 7 columns',
      layout: { colCount: 7, containerWidth: 1160, gap: 8 },
      tallestCard: 222.857,
    },
    {
      name: 'followed artists in 5 columns',
      layout: { colCount: 5, containerWidth: 1160, gap: 16 },
      tallestCard: 283.2,
    },
  ])(
    'reserves a square cover plus 4rem of text for $name without rounding below it',
    ({ layout, tallestCard }) => {
      expectTightFit(estimateArtistRowHeight(layout), tallestCard)
    },
  )

  it('scales the reserved text height with a 20px root font so larger text does not overlap the next row', () => {
    const layout = { colCount: 7, containerWidth: 1160, gap: 8 }
    document.documentElement.style.fontSize = '20px'

    // 4rem of text at 20px is 80px.
    expectTightFit(estimateArtistRowHeight(layout), gridCardWidth(layout) + 80)
  })
})

describe('estimateArtistGalleryRowHeight', () => {
  it('reserves the 2-line-title card at the sm breakpoint and above (viewport >= 640px)', () => {
    const matchMedia = stubMatchMedia(true)

    expectTightFit(
      estimateArtistGalleryRowHeight({ colCount: 8, containerWidth: 1160, gap: 6 }),
      258.667,
    )
    expect(matchMedia).toHaveBeenCalledWith(SM_QUERY)
  })

  it('reserves the stacked-meta card below the sm breakpoint (viewport < 640px)', () => {
    const matchMedia = stubMatchMedia(false)

    expectTightFit(
      estimateArtistGalleryRowHeight({ colCount: 4, containerWidth: 358, gap: 6 }),
      175.917,
    )
    expect(matchMedia).toHaveBeenCalledWith(SM_QUERY)
  })

  it('uses a different reserve above and below the sm breakpoint for the same layout', () => {
    const layout = { colCount: 4, containerWidth: 358, gap: 6 }
    stubMatchMedia(true)
    const wide = estimateArtistGalleryRowHeight(layout)
    stubMatchMedia(false)
    const narrow = estimateArtistGalleryRowHeight(layout)

    // At a 16px root the sm card reserves 72.333px of non-cover height against 62.583px.
    expect(wide).toBeGreaterThan(narrow)
  })

  it('reserves the larger of the two cards when matchMedia is unavailable', () => {
    removeMatchMedia()
    const layout = { colCount: 8, containerWidth: 1160, gap: 6 }

    // At a 16px root the sm variant is the taller one.
    expectTightFit(estimateArtistGalleryRowHeight(layout), 258.667)
  })

  it('picks the taller variant at a 12.8px root when matchMedia is unavailable', () => {
    removeMatchMedia()
    document.documentElement.style.fontSize = '12.8px'
    const layout = { colCount: 8, containerWidth: 1160, gap: 6 }
    const cover = (gridCardWidth(layout) * 4) / 3
    const smCard = cover + 4.5625 * 12.8 - 0.6667
    const narrowCard = cover + 1.125 * 12.8 + 44.5833

    // At a small root the stacked-meta card (fixed pixel part) overtakes the sm card.
    expect(narrowCard).toBeGreaterThan(smCard)
    expectTightFit(estimateArtistGalleryRowHeight(layout), narrowCard)
  })

  it.each([
    { matches: true, label: 'sm and up' },
    { matches: false, label: 'below sm' },
  ])('scales the rem part of the reserve with a 12.8px root font ($label)', ({ matches }) => {
    stubMatchMedia(matches)
    document.documentElement.style.fontSize = '12.8px'
    const layout = { colCount: 6, containerWidth: 900, gap: 6 }
    const cover = (gridCardWidth(layout) * 4) / 3
    const tallestCard = matches ? cover + 4.5625 * 12.8 - 0.6667 : cover + 1.125 * 12.8 + 44.5833

    expectTightFit(estimateArtistGalleryRowHeight(layout), tallestCard)
  })

  it('scales the rem part of the reserve with a 20px root font at sm and up', () => {
    stubMatchMedia(true)
    document.documentElement.style.fontSize = '20px'
    const layout = { colCount: 8, containerWidth: 1160, gap: 6 }
    const cover = (gridCardWidth(layout) * 4) / 3

    expectTightFit(estimateArtistGalleryRowHeight(layout), cover + 4.5625 * 20 - 0.6667)
  })
})

describe('estimateHistoryRowHeight', () => {
  it('reserves the 2-line-title history card in 8 columns without rounding below it', () => {
    expectTightFit(
      estimateHistoryRowHeight({ colCount: 8, containerWidth: 1160, gap: 12 }),
      248.667,
    )
  })

  it('scales the reserved text height with a 20px root font so larger text does not overlap the next row', () => {
    document.documentElement.style.fontSize = '20px'

    // 179.333 cover + 3.4375rem (68.75) + 14.333 of px-sized meta line.
    expectTightFit(
      estimateHistoryRowHeight({ colCount: 8, containerWidth: 1160, gap: 12 }),
      262.417,
    )
  })
})

describe('estimateGalleryThumbRowHeight', () => {
  it('reserves exactly the 3:4 thumbnail height without rounding below it', () => {
    expectTightFit(
      estimateGalleryThumbRowHeight({ colCount: 10, containerWidth: 1118, gap: 8 }),
      139.467,
    )
  })

  it('does not depend on the root font size because the thumbnail has no text', () => {
    const layout = { colCount: 10, containerWidth: 1118, gap: 8 }
    const atDefault = estimateGalleryThumbRowHeight(layout)
    document.documentElement.style.fontSize = '20px'

    expect(estimateGalleryThumbRowHeight(layout)).toBe(atDefault)
  })
})
