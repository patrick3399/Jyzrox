/** In-memory memory of how an E-Hentai gallery detail page looked when the user
 *  last used it.
 *
 *  The detail page paginates its previews with an imperative request (Load more
 *  / infinite scroll), so none of that lives in the SWR cache. Opening the
 *  reader unmounts the page; coming back used to mount it with only the first
 *  preview batch, a much shorter document, and the browser's native scroll
 *  restoration landing on the wrong content. Keeping the paginated previews and
 *  the related UI state here lets a remount rebuild the same page without
 *  another request.
 *
 *  Bounded (LRU) and per document: a reload starts clean, like the SWR cache. */

export type EhDetailView = {
  extraPreviews: Record<string, string>
  hasMore: boolean
  infiniteScroll: boolean
  showComments: boolean
  showAllComments: boolean
  /** Scroll position captured when the user navigated away (reader, a
   *  thumbnail, a related gallery). Null once consumed or when they left by
   *  some other route; applied once, after the restored content has rendered. */
  scrollY: number | null
  /** Thumbnail count on screen at that moment: the restored scroll is only
   *  meaningful once at least this many have rendered again. */
  thumbCount: number
}

export const EH_DETAIL_VIEW_LIMIT = 16

const views = new Map<string, EhDetailView>()

export function ehDetailViewKey(gid: number, token: string): string {
  return `${gid}:${token}`
}

const EMPTY_VIEW: EhDetailView = {
  extraPreviews: {},
  hasMore: true,
  infiniteScroll: false,
  showComments: false,
  showAllComments: false,
  scrollY: null,
  thumbCount: 0,
}

export function readEhDetailView(key: string): EhDetailView | undefined {
  return views.get(key)
}

/** Merge `patch` into the view stored for `key`, marking it most recently used. */
export function saveEhDetailView(key: string, patch: Partial<EhDetailView>): void {
  const next: EhDetailView = { ...EMPTY_VIEW, ...views.get(key), ...patch }
  views.delete(key)
  views.set(key, next)
  while (views.size > EH_DETAIL_VIEW_LIMIT) {
    const oldest = views.keys().next()
    if (oldest.done) break
    views.delete(oldest.value)
  }
}

export function clearEhDetailViews(): void {
  views.clear()
}
