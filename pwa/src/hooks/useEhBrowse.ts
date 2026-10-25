'use client'

import { useCallback, useEffect, useLayoutEffect, useMemo, useReducer, useRef } from 'react'
import { useSearchParams } from 'next/navigation'
import {
  buildParamsFromIdentity,
  EH_PAGE_SIZE,
  identityToUrlParams,
  initialState,
  parseSnapshot,
  parseUrlToIdentity,
  queryKey,
  reducer,
  type Action,
  type Cursor,
  type EhBrowseState,
  type Filters,
  type Tab,
} from '@/lib/ehBrowseState'
import {
  canonicalEhIdentity,
  ehentaiBrowseAdapter,
  isEhFavCategoryMeta,
  isEhGallery,
} from '@/lib/browse/ehentai'
import { commitBrowseUrl, type BrowseHistoryMode } from '@/lib/browse/browseHistory'
import { createBrowseSnapshotStore, type BrowseSnapshotScope } from '@/lib/browse/snapshotStore'
import { getBrowseTabId } from '@/lib/browse/tabScope'
import { useBrowseSession } from '@/hooks/useBrowseSession'
import { useBrowseTabScope } from '@/hooks/useBrowseTabScope'
import { api } from '@/lib/api'
import type { EhFavCategory, EhGallery } from '@/lib/types'

const LEGACY_SNAPSHOT_KEY = 'eh_browse_snapshot'
const UNSCOPED_PARTITION_USER_ID = 'unscoped'
const IMAGE_SESSION_TTL_MS = 12 * 60 * 60 * 1000
const useIsomorphicLayoutEffect = typeof window === 'undefined' ? useEffect : useLayoutEffect

class MemoryStorage implements Storage {
  private values = new Map<string, string>()
  get length() {
    return this.values.size
  }
  clear() {
    this.values.clear()
  }
  getItem(key: string) {
    return this.values.get(key) ?? null
  }
  key(index: number) {
    return [...this.values.keys()][index] ?? null
  }
  removeItem(key: string) {
    this.values.delete(key)
  }
  setItem(key: string, value: string) {
    this.values.set(key, value)
  }
}

const serverStorage = new MemoryStorage()

function initFromUrl(search: string): EhBrowseState {
  const params = new URLSearchParams(search)
  return {
    ...initialState,
    ...parseUrlToIdentity(params),
    ephemeralSession: params.get('image_session'),
  }
}

function isValidEhCursor(value: unknown): boolean {
  if (!value || typeof value !== 'object') return false
  const cursor = value as Record<string, unknown>
  return (
    (cursor.kind === 'gid' &&
      typeof cursor.nextGid === 'number' &&
      Number.isInteger(cursor.nextGid) &&
      cursor.nextGid > 0) ||
    (cursor.kind === 'fav' && typeof cursor.next === 'string' && cursor.next.length > 0) ||
    (cursor.kind === 'page' &&
      typeof cursor.page === 'number' &&
      Number.isInteger(cursor.page) &&
      cursor.page >= 0)
  )
}

export type EhBrowseScope = { userId?: string; tabId?: string }
export type EhHistoryMode = BrowseHistoryMode

/** Which identity changes are worth a history entry.
 *
 *  A surface (Popular, Latest, a query search, Favorites, Toplist, image
 *  results) is a place the user navigated to, so it must be reachable by back:
 *  the browse list has no back FAB, and on mobile the edge swipe is the only
 *  back affordance, so collapsing popular -> favorites into one entry means
 *  backing out of E-Hentai entirely instead of stepping back a surface.
 *
 *  The comparison is on the canonical surface, not on `tab`: Latest and a query
 *  search both live on `tab: 'search'` but are different result sets, and
 *  treating them as one made Popular -> Latest -> "foo" overwrite the Latest
 *  entry.
 *
 *  Filters inside a surface are not places. Their controls stay on screen, and
 *  banking an entry per favourite-category pill or per advanced-search checkbox
 *  would make leaving the section take one swipe per pill the user touched. */
function historyModeFor(previous: EhBrowseState, next: EhBrowseState): EhHistoryMode {
  return canonicalEhIdentity(previous).surface === canonicalEhIdentity(next).surface
    ? 'replace'
    : 'push'
}

