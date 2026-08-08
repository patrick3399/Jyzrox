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
