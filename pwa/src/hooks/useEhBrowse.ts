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
} from '@/lib/ehBrowseState'
import { api } from '@/lib/api'
import type { EhSearchResult, EhFavoritesResult, EhFavCategory } from '@/lib/types'

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

  const loadMore = useCallback(async () => {
    const s = stateRef.current
    if (s.status === 'seeding' || s.status === 'loading') return
    if (s.items.length > 0 && !s.hasMore) return

    const keyAtStart = queryKey(s)
    const seeding = s.items.length === 0
    inflightRef.current?.abort()
    const ac = new AbortController()
    inflightRef.current = ac
    dispatch({ type: 'LOAD_START', seeding })

    const plan = buildParams(s)
    try {
      if (plan.kind === 'search' || plan.kind === 'popular' || plan.kind === 'toplist') {
        let res: EhSearchResult
        let cursor: Cursor
        let hasMore: boolean
        if (plan.kind === 'search') {
          res = await api.eh.search(plan.args, { signal: ac.signal })
          cursor = res.next_gid != null ? { kind: 'gid', nextGid: res.next_gid } : null
          hasMore = res.next_gid != null
        } else if (plan.kind === 'toplist') {
          res = await api.eh.getToplist(plan.args, { signal: ac.signal })
          hasMore = res.galleries.length >= EH_PAGE_SIZE
          cursor = hasMore ? { kind: 'page', page: plan.args.page + 1 } : null
        } else {
          res = await api.eh.getPopular({ signal: ac.signal })
          cursor = null
          hasMore = false
        }
        if (ac.signal.aborted || queryKey(stateRef.current) !== keyAtStart) return
        dispatch(
          seeding
            ? { type: 'SEED', items: res.galleries, total: res.total, cursor, hasMore }
            : { type: 'APPEND', items: res.galleries, cursor, hasMore },
        )
      } else {
        const res: EhFavoritesResult = await api.eh.getFavorites(plan.args, { signal: ac.signal })
        if (ac.signal.aborted || queryKey(stateRef.current) !== keyAtStart) return
        if (res.categories?.length) setFavCategories(res.categories)
        const cursor: Cursor =
          res.has_next && res.next_cursor ? { kind: 'fav', next: res.next_cursor } : null
        dispatch(
          seeding
            ? { type: 'SEED', items: res.galleries, total: res.total, cursor, hasMore: res.has_next }
            : { type: 'APPEND', items: res.galleries, cursor, hasMore: res.has_next },
        )
      }
    } catch (err) {
      if (ac.signal.aborted) return
      dispatch({ type: 'LOAD_ERROR', error: err instanceof Error ? err.message : 'failed' })
    }
  }, [])

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
