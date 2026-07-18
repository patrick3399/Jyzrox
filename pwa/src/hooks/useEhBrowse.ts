'use client'

import {
  useReducer,
  useRef,
  useCallback,
  useMemo,
  useEffect,
  useLayoutEffect,
  useState,
} from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import {
  reducer,
  initialState,
  parseUrlToIdentity,
  parseSnapshot,
  serializeSnapshot,
  identityToUrlParams,
  buildParams,
  queryKey,
  EH_PAGE_SIZE,
  type EhBrowseState,
  type Action,
  type Filters,
  type Tab,
  type Cursor,
  type FetchPlan,
} from '@/lib/ehBrowseState'
import { api } from '@/lib/api'
import type { EhGallery, EhFavCategory } from '@/lib/types'

const SNAPSHOT_KEY = 'eh_browse_snapshot'

// useLayoutEffect warns during SSR; the server never scrolls, so useEffect is fine there.
const useIsomorphicLayoutEffect = typeof window === 'undefined' ? useEffect : useLayoutEffect

function initFromUrl(search: string): EhBrowseState {
  const identity = parseUrlToIdentity(new URLSearchParams(search))
  const base: EhBrowseState = { ...initialState, ...identity }
  if (typeof window === 'undefined') return base
  // Restore the accumulated buffer + scroll position when the snapshot belongs to
  // the exact same query identity we're mounting with (back-nav / tab round-trip).
  const snap = parseSnapshot(sessionStorage.getItem(SNAPSHOT_KEY), queryKey(base))
  return snap ? { ...base, ...snap } : base
}

