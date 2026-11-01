'use client'

import type { MarqueeRect } from '@/hooks/useExplorerSelection'

/**
 * Rubber-band rectangle drawn over the grid while dragging on empty space.
 * Coordinates are relative to the scroll container's content, so the parent
 * scroll element must be `position: relative`.
 */
export function SelectionMarquee({ rect }: { rect: MarqueeRect | null }) {
  if (!rect) return null
  return (
    <div
      data-testid="selection-marquee"
      aria-hidden="true"
      className="pointer-events-none absolute z-20 rounded-sm border border-vault-accent bg-vault-accent/15"
      style={{ left: rect.left, top: rect.top, width: rect.width, height: rect.height }}
    />
  )
}
