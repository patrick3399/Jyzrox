import { consumeTabRestore, getListHref } from './navMemory'

type BackRouter = {
  back: () => void
  push: (href: string) => void
  replace: (href: string) => void
}

/** History back that stays inside the section: when this page was reached via
 *  a nav-tab restore of a deep URL, history's previous entry is whatever the
 *  user detoured through (e.g. /library) — climb to the section's last
 *  list-level URL instead. Otherwise plain history back with a fallback.
 *
 *  Shared by the back FAB and the standalone-app edge-swipe gesture: on a page
 *  without a FAB the swipe is the only back affordance, so both paths must
 *  resolve the destination the same way.
 *
 *  The climb replaces the arrival entry rather than pushing onto it. Pushing
 *  would leave the page the user just dismissed one step forward in history,
 *  so backing again would return to it and repeated up/back would grow the
 *  stack without bound. */
export function smartBack(router: BackRouter, fallback: string): void {
  const sectionRoot = fallback.split('?')[0]
  if (consumeTabRestore(window.location.pathname + window.location.search)) {
    router.replace(getListHref(sectionRoot))
    return
  }
  if (window.history.length > 1) {
    router.back()
  } else {
    router.push(fallback)
  }
}