export function useEhBrowse() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const [state, dispatch] = useReducer(reducer, searchParams.toString(), initFromUrl)

  // stateRef must be fresh BEFORE child components' passive effects run: VirtualGrid
  // fires onLoadMore from an effect in the very commit an append renders, and child
  // effects flush before parent effects. With a passive-effect sync, loadMore would
  // read the previous commit's status ('loading'), swallow the call, and — since
  // VirtualGrid's fired-at gate only reopens when items.length grows — wedge the
  // infinite scroll permanently. Layout effects (parent included) all flush before
  // any passive effect, so this closes the race.
  const stateRef = useRef(state)
  useIsomorphicLayoutEffect(() => {
    stateRef.current = state
  })
  const inflightRef = useRef<AbortController | null>(null)
  // View-adjacent metadata (favourite-category names/counts) — not part of identity.
  const [favCategories, setFavCategories] = useState<EhFavCategory[]>([])

  // Fetch a single page for the given plan, normalising every tab to
  // { galleries, cursor, hasMore, total }.
  const fetchPage = useCallback(
    async (
      plan: FetchPlan,
      signal: AbortSignal,
    ): Promise<{
      galleries: EhGallery[]
      cursor: Cursor
      hasMore: boolean
      total: number | null
    }> => {
      if (plan.kind === 'search') {
        const res = await api.eh.search(plan.args, { signal })
        return {
          galleries: res.galleries,
          cursor: res.next_gid != null ? { kind: 'gid', nextGid: res.next_gid } : null,
          hasMore: res.next_gid != null,
          total: res.total,
        }
      }
      if (plan.kind === 'toplist') {
        const res = await api.eh.getToplist(plan.args, { signal })
        const hasMore = res.galleries.length >= EH_PAGE_SIZE
        return {
          galleries: res.galleries,
          cursor: hasMore ? { kind: 'page', page: plan.args.page + 1 } : null,
          hasMore,
          total: res.total,
        }
      }
      if (plan.kind === 'popular') {
        const res = await api.eh.getPopular({ signal })
        return { galleries: res.galleries, cursor: null, hasMore: false, total: res.total }
      }
      const res = await api.eh.getFavorites(plan.args, { signal })
      if (res.categories?.length) setFavCategories(res.categories)
      return {
        galleries: res.galleries,
        cursor: res.has_next && res.next_cursor ? { kind: 'fav', next: res.next_cursor } : null,
        hasMore: res.has_next,
        total: res.total,
      }
    },
    [],
  )

  const loadMore = useCallback(async () => {
    const s0 = stateRef.current
    if (s0.status === 'seeding' || s0.status === 'loading') return
    if (s0.items.length > 0 && !s0.hasMore) return

    const keyAtStart = queryKey(s0)
    const seeding = s0.items.length === 0
    inflightRef.current?.abort()
    const ac = new AbortController()
    inflightRef.current = ac
    dispatch({ type: 'LOAD_START', seeding })

    let page: { galleries: EhGallery[]; cursor: Cursor; hasMore: boolean; total: number | null }
    try {
      page = await fetchPage(buildParams(s0), ac.signal)
    } catch (err) {
      if (ac.signal.aborted) return
      dispatch({ type: 'LOAD_ERROR', error: err instanceof Error ? err.message : 'failed' })
      return
    }

    if (ac.signal.aborted || queryKey(stateRef.current) !== keyAtStart) return

    let { cursor, hasMore } = page
    // A page that yields nothing new AND leaves the cursor where it was would just
    // refetch itself forever — treat it as the end. (Genuinely overlapping pages that
    // still advance the cursor keep hasMore, and the grid retries from the new cursor.)
    const seen = new Set(s0.items.map((g) => g.gid))
    const freshCount = page.galleries.filter((g) => !seen.has(g.gid)).length
    if (
      freshCount === 0 &&
      hasMore &&
      (cursor == null || JSON.stringify(cursor) === JSON.stringify(s0.cursor))
    ) {
      hasMore = false
      cursor = null
    }

    dispatch(
      seeding
        ? { type: 'SEED', items: page.galleries, total: page.total, cursor, hasMore }
        : { type: 'APPEND', items: page.galleries, cursor, hasMore },
    )
  }, [fetchPage])

  // Last scroll position produced by the USER (scroll events / explicit calls).
  // The unmount write must use this instead of live window.scrollY: on a push
  // navigation Next resets the window scroll in the new page's layout phase,
  // and React runs this page's passive unmount cleanup after that — reading
  // window.scrollY there would bank 0 and lose the position.
  const lastScrollYRef = useRef(0)

  // Bank the current view (buffer/cursor/scroll) into the per-identity snapshot
  // store. Used both by the lifecycle persistence below and by identity switches.
  const persistView = useCallback((s: EhBrowseState, scrollYOverride?: number) => {
    if (typeof window === 'undefined' || s.items.length === 0) return
    const scrollY = scrollYOverride ?? window.scrollY
    const prev = sessionStorage.getItem(SNAPSHOT_KEY)
    try {
      sessionStorage.setItem(SNAPSHOT_KEY, serializeSnapshot({ ...s, scrollY }, prev))
    } catch {
      // Quota fallback must reset cursor and scroll together with the buffer.
      // Keeping a late cursor beside an empty item list would skip results.
      try {
        sessionStorage.setItem(
          SNAPSHOT_KEY,
          serializeSnapshot({
            ...s,
            items: [],
            total: null,
            cursor: null,
            hasMore: true,
            scrollY: 0,
          }),
        )
      } catch {
        /* give up silently */
      }
    }
  }, [])

  // Identity-changing dispatch: bank the outgoing view first, then bring the
  // incoming identity's banked view back (RESTORE) instead of reseeding from
  // page 1 — this is what keeps buffer + scroll across in-page tab switches.
  // Multi-action form folds compound updates (e.g. commitQuery = SET_TAB +
  // COMMIT_QUERY) so the restore lookup targets the FINAL identity.
  const dispatchIdentityChange = useCallback(
    (...batch: Action[]) => {
      const s0 = stateRef.current
      const next = batch.reduce(reducer, s0)
      const nextKey = queryKey(next)
      const identityChanged = nextKey !== queryKey(s0)
      if (identityChanged) persistView(s0)
      for (const a of batch) dispatch(a)
      if (!identityChanged || typeof window === 'undefined') return
      const snap = parseSnapshot(sessionStorage.getItem(SNAPSHOT_KEY), nextKey)
      if (snap) dispatch({ type: 'RESTORE', snapshot: snap })
    },
    [persistView],
  )

  const actions = useMemo(
    () => ({
      setTab: (tab: Tab) => dispatchIdentityChange({ type: 'SET_TAB', tab }),
      commitQuery: (query: string) =>
        dispatchIdentityChange({ type: 'SET_TAB', tab: 'search' }, { type: 'COMMIT_QUERY', query }),
      setFilter: (patch: Partial<Filters>) => dispatchIdentityChange({ type: 'SET_FILTER', patch }),
      applyIdentity: (identity: Pick<EhBrowseState, 'tab' | 'query' | 'filters'>) =>
        dispatchIdentityChange({ type: 'APPLY_IDENTITY', identity }),
      showExternalResults: (items: EhGallery[], total: number) => {
        dispatchIdentityChange(
          { type: 'SET_TAB', tab: 'search' },
          { type: 'COMMIT_QUERY', query: '' },
        )
        dispatch({ type: 'SEED', items, total, cursor: null, hasMore: false })
      },
      setScroll: (scrollY: number) => dispatch({ type: 'SET_SCROLL', scrollY }),
      reset: () => dispatch({ type: 'RESET' }),
    }),
    [dispatchIdentityChange],
  )

  // ── URL sync: identity → URL. View (buffer/cursor/scroll) never goes in the URL.
  const identityKey = useMemo(
    () => identityToUrlParams(state).toString(),
    // Only the identity fields matter; recomputing on view (items/scroll) changes is wasteful.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [state.tab, state.query, state.filters],
  )
  const firstUrlSync = useRef(true)
  useEffect(() => {
    if (firstUrlSync.current) {
      firstUrlSync.current = false
      return
    }
    router.replace(identityKey ? `/e-hentai?${identityKey}` : '/e-hentai', { scroll: false })
  }, [identityKey, router])

  // React to an externally-cleared URL (e.g. tapping the nav link / double-tap reset
  // navigates to bare /e-hentai while the page stays mounted): reset to the home tab
  // and drop the snapshot. Guarded so our own popular-default URL writes don't loop.
  const searchStr = searchParams.toString()
  useEffect(() => {
    if (searchStr !== '') return
    if (queryKey(stateRef.current) === queryKey(initialState)) return
    if (typeof window !== 'undefined') sessionStorage.removeItem(SNAPSHOT_KEY)
    dispatch({ type: 'RESET' })
  }, [searchStr])

  // ── Snapshot persistence: continuous scroll capture + write on every exit.
  // MUST be a layout effect: on a push navigation Next resets window scroll in
  // the incoming page's layout phase, and the reset's scroll event fires in the
  // browser's rendering step — usually BEFORE React's passive cleanups flush.
  // With a passive effect the reset event would hit the still-attached listener
  // and poison lastScrollYRef with 0 (intermittently — it's a race). Layout
  // cleanups of a removed tree run in the mutation phase, strictly before the
  // incoming page's layout effects, so the listener is detached before the
  // reset can happen at all.
  useIsomorphicLayoutEffect(() => {
    if (typeof window === 'undefined') return
    // Init to 0, not live scrollY: this runs before the router's own scroll
    // handling for the new page, so window.scrollY may still be the PREVIOUS
    // page's position. Real positions arrive via scroll events (user scrolling,
    // our restore's scrollTo, or the browser's popstate restoration).
    lastScrollYRef.current = 0
    const write = () => persistView(stateRef.current)
    let persistTimer: ReturnType<typeof setTimeout> | undefined
    const onScroll = () => {
      lastScrollYRef.current = window.scrollY
      clearTimeout(persistTimer)
      persistTimer = setTimeout(write, 250)
    }
    const onHide = () => {
      if (document.visibilityState === 'hidden') {
        clearTimeout(persistTimer)
        write()
      }
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('pagehide', write)
    document.addEventListener('visibilitychange', onHide)
    return () => {
      // Bank the last USER position, never live scrollY — see effect comment.
      persistView(stateRef.current, lastScrollYRef.current)
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('pagehide', write)
      document.removeEventListener('visibilitychange', onHide)
      clearTimeout(persistTimer)
    }
  }, [persistView])

  return { state, dispatch: dispatch as React.Dispatch<Action>, actions, loadMore, favCategories }
}
