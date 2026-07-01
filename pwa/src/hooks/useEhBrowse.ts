'use client'

import { useReducer, useRef, useCallback, useMemo, useEffect, useState } from 'react'
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

  const stateRef = useRef(state)
  useEffect(() => {
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
    ): Promise<{ galleries: EhGallery[]; cursor: Cursor; hasMore: boolean; total: number | null }> => {
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

    // A completed fetch that advances the cursor but yields zero NEW items (after
    // gid-dedupe) would leave the buffer unchanged — and VirtualGrid only re-fires
    // onLoadMore when items.length grows, so the infinite scroll would wedge. EH
    // favorites are ordered by favourite-time while the cursor is gid-based, so
    // accumulated pages can fully overlap. Chain forward until we gather at least
    // one new item, hit the end, or the cursor can no longer advance.
    const seen = new Set(s0.items.map((g) => g.gid))
    const collected: EhGallery[] = []
    let cursor = s0.cursor
    let hasMore = s0.hasMore
    let total = s0.total
    const MAX_CHAINED = 10

    try {
      for (let i = 0; i < MAX_CHAINED; i++) {
        const page = await fetchPage(buildParams({ ...s0, cursor }), ac.signal)
        if (ac.signal.aborted || queryKey(stateRef.current) !== keyAtStart) return
        if (seeding && i === 0) total = page.total
        const fresh = page.galleries.filter((g) => !seen.has(g.gid))
        for (const g of fresh) seen.add(g.gid)
        collected.push(...fresh)
        const prevCursor = cursor
        cursor = page.cursor
        hasMore = page.hasMore
        if (fresh.length > 0 || !hasMore) break
        // Zero new items but more claimed: only keep chaining if the cursor actually
        // moved, otherwise we'd refetch the same page forever — treat as the end.
        if (cursor == null || JSON.stringify(cursor) === JSON.stringify(prevCursor)) {
          hasMore = false
          break
        }
      }
    } catch (err) {
      if (ac.signal.aborted) return
      dispatch({ type: 'LOAD_ERROR', error: err instanceof Error ? err.message : 'failed' })
      return
    }

    if (ac.signal.aborted || queryKey(stateRef.current) !== keyAtStart) return
    dispatch(
      seeding
        ? { type: 'SEED', items: collected, total, cursor, hasMore }
        : { type: 'APPEND', items: collected, cursor, hasMore },
    )
  }, [fetchPage])

  const actions = useMemo(
    () => ({
      setTab: (tab: Tab) => dispatch({ type: 'SET_TAB', tab }),
      commitQuery: (query: string) => {
        dispatch({ type: 'SET_TAB', tab: 'search' })
        dispatch({ type: 'COMMIT_QUERY', query })
      },
      setFilter: (patch: Partial<Filters>) => dispatch({ type: 'SET_FILTER', patch }),
      setScroll: (scrollY: number) => dispatch({ type: 'SET_SCROLL', scrollY }),
      reset: () => dispatch({ type: 'RESET' }),
    }),
    [],
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
  useEffect(() => {
    if (typeof window === 'undefined') return
    const write = () => {
      const s = stateRef.current
      if (s.items.length === 0) return
      try {
        sessionStorage.setItem(SNAPSHOT_KEY, serializeSnapshot({ ...s, scrollY: window.scrollY }))
      } catch {
        // quota — retry without the buffer so cursor/scroll still survive
        try {
          sessionStorage.setItem(
            SNAPSHOT_KEY,
            serializeSnapshot({ ...s, items: [], scrollY: window.scrollY }),
          )
        } catch {
          /* give up silently */
        }
      }
    }
    let raf = 0
    const onScroll = () => {
      if (raf) return
      raf = requestAnimationFrame(() => {
        raf = 0
        write()
      })
    }
    const onHide = () => {
      if (document.visibilityState === 'hidden') write()
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('pagehide', write)
    document.addEventListener('visibilitychange', onHide)
    return () => {
      write()
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('pagehide', write)
      document.removeEventListener('visibilitychange', onHide)
      if (raf) cancelAnimationFrame(raf)
    }
  }, [])

  return { state, dispatch: dispatch as React.Dispatch<Action>, actions, loadMore, favCategories }
}
