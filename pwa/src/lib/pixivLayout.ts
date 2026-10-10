/** Row heights for the Pixiv browse grid, excluding the gap below the row.
 *
 *  Each grid card is a square (or a strip of squares) followed by single-line,
 *  truncated text, so its height follows from the column width. The grid uses
 *  these with `measureRows={false}`: rows are placed exactly `rowHeight + gap`
 *  apart, so a result below the real card height makes the next row overlap the
 *  card. Every function therefore reserves the tallest variant of its card and
 *  rounds up.
 *
 *  Text heights are kept in rem where the card's classes are rem-based, so a
 *  larger browser default font size grows the reserve with the text instead of
 *  overlapping. List mode has no entry here: its tag chips wrap, so those rows
 *  have no width-derived height and stay measured. */

type RowHeightContext = { colCount: number; containerWidth: number; gap: number }

// `text-[10px]` sets only the font size; the line inherits the unitless 1.5
// line-height, which resolves against those 10px rather than the root size.
const STATS_LINE_PX = 15

function rootFontSize(): number {
  if (typeof window === 'undefined') return 16
  const size = Number.parseFloat(window.getComputedStyle(document.documentElement).fontSize)
  return Number.isFinite(size) && size > 0 ? size : 16
}

function cardWidth({ colCount, containerWidth, gap }: RowHeightContext): number {
  const columns = Math.max(colCount, 1)
  return Math.max(0, containerWidth - gap * (columns - 1)) / columns
}

/** `IllustCard` in grid mode: square cover, then `mt-1.5` + a `text-sm` title
 *  line (1.25rem) + a `text-xs` artist line (1rem) + `mt-0.5` + the stats line. */
export function estimatePixivIllustRowHeight(layout: RowHeightContext) {
  return Math.ceil(cardWidth(layout) + 2.75 * rootFontSize() + STATS_LINE_PX)
}

/** `RankingCard`: square cover, then `mt-1.5` + a `text-sm` title line + a
 *  `text-xs` artist line. */
export function estimatePixivRankingRowHeight(layout: RowHeightContext) {
  return Math.ceil(cardWidth(layout) + 2.625 * rootFontSize())
}

/** `UserPreviewCard`: a 1px border around a strip a third of the inner width
 *  tall, then a `p-2` footer holding the `h-7` avatar. The strip is either three
 *  squares separated by `gap-0.5` or the 3:1 "no works" placeholder; the
 *  placeholder is the taller of the two by 4/3 px, so that is what is reserved. */
export function estimatePixivUserRowHeight(layout: RowHeightContext) {
  const border = 2
  const innerWidth = Math.max(0, cardWidth(layout) - border)
  return Math.ceil(innerWidth / 3 + 2.75 * rootFontSize() + border)
}
