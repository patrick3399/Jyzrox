import { gridCardWidth } from '@/lib/gridRowHeight'

/** Height of one E-Hentai grid row, excluding the gap below it.
 *
 *  A grid tile (`GridCard`) is an `aspect-[3/4]` box with its title, uploader
 *  and rating overlaid on the cover, so nothing below the cover adds height and
 *  the row height follows from the column width alone.
 *
 *  The grid uses this with `measureRows={false}`. Rows are then placed exactly
 *  `rowHeight + gap` apart, so this MUST NOT come out below the real tile
 *  height or the next row overlaps the tile; rounding up costs under a pixel. */
export function estimateEhGridRowHeight(layout: {
  colCount: number
  containerWidth: number
  gap: number
}) {
  return Math.ceil(gridCardWidth(layout) * (4 / 3))
}
