/**
 * A change made somewhere in the app — a bookmark, a favourite, a follow — as
 * it applies to the browse lists of one source.
 *
 * Both callbacks must be pure and idempotent, and `updateItem` must keep the
 * item's id: a mounted list applies a patch to its buffer and again to the
 * result of a request that was in flight when the patch arrived, because that
 * response may have been fetched before the change.
 */
export type BrowseListPatch<Item> = {
  /** Return the item itself to leave it, a replacement, or null to drop it. */
  updateItem: (item: Item, identityKey: string) => Item | null
  /**
   * True when the change adds an item to this list at a position the client
   * cannot know. A saved list for which it is true is discarded, so its next
   * visit loads it fresh; a mounted list keeps its buffer until refreshed.
   */
  invalidates?: (identityKey: string, items: readonly Item[]) => boolean
}

/**
 * Apply `update` to every page. Pages without a changed item keep their
 * identity; null means no item changed at all.
 */
export function patchPages<Item>(
  pages: readonly Item[][],
  update: (item: Item) => Item | null,
): { pages: Item[][]; removed: number } | null {
  let changed = false
  let removed = 0
  const next = pages.map((page) => {
    let pageChanged = false
    const kept: Item[] = []
    for (const item of page) {
      const replacement = update(item)
      if (replacement !== item) pageChanged = true
      if (replacement === null) removed += 1
      else kept.push(replacement)
    }
    if (!pageChanged) return page
    changed = true
    return kept
  })
  return changed ? { pages: next, removed } : null
}
