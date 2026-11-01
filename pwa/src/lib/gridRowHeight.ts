/** Row heights for the grids that run with fixed, width-derived rows, excluding
 *  the gap below the row.
 *
 *  Each of these grids passes one of these functions as `estimateHeight` with
 *  `measureRows={false}`: rows are placed exactly `rowHeight + gap` apart, so a
 *  result below the real card height makes the next row overlap the card, and a
 *  result a pixel or more above it leaves a visible gap. Every function therefore
 *  reserves the tallest variant of its card and rounds up, which costs under a
 *  pixel. Cards whose text can wrap are kept to single lines (`truncate`) so
 *  their height stays a pure function of the column width.
 *
 *  Text heights are kept in rem where the card's classes are rem-based, so the
 *  reserve follows the live root font size (users can scale it 80%-130%) instead
 *  of undercutting the text at a larger size. Terms that are fixed in pixels
 *  (`text-[10px]` and friends) are not scaled. */

export type RowHeightContext = { colCount: number; containerWidth: number; gap: number }

/** Computed root font size in px; 16 on the server or when it cannot be parsed. */
export function rootFontSize(): number {
  if (typeof window === 'undefined') return 16
  const size = Number.parseFloat(window.getComputedStyle(document.documentElement).fontSize)
  return Number.isFinite(size) && size > 0 ? size : 16
}

/** Width of one grid card: the container minus the column gaps, split evenly. */
export function gridCardWidth({ colCount, containerWidth, gap }: RowHeightContext): number {
  const columns = Math.max(colCount, 1)
  return Math.max(0, containerWidth - gap * (columns - 1)) / columns
}

/** Artist card (all and followed): 1px border + square cover + `p-3` (1.5rem) +
 *  `text-sm` title line (1.25rem) + `space-y-1` (0.25rem) + `text-xs` line
 *  (1rem). The 2px of border cancels the 2px it takes from the cover, so the
 *  tallest card is `W + 4rem`. */
export function estimateArtistRowHeight(layout: RowHeightContext) {
  return Math.ceil(gridCardWidth(layout) + 4 * rootFontSize())
}

/** Artist detail gallery card: 3:4 cover + info block. The info block uses `sm:`
 *  variants, which key off the viewport, so the variant is picked with
 *  `matchMedia`. At and above `sm`: `sm:p-2.5` 1.25rem + 2-line `text-xs leading-snug`
 *  title 2.0625rem + `space-y-1` 0.25rem + `text-xs` pages line 1rem; the 2px
 *  border less the 8/3px it removes from the cover is -2/3px. Below `sm`: `p-2`
 *  1rem + `space-y-0.5` 0.125rem, plus in px a 2-line `text-[11px] leading-snug`
 *  title (30.25), a `text-[10px]` pages line at the inherited 1.5 line-height
 *  (15) and the border term (-2/3). Without `matchMedia` the larger one wins. */
export function estimateArtistGalleryRowHeight(layout: RowHeightContext) {
  const rem = rootFontSize()
  const cover = (gridCardWidth(layout) * 4) / 3
  const wide = cover + 4.5625 * rem - 2 / 3
  const narrow = cover + 1.125 * rem + 44.5834
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return Math.ceil(Math.max(wide, narrow))
  }
  return Math.ceil(window.matchMedia('(min-width: 40rem)').matches ? wide : narrow)
}

/** `HistoryCard`: 3:4 cover + `p-2` (1rem) + 2-line `text-xs leading-snug` title
 *  (2.0625rem) + `mt-1.5` (0.375rem); in px one `text-[10px]` meta line (15) and
 *  the border term (-2/3). */
export function estimateHistoryRowHeight(layout: RowHeightContext) {
  return Math.ceil((gridCardWidth(layout) * 4) / 3 + 3.4375 * rootFontSize() + 14.3334)
}

/** Gallery-detail thumbnail: a bare 3:4 image, no text. */
export function estimateGalleryThumbRowHeight(layout: RowHeightContext) {
  return Math.ceil((gridCardWidth(layout) * 4) / 3)
}
