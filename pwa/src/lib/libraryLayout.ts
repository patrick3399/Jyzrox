// Height reserved below the cover for a LibraryGalleryCard's info block:
// p-2.5 (20) + 2-line line-clamp title text-sm/leading-snug (~39) + gap-1.5 (6)
// + rating/pages row pt-1 + text-base (~20) + card border (2) ≈ 87px.
// This MUST NOT underestimate the real info height: `measureRows={false}` places
// the next row at `rowHeight + gap`, so a too-small reserve makes the next row
// overlap and cover the previous card's bottom edge — including its focus ring.
const LIBRARY_CARD_INFO_HEIGHT = 88

export function estimateLibraryGridRowHeight({
  colCount,
  containerWidth,
  gap,
}: {
  colCount: number
  containerWidth: number
  gap: number
}) {
  const safeWidth = Math.max(containerWidth, 320)
  const safeColCount = Math.max(colCount, 1)
  const cardWidth = (safeWidth - gap * (safeColCount - 1)) / safeColCount
  const coverHeight = cardWidth * (4 / 3)

  // No upper clamp: truncating tall (wide-card) rows would underestimate the
  // real card height and reintroduce the next-row overlap described above.
  return Math.ceil(Math.max(188, coverHeight + LIBRARY_CARD_INFO_HEIGHT))
}
