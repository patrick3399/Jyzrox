export type BrowseAnchor = {
  itemId: string | number | null
  offset: number
  scrollY: number
}

export type AnchorRestoreDecision =
  | { kind: 'anchor'; index: number; offset: number }
  | { kind: 'pixel'; scrollY: number }
  | { kind: 'top' }

export function decideAnchorRestore<Item>(
  anchor: BrowseAnchor,
  items: readonly Item[],
  getItemId: (item: Item) => string | number,
): AnchorRestoreDecision {
  if (anchor.itemId !== null) {
    const index = items.findIndex((item) => getItemId(item) === anchor.itemId)
    if (index >= 0) return { kind: 'anchor', index, offset: anchor.offset }
  }
  if (Number.isFinite(anchor.scrollY) && anchor.scrollY >= 0) {
    return { kind: 'pixel', scrollY: anchor.scrollY }
  }
  return { kind: 'top' }
}

/**
 * Viewport offset to restore an anchor card at. The stored offset is the card's
 * top at capture time; if the card has since become shorter (e.g. a layout
 * change shipped between capture and restore) a negative offset as deep as the
 * card would leave it entirely above the viewport, so align its top instead.
 * A zero height means the card is not laid out yet; keep the stored offset.
 */
export function restoreAnchorOffset(offset: number, cardHeight: number): number {
  if (cardHeight > 0 && offset <= -cardHeight) return 0
  return offset
}