export function useEhBrowse(scopeInput?: EhBrowseScope) {
  const searchParams = useSearchParams()
  const browserStorage = typeof window === 'undefined' ? serverStorage : sessionStorage
  const implicitDefaultScope = scopeInput === undefined
  // Callers that supply no scope share one partition. The page always passes
  // the authenticated user, so this is a harness affordance — named, not
  // "default", so an unscoped partition is recognizable if it ever reaches a
  // real browser instead of silently reading as a legitimate user id.
  const resolvedUserId = implicitDefaultScope ? UNSCOPED_PARTITION_USER_ID : scopeInput.userId
  const prerequisitesReady = typeof resolvedUserId === 'string' && resolvedUserId.length > 0
  const storage = useMemo<Storage>(
    () => (prerequisitesReady ? browserStorage : new MemoryStorage()),
    [browserStorage, prerequisitesReady],
  )
  const [identityState, identityDispatch] = useReducer(
    reducer,
    searchParams.toString(),
    initFromUrl,
  )
  const identityStateRef = useRef(identityState)
  useIsomorphicLayoutEffect(() => {
    identityStateRef.current = identityState
  })

  const requestedTabId =
    scopeInput?.tabId ?? (implicitDefaultScope ? getBrowseTabId(browserStorage) : undefined)
  const tabScope = useBrowseTabScope({
    storage: browserStorage,
    enabled: prerequisitesReady,
    requestedTabId,
  })
  const scopeReady = prerequisitesReady && tabScope.ready
  const tabId = tabScope.tabId
  const scope = useMemo<BrowseSnapshotScope>(
    () => ({
      userId: resolvedUserId || 'pending',
      tabId,
      sourceId: ehentaiBrowseAdapter.sourceId,
      schemaVersion: ehentaiBrowseAdapter.schemaVersion,
    }),
    [resolvedUserId, tabId],
  )
  const canonicalIdentity = canonicalEhIdentity(identityState)
  const canonicalKey = queryKey(identityState)

  const fetchPage = useCallback(
    async (identity: typeof canonicalIdentity, cursor: Cursor, signal: AbortSignal) => {
      // Defensive only: the kernel does not issue requests while `ready` is
      // false. If one ever slipped through, committing a fabricated empty page
      // as a real result would show "No results" and stop pagination
      // (hasMore false), so fail loudly instead.
      if (!scopeReady) throw new Error('E-Hentai browse scope is not ready')
      const plan = buildParamsFromIdentity(identity, cursor)
      // The kernel's total is number | null. A source payload that omits the
      // field must degrade to "unknown", never to undefined: consumers guard
      // on null and would otherwise dereference it.
      if (plan.kind === 'search') {
        const response = await api.eh.search(plan.args, { signal })
        return {
          items: response.galleries,
          cursor:
            response.next_gid != null ? ({ kind: 'gid', nextGid: response.next_gid } as Cursor) : null,
          hasMore: response.next_gid != null,
          total: response.total ?? null,
        }
      }
      if (plan.kind === 'toplist') {
        const response = await api.eh.getToplist(plan.args, { signal })
        const hasMore = response.galleries.length >= EH_PAGE_SIZE
        return {
          items: response.galleries,
          cursor: hasMore ? ({ kind: 'page', page: plan.args.page + 1 } as Cursor) : null,
          hasMore,
          total: response.total ?? null,
        }
      }
      if (plan.kind === 'popular') {
        const response = await api.eh.getPopular({ signal })
        return {
          items: response.galleries,
          cursor: null,
          hasMore: false,
          total: response.total ?? null,
        }
      }
      const response = await api.eh.getFavorites(plan.args, { signal })
      return {
        items: response.galleries,
        cursor:
          response.has_next && response.next_cursor
            ? ({ kind: 'fav', next: response.next_cursor } as Cursor)
            : null,
        hasMore: response.has_next,
        total: response.total ?? null,
        meta: response.categories ?? [],
      }
    },
    [scopeReady],
  )
  const adapter = useMemo(
    () => ({
      getItemId: ehentaiBrowseAdapter.getItemKey,
      fetchPage,
      isReplayableIdentity: (identity: typeof canonicalIdentity) => identity.surface !== 'image-search',
      validateItem: isEhGallery,
      validateMeta: isEhFavCategoryMeta,
      validateCursor: isValidEhCursor,
    }),
    [fetchPage],
  )
  const retention = useMemo(
    () =>
      identityState.ephemeralSession
        ? { replayable: false, ttlMs: IMAGE_SESSION_TTL_MS }
        : undefined,
    [identityState.ephemeralSession],
  )
  const scopedStore = useMemo(
    () =>
      createBrowseSnapshotStore<EhGallery, Cursor>({
        storage,
        scope,
        validateCursor: isValidEhCursor,
        validateItem: isEhGallery,
        validateMeta: isEhFavCategoryMeta,
      }),
    [scope, storage],
  )

  // Compatibility is a destructive, per-tab/schema handoff. The coordinator
  // runs it during commit immediately before restoring the scoped partition.
  const migrateLegacy = useCallback(() => {
    if (!scopeReady || identityState.ephemeralSession) return
    const migrationMarker = `eh_browse_migrated_v${ehentaiBrowseAdapter.schemaVersion}:${tabId}`
    if (browserStorage.getItem(migrationMarker) === '1') return
    const legacy = parseSnapshot(browserStorage.getItem(LEGACY_SNAPSHOT_KEY), canonicalKey)
    if (legacy) {
      const legacyScrollY = legacy.scrollY ?? 0
      scopedStore.save(canonicalKey, {
        pages: [legacy.items ?? []],
        cursor: legacy.cursor ?? null,
        hasMore: legacy.hasMore ?? true,
        total: legacy.total ?? null,
        anchor:
          legacy.anchor ??
          (legacyScrollY > 0 ? { itemId: null, offset: 0, scrollY: legacyScrollY } : null),
        layout: legacy.layout ?? null,
      })
    }
    browserStorage.removeItem(LEGACY_SNAPSHOT_KEY)
    browserStorage.setItem(migrationMarker, '1')
  }, [browserStorage, canonicalKey, identityState.ephemeralSession, scopeReady, scopedStore, tabId])

  const session = useBrowseSession<EhGallery, Cursor, typeof canonicalIdentity>({
    identity: canonicalIdentity,
    identityKey: canonicalKey,
    adapter,
    scope,
    storage,
    retention,
    ready: scopeReady,
    autoLoad: false,
    preHydrate: migrateLegacy,
  })
  const cancelPending = session.cancelPending
  const sessionCheckpoint = session.checkpoint
  const updateSessionView = session.updateView
  const replacePage = session.replacePage
  const liveViewRef = useRef<{
    anchor: EhBrowseState['anchor']
    layout: EhBrowseState['layout']
  } | null>(null)
  const lastRestoreKeyRef = useRef<string | null>(null)
  const liveViewIdentityRef = useRef(session.state.identityKey)
  const restoreInstruction = session.restoreInstruction
  useIsomorphicLayoutEffect(() => {
    if (liveViewIdentityRef.current !== session.state.identityKey) {
      liveViewIdentityRef.current = session.state.identityKey
      liveViewRef.current = null
      lastRestoreKeyRef.current = null
    }
    if (restoreInstruction && restoreInstruction.key !== lastRestoreKeyRef.current) {
      lastRestoreKeyRef.current = restoreInstruction.key
      liveViewRef.current =
        restoreInstruction.target.kind === 'view' ? restoreInstruction.target.view : null
    }
  }, [restoreInstruction, session.state.identityKey])
  const restoredView =
    restoreInstruction?.target.kind === 'view' ? restoreInstruction.target.view : null

  const returnedState: EhBrowseState = {
    ...identityState,
    items: session.state.items,
    cursor: session.state.cursor,
    hasMore: session.state.hasMore,
    total: session.state.total,
    status: session.state.terminal
      ? 'expired'
      : session.state.status === 'loading'
        ? session.state.items.length === 0
          ? 'seeding'
          : 'loading'
        : session.state.status,
    error: session.state.error?.message ?? null,
    anchor: restoredView?.anchor ?? identityState.anchor,
    layout: restoredView?.layout ?? identityState.layout,
    scrollY: restoredView?.anchor?.scrollY ?? identityState.scrollY,
  }
  const stateRef = useRef(returnedState)
  useIsomorphicLayoutEffect(() => {
    stateRef.current = returnedState
  })

  // Identity key of the history entry this page instance pushed and is still
  // sitting on. Lets "Clear search" step back over an entry it banked itself
  // instead of stacking a duplicate of the surface the user came from. Null
  // whenever the current entry's origin is unknown (deep link, reload, history
  // moved by the browser).
  const pushedEntryKeyRef = useRef<string | null>(null)
  const writeHistory = useCallback(
    (next: EhBrowseState, previous: EhBrowseState, historyMode?: EhHistoryMode) => {
      const mode = historyMode ?? historyModeFor(previous, next)
      const params = identityToUrlParams(next).toString()
      commitBrowseUrl(params ? `/e-hentai?${params}` : '/e-hentai', mode)
      if (mode === 'push' || pushedEntryKeyRef.current === queryKey(previous)) {
        // A replace inside the pushed entry keeps it pushed under its new key.
        pushedEntryKeyRef.current = queryKey(next)
      } else {
        pushedEntryKeyRef.current = null
      }
    },
    [],
  )

  // Save the view of the identity being left. `scrollY` is read live here, at
  // the moment the user acts, because Next's router resets it before unmount
  // cleanups run (FE-T12).
  const checkpointCurrentView = useCallback(() => {
    const current = stateRef.current
    const liveView = liveViewRef.current
    const liveAnchor = {
      itemId: liveView?.anchor?.itemId ?? current.anchor?.itemId ?? null,
      offset: liveView?.anchor?.offset ?? current.anchor?.offset ?? 0,
      scrollY: window.scrollY,
    }
    sessionCheckpoint({ anchor: liveAnchor, layout: liveView?.layout ?? current.layout }, retention)
  }, [retention, sessionCheckpoint])

  const commitIdentity = useCallback(
    (actions: Action[], historyMode?: EhHistoryMode) => {
      const previous = identityStateRef.current
      let preview = previous
      for (const action of actions) preview = reducer(preview, action)
      if (queryKey(preview) === queryKey(previous)) {
        for (const action of actions) identityDispatch(action)
        // Panel expansion is excluded from the identity key, but it is still
        // serialized into the URL (`adv_open`). Without this write the entry
        // keeps whatever the panel looked like when it was created, so after
        // reader -> back the panel is open or closed depending on click history.
        if (identityToUrlParams(preview).toString() !== identityToUrlParams(previous).toString()) {
          writeHistory(preview, previous, 'replace')
        }
        return
      }
      checkpointCurrentView()
      cancelPending()
      for (const action of actions) identityDispatch(action)
      writeHistory(preview, previous, historyMode)
    },
    [cancelPending, checkpointCurrentView, writeHistory],
  )

  const imageSessionCounterRef = useRef(0)
  const actions = useMemo(
    () => ({
      commitIdentity: (
        identity: Pick<EhBrowseState, 'tab' | 'query' | 'filters'>,
        historyMode: EhHistoryMode,
      ) => commitIdentity([{ type: 'APPLY_IDENTITY', identity }], historyMode),
      setTab: (tab: Tab, historyMode?: EhHistoryMode) =>
        commitIdentity([{ type: 'SET_TAB', tab }], historyMode),
      commitQuery: (query: string, historyMode?: EhHistoryMode) =>
        commitIdentity(
          [
            { type: 'SET_TAB', tab: 'search' },
            { type: 'COMMIT_QUERY', query },
          ],
          historyMode,
        ),
      setFilter: (patch: Partial<Filters>, historyMode?: EhHistoryMode) =>
        commitIdentity([{ type: 'SET_FILTER', patch }], historyMode),
      applyIdentity: (
        identity: Pick<EhBrowseState, 'tab' | 'query' | 'filters'>,
        historyMode?: EhHistoryMode,
      ) => commitIdentity([{ type: 'APPLY_IDENTITY', identity }], historyMode),
      showExternalResults: (items: EhGallery[], total: number) => {
        cancelPending()
        const imageSession = `${Date.now()}-${++imageSessionCounterRef.current}`
        const next = reducer(identityStateRef.current, {
          type: 'SHOW_EXTERNAL_RESULTS',
          session: imageSession,
          items,
          total,
        })
        scopedStore.save(
          queryKey(next),
          {
            pages: [items],
            cursor: null,
            hasMore: false,
            total,
            anchor: null,
            layout: null,
          },
          { replayable: false, ttlMs: IMAGE_SESSION_TTL_MS },
        )
        const previous = identityStateRef.current
        // Results are a new surface like any other: replacing the entry the
        // user came from made back leave E-Hentai instead of returning to it.
        if (historyModeFor(previous, next) === 'push') checkpointCurrentView()
        identityDispatch({ type: 'SHOW_EXTERNAL_RESULTS', session: imageSession, items, total })
        writeHistory(next, previous)
      },
      setScroll: (scrollY: number) => {
        const current = liveViewRef.current
        const view = {
          anchor: current?.anchor
            ? { ...current.anchor, scrollY }
            : scrollY > 0
              ? { itemId: null, offset: 0, scrollY }
              : null,
          layout: current?.layout ?? stateRef.current.layout,
        }
        liveViewRef.current = view
        updateSessionView(view)
      },
      setAnchor: (anchor: EhBrowseState['anchor']) => {
        const view = { anchor, layout: liveViewRef.current?.layout ?? stateRef.current.layout }
        liveViewRef.current = view
        updateSessionView(view)
      },
      setLayout: (layout: EhBrowseState['layout']) => {
        const view = { anchor: liveViewRef.current?.anchor ?? stateRef.current.anchor, layout }
        liveViewRef.current = view
        updateSessionView(view)
      },
      checkpoint: (anchor?: EhBrowseState['anchor'], layout?: EhBrowseState['layout']) => {
        const current = stateRef.current
        const liveView = liveViewRef.current
        const view = {
          anchor:
            anchor === undefined
              ? liveView?.anchor ??
                current.anchor ??
                (current.scrollY > 0
                  ? { itemId: null, offset: 0, scrollY: current.scrollY }
                  : null)
              : anchor,
          layout: layout === undefined ? liveView?.layout ?? current.layout : layout,
        }
        liveViewRef.current = view
        sessionCheckpoint(view, retention)
      },
      reset: () => commitIdentity([{ type: 'RESET' }], 'replace'),
      /** Leave a query search. When this page pushed the search entry on top of
       *  another surface, step back over it: popstate restores that surface and
       *  its snapshot, and history does not grow a duplicate entry (replacing
       *  instead left [popular, popular], so the first back did nothing). With no
       *  such entry (deep link, reload) fall back to resetting in place. */
      clearSearch: () => {
        if (pushedEntryKeyRef.current === queryKey(identityStateRef.current)) {
          pushedEntryKeyRef.current = null
          window.history.back()
          return
        }
        commitIdentity([{ type: 'RESET' }], 'replace')
      },
    }),
    [
      cancelPending,
      checkpointCurrentView,
      commitIdentity,
      retention,
      scopedStore,
      sessionCheckpoint,
      updateSessionView,
      writeHistory,
    ],
  )

  const compatibilityDispatch = useCallback(
    (action: Action) => {
      if (action.type === 'SEED') {
        replacePage({
          items: action.items,
          cursor: action.cursor,
          hasMore: action.hasMore,
          total: action.total,
        })
        return
      }
      if (action.type === 'RESTORE') {
        replacePage({
          items: action.snapshot.items ?? [],
          cursor: action.snapshot.cursor ?? null,
          hasMore: action.snapshot.hasMore ?? true,
          total: action.snapshot.total ?? null,
        })
        return
      }
      identityDispatch(action)
    },
    [replacePage],
  )

  const searchString = searchParams.toString()
  useEffect(() => {
    const params = new URLSearchParams(searchString)
    const identity = {
      ...parseUrlToIdentity(params),
      ephemeralSession: params.get('image_session'),
    }
    const next = { ...identityStateRef.current, ...identity }
    if (queryKey(identityStateRef.current) !== queryKey(next)) {
      // The URL moved without this page writing it (browser back/forward, a
      // deep link): whichever entry it is on now was not pushed by us.
      pushedEntryKeyRef.current = null
      cancelPending()
      identityDispatch({ type: 'APPLY_IDENTITY', identity })
    }
  }, [cancelPending, searchString])

  return {
    state: returnedState,
    dispatch: compatibilityDispatch as React.Dispatch<Action>,
    actions,
    loadMore: session.loadMore,
    restoreInstruction,
    acknowledgeRestore: session.acknowledgeRestore,
    favCategories: (Array.isArray(session.state.meta) ? session.state.meta : []) as EhFavCategory[],
  }
}
