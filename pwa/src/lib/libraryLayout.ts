import type { ColumnConfig } from '@/components/VirtualGrid'
import type { GridDensityPreference } from '@/lib/uiPreferences'

// Height reserved below the cover for a LibraryGalleryCard's info block:
// p-2.5 (20) + 2-line line-clamp title text-sm/leading-snug (~39) + gap-1.5 (6)
// + rating/pages row pt-1 + text-base (~20) + card border (2) ≈ 87px.
// This MUST NOT underestimate the real info height: `measureRows={false}` places
// the next row at `rowHeight + gap`, so a too-small reserve makes the next row
// overlap and cover the previous card's bottom edge — including its focus ring.
const LIBRARY_CARD_INFO_HEIGHT = 88

const AUTO_COLUMNS: Record<GridDensityPreference, ColumnConfig> = {
  spacious: { base: 2, sm: 3, md: 4, lg: 5, xl: 6, xxl: 7 },
  comfortable: { base: 4, sm: 5, md: 6, lg: 8, xl: 10, xxl: 12 },
  compact: { base: 4, sm: 6, md: 8, lg: 10, xl: 12, xxl: 12 },
}

export function getLibraryGridColumns(
  density: GridDensityPreference,
  preferredColumns = 0,
): ColumnConfig {
  if (preferredColumns <= 0) return AUTO_COLUMNS[density]
  const max = Math.max(2, Math.min(12, Math.round(preferredColumns)))
  return {
    base: Math.min(2, max),
    sm: Math.min(3, max),
    md: Math.min(4, max),
    lg: Math.min(Math.max(5, Math.ceil(max * 0.67)), max),
    xl: Math.min(Math.max(6, Math.ceil(max * 0.84)), max),
    xxl: max,
  }
}

export function getLibraryGridGap(density: GridDensityPreference): number {
  if (density === 'compact') return 8
  if (density === 'spacious') return 16
  return 12
}

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
