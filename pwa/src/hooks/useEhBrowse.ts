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
export type EhHistoryMode = 'push' | 'replace'

function updateEhBrowseUrl(url: string, historyMode: EhHistoryMode): void {
  // These are same-page identity transitions. Going through Next's router makes
  // it fetch an RSC payload even though the local reducer already owns the view,
  // and iOS standalone Safari can subsequently fall back to a document
  // navigation with an empty query string. Native History API calls are
  // integrated with the App Router and keep useSearchParams/popstate in sync
  // without introducing that RSC navigation window.
  const state = window.history.state
  if (historyMode === 'push') window.history.pushState(state, '', url)
  else window.history.replaceState(state, '', url)
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
      if (!scopeReady) {
        return { items: [], cursor: null, hasMore: false, total: 0 }
      }
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

  const commitIdentity = useCallback(
    (actions: Action[], historyMode: EhHistoryMode) => {
      let preview = identityStateRef.current
      for (const action of actions) preview = reducer(preview, action)
      if (queryKey(preview) === queryKey(identityStateRef.current)) {
        for (const action of actions) identityDispatch(action)
        return
      }
      const current = stateRef.current
      const liveView = liveViewRef.current
      const liveAnchor = {
        itemId: liveView?.anchor?.itemId ?? current.anchor?.itemId ?? null,
        offset: liveView?.anchor?.offset ?? current.anchor?.offset ?? 0,
        scrollY: window.scrollY,
      }
      sessionCheckpoint({ anchor: liveAnchor, layout: liveView?.layout ?? current.layout }, retention)
      cancelPending()
      for (const action of actions) identityDispatch(action)
      const params = identityToUrlParams(preview).toString()
      const url = params ? `/e-hentai?${params}` : '/e-hentai'
      updateEhBrowseUrl(url, historyMode)
    },
    [cancelPending, retention, sessionCheckpoint],
  )

  const imageSessionCounterRef = useRef(0)
  const actions = useMemo(
    () => ({
      commitIdentity: (
        identity: Pick<EhBrowseState, 'tab' | 'query' | 'filters'>,
        historyMode: EhHistoryMode,
      ) => commitIdentity([{ type: 'APPLY_IDENTITY', identity }], historyMode),
      setTab: (tab: Tab, historyMode: EhHistoryMode = 'replace') =>
        commitIdentity([{ type: 'SET_TAB', tab }], historyMode),
      commitQuery: (query: string, historyMode: EhHistoryMode = 'replace') =>
        commitIdentity(
          [
            { type: 'SET_TAB', tab: 'search' },
            { type: 'COMMIT_QUERY', query },
          ],
          historyMode,
        ),
      setFilter: (patch: Partial<Filters>, historyMode: EhHistoryMode = 'replace') =>
        commitIdentity([{ type: 'SET_FILTER', patch }], historyMode),
      applyIdentity: (
        identity: Pick<EhBrowseState, 'tab' | 'query' | 'filters'>,
        historyMode: EhHistoryMode = 'replace',
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
        identityDispatch({ type: 'SHOW_EXTERNAL_RESULTS', session: imageSession, items, total })
        const params = identityToUrlParams(next).toString()
        updateEhBrowseUrl(`/e-hentai?${params}`, 'replace')
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
    }),
    [cancelPending, commitIdentity, retention, scopedStore, sessionCheckpoint, updateSessionView],
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
