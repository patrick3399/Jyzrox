export type BrowseHistoryMode = 'push' | 'replace'

/** Write a same-page browse identity to the URL.
 *
 *  These are same-page transitions: the local reducer already owns the view, so
 *  going through Next's router would fetch an RSC payload for a page that is
 *  already rendered, and iOS standalone Safari can then fall back to a document
 *  navigation with an empty query string.
 *
 *  The App Router patches pushState/replaceState to copy its own internals onto
 *  the entry being written and to dispatch ACTION_RESTORE so usePathname and
 *  useSearchParams hold the new URL. That patch bails out to the unpatched call
 *  when the supplied state already carries `__NA` — which every App Router
 *  entry does — so passing `window.history.state` back in opts out of the sync
 *  and leaves useSearchParams on the previous query. Pass a fresh object and
 *  let the patch carry the internals over itself. */
export function commitBrowseUrl(url: string, historyMode: BrowseHistoryMode): void {
  if (historyMode === 'push') window.history.pushState({}, '', url)
  else window.history.replaceState({}, '', url)
}
