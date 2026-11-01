'use client'

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useReducer,
  useRef,
  useState,
} from 'react'
import {
  createBrowseReducer,
  createBrowseState,
  type BrowseHydration,
  type BrowsePageResult,
  type BrowseRequestPlan,
  type BrowseState,
} from '@/lib/browse/reducer'
import { canonicalIdentityKey } from '@/lib/browse/identity'
import { publishBrowseListPatch, subscribeBrowseListPatches } from '@/lib/browse/listPatches'
import type { BrowseListPatch } from '@/lib/browse/patch'
import {
  createBrowseSnapshotStore,
  type BrowseLayoutSnapshot,
  type BrowseSnapshotSaveOptions,
  type BrowseSnapshotScope,
} from '@/lib/browse/snapshotStore'
import type { BrowseAnchor } from '@/lib/browse/anchor'

const useIsomorphicLayoutEffect = typeof window === 'undefined' ? useEffect : useLayoutEffect

type BrowseAdapter<Item, Cursor, Identity> = {
  getItemId: (item: Item) => string | number
  fetchPage: (
    identity: Identity,
    cursor: Cursor | null,
    signal: AbortSignal,
  ) => Promise<BrowsePageResult<Item, Cursor>>
  validateCursor?: (value: unknown) => boolean
  validateItem?: (value: unknown) => boolean
  validateMeta?: (value: unknown) => boolean
  isReplayableIdentity?: (identity: Identity) => boolean
}

type UseBrowseSessionOptions<Item, Cursor, Identity> = {
  identity: Identity
  identityKey: string
  adapter: BrowseAdapter<Item, Cursor, Identity>
  scope: BrowseSnapshotScope
  storage: Storage
  retention?: BrowseSnapshotSaveOptions
  ready?: boolean
  autoLoad?: boolean
  preHydrate?: () => void
}

type BrowseCheckpoint = {
  anchor: BrowseAnchor | null
  layout: BrowseLayoutSnapshot | null
}

export type BrowseRestoreInstruction = {
  key: string
  identityKey: string
  target:
    | { kind: 'view'; view: BrowseCheckpoint }
    | { kind: 'top' }
}

/**
 * The buffer state as published to consumers.
 *
 * `pending` marks the render window between the caller adopting a new
 * `identityKey` and the reducer committing it: identity-derived UI and
 * buffer-derived metadata are read in the same render body, so during that
 * window the buffer still belongs to the previous identity.
 */
export type BrowseSessionState<Item, Cursor> = BrowseState<Item, Cursor> & {
  pending: boolean
}

export type BrowseRefreshOptions = {
  /**
   * `'loaded'` (default) re-fetches every loaded page so a deep anchor
   * survives. `'first'` replaces the buffer with the first page only: one
   * request, for a refresh the user asked for at the top of the list.
   */
  depth?: 'loaded' | 'first'
}

export type BrowseSessionResult<Item, Cursor> = {
  state: BrowseSessionState<Item, Cursor>
  loadMore: () => Promise<void>
  refresh: (options?: BrowseRefreshOptions) => Promise<void>
  retry: () => Promise<void>
  checkpoint: (
    view: BrowseCheckpoint,
    retention?: BrowseSnapshotSaveOptions,
  ) => boolean
  updateView: (view: BrowseCheckpoint) => void
  restoreInstruction: BrowseRestoreInstruction | null
  acknowledgeRestore: (key: string) => void
  /** @deprecated Use restoreInstruction and acknowledgeRestore. */
  restoredView: BrowseCheckpoint | null
  replacePage: (
    page: BrowsePageResult<Item, Cursor>,
    view?: BrowseCheckpoint,
    retention?: BrowseSnapshotSaveOptions,
  ) => boolean
  cancelPending: () => void
  /**
   * Apply a user's change to one or more items (a bookmark, a favourite) to
   * this list, to the other saved lists of its partition and to any of them
   * mounted elsewhere. Use it instead of `refresh` for such changes.
   */
  patchItems: (patch: BrowseListPatch<Item>) => void
}

export function useBrowseSession<Item, Cursor, Identity>({
  identity,
  identityKey,
  adapter,
  scope,
  storage,
  retention,
  ready = true,
  autoLoad = true,
  preHydrate,
}: UseBrowseSessionOptions<Item, Cursor, Identity>): BrowseSessionResult<Item, Cursor> {
  const adapterRef = useRef(adapter)
  const identityRef = useRef(identity)
  const retentionRef = useRef(retention)
  const preHydrateRef = useRef(preHydrate)
  useLayoutEffect(() => {
    adapterRef.current = adapter
    identityRef.current = identity
    retentionRef.current = retention
    preHydrateRef.current = preHydrate
  }, [adapter, identity, preHydrate, retention])

  const reducer = useMemo(
    () => createBrowseReducer<Item, Cursor>(adapter.getItemId),
    [adapter.getItemId],
  )
  const [state, dispatch] = useReducer(reducer, identityKey, createBrowseState<Item, Cursor>)
  const stateRef = useRef(state)
  const readyRef = useRef(ready)
  useLayoutEffect(() => {
    stateRef.current = state
    readyRef.current = ready
  }, [ready, state])

  const stableScope = useMemo(
    () => ({
      userId: scope.userId,
      tabId: scope.tabId,
      sourceId: scope.sourceId,
      schemaVersion: scope.schemaVersion,
    }),
    [scope.schemaVersion, scope.sourceId, scope.tabId, scope.userId],
  )
  const store = useMemo(
    () =>
      createBrowseSnapshotStore<Item, Cursor>({
        storage,
        scope: stableScope,
        validateCursor: adapter.validateCursor,
        validateItem: adapter.validateItem,
        validateMeta: adapter.validateMeta,
      }),
    [adapter.validateCursor, adapter.validateItem, adapter.validateMeta, stableScope, storage],
  )
  const storeRef = useRef(store)
  const publishTargetRef = useRef({ storage, scope: stableScope })
  useLayoutEffect(() => {
    storeRef.current = store
    publishTargetRef.current = { storage, scope: stableScope }
  }, [stableScope, storage, store])

  const generationRef = useRef(0)
  const activeIdentityKeyRef = useRef(identityKey)
  const inflightRef = useRef<AbortController | null>(null)
  const requestInFlightRef = useRef(false)
  // Item patches that arrived while the request of `generation` was in
  // flight. That response may have been fetched before the change, so its
  // commit replays them (patches are idempotent).
  const inflightPatchesRef = useRef<{
    generation: number
    updates: Array<(item: Item) => Item | null>
  }>({ generation: 0, updates: [] })
  const liveViewRef = useRef<BrowseCheckpoint | null>(null)
  const restoreEpochRef = useRef(0)
  const restoreInstructionRef = useRef<BrowseRestoreInstruction | null>(null)
  const [restoreInstruction, setRestoreInstruction] =
    useState<BrowseRestoreInstruction | null>(null)

  const publishRestore = useCallback(
    (nextIdentityKey: string, target: BrowseRestoreInstruction['target']): void => {
      const instruction = {
        key: `${nextIdentityKey}:restore:${++restoreEpochRef.current}`,
        identityKey: nextIdentityKey,
        target,
      }
      restoreInstructionRef.current = instruction
      setRestoreInstruction(instruction)
    },
    [],
  )

  const clearRestore = useCallback((): void => {
    restoreInstructionRef.current = null
    setRestoreInstruction(null)
  }, [])

  const acknowledgeRestore = useCallback((key: string): void => {
    if (restoreInstructionRef.current?.key !== key) return
    restoreInstructionRef.current = null
    setRestoreInstruction(null)
  }, [])

  const saveState = useCallback(
    (
      currentStore: ReturnType<typeof createBrowseSnapshotStore<Item, Cursor>>,
      current: BrowseState<Item, Cursor>,
      view: BrowseCheckpoint,
      saveOptions?: BrowseSnapshotSaveOptions,
    ): boolean => {
      if (current.pages.length === 0) return false
      return currentStore.save(
        current.identityKey,
        {
          pages: current.pages,
          cursor: current.cursor,
          hasMore: current.hasMore,
          total: current.total,
          anchor: view.anchor,
          layout: view.layout,
          pageMeta: current.meta,
        },
        saveOptions,
      )
    },
    [],
  )

  const updateView = useCallback((view: BrowseCheckpoint): void => {
    liveViewRef.current = view
  }, [])

  const checkpoint = useCallback(
    (view: BrowseCheckpoint, saveOptions?: BrowseSnapshotSaveOptions): boolean => {
      updateView(view)
      return saveState(
        storeRef.current,
        stateRef.current,
        view,
        saveOptions ?? retentionRef.current,
      )
    },
    [saveState, updateView],
  )

  const requestPages = useCallback(
    async (
      request: BrowseRequestPlan<Cursor>,
      requestIdentity: Identity,
      requestIdentityKey: string,
    ): Promise<void> => {
      if (requestInFlightRef.current) return
      requestInFlightRef.current = true
      inflightRef.current?.abort()
      const controller = new AbortController()
      inflightRef.current = controller
      const generation = ++generationRef.current
      inflightPatchesRef.current = { generation, updates: [] }
      const replayPatchesFromFlight = () => {
        const pending = inflightPatchesRef.current
        if (pending.generation !== generation) return
        for (const update of pending.updates) {
          dispatch({ type: 'ITEMS_PATCHED', identityKey: requestIdentityKey, update })
        }
      }
      dispatch({ type: 'REQUEST_STARTED', generation, request })
      try {
        if (request.kind === 'refresh') {
          const pages: Item[][] = []
          let cursor: Cursor | null = null
          let lastPage: BrowsePageResult<Item, Cursor> | null = null
          let meta: unknown

          for (let pageIndex = 0; pageIndex < request.targetDepth; pageIndex += 1) {
            const page = await adapterRef.current.fetchPage(
              requestIdentity,
              cursor,
              controller.signal,
            )
            if (
              controller.signal.aborted ||
              generationRef.current !== generation ||
              activeIdentityKeyRef.current !== requestIdentityKey
            ) {
              return
            }
            pages.push(page.items)
            if (page.meta !== undefined) meta = page.meta
            lastPage = page

            if (!page.hasMore || page.cursor === null) break
            if (canonicalIdentityKey(cursor) === canonicalIdentityKey(page.cursor)) {
              lastPage = { ...page, hasMore: false }
              break
            }
            cursor = page.cursor
          }

          if (!lastPage) return
          const buffer: BrowseHydration<Item, Cursor> = {
            pages,
            cursor: lastPage.cursor,
            hasMore: lastPage.hasMore,
            total: lastPage.total,
            meta,
          }
          const currentView = liveViewRef.current
          if (currentView?.anchor) {
            const anchorId = currentView.anchor.itemId
            const anchorStillExists =
              anchorId !== null &&
              pages.some((page) =>
                page.some((item) => adapterRef.current.getItemId(item) === anchorId),
              )
            const nextView = {
              anchor: anchorStillExists ? currentView.anchor : null,
              layout: currentView.layout,
            }
            liveViewRef.current = nextView
            const pendingRestore = restoreInstructionRef.current
            if (
              pendingRestore?.identityKey === requestIdentityKey &&
              pendingRestore.target.kind === 'view'
            ) {
              const nextInstruction = {
                ...pendingRestore,
                target: { kind: 'view' as const, view: nextView },
              }
              restoreInstructionRef.current = nextInstruction
              setRestoreInstruction(nextInstruction)
            }
          }
          dispatch({
            type: 'BUFFER_SUCCEEDED',
            identityKey: requestIdentityKey,
            generation,
            buffer,
          })
          replayPatchesFromFlight()
        } else {
          const page = await adapterRef.current.fetchPage(
            requestIdentity,
            request.cursor,
            controller.signal,
          )
          if (
            controller.signal.aborted ||
            generationRef.current !== generation ||
            activeIdentityKeyRef.current !== requestIdentityKey
          ) {
            return
          }
          dispatch({
            type: 'PAGE_SUCCEEDED',
            identityKey: requestIdentityKey,
            generation,
            mode: request.kind === 'append' ? 'append' : 'replace',
            page,
          })
          replayPatchesFromFlight()
        }
      } catch (error) {
        if (controller.signal.aborted || generationRef.current !== generation) return
        dispatch({
          type: 'PAGE_FAILED',
          identityKey: requestIdentityKey,
          generation,
          error: error instanceof Error ? error : new Error('Browse request failed'),
          request,
        })
      } finally {
        if (inflightRef.current === controller) {
          inflightRef.current = null
          requestInFlightRef.current = false
        }
      }
    },
    [],
  )

  // Patches published for this partition — by this page's own cards through
  // patchItems, or by a detail page — reach the live buffer too. Subscribed in
  // a layout effect ahead of the restore below, so no publish can land between
  // reading the snapshot and listening.
  useIsomorphicLayoutEffect(() => {
    if (!ready) return
    return subscribeBrowseListPatches<Item>(storage, stableScope, (patch) => {
      const liveIdentityKey = activeIdentityKeyRef.current
      const update = (item: Item) => patch.updateItem(item, liveIdentityKey)
      dispatch({ type: 'ITEMS_PATCHED', identityKey: liveIdentityKey, update })
      if (requestInFlightRef.current) inflightPatchesRef.current.updates.push(update)
    })
  }, [ready, stableScope, storage])

  useIsomorphicLayoutEffect(() => {
    activeIdentityKeyRef.current = identityKey
    inflightRef.current?.abort()
    inflightRef.current = null
    requestInFlightRef.current = false
    const transitionGeneration = ++generationRef.current
    dispatch({ type: 'IDENTITY_CHANGED', identityKey, generation: transitionGeneration })

    if (!ready) {
      liveViewRef.current = null
      clearRestore()
      return () => {
        inflightRef.current?.abort()
        inflightRef.current = null
        requestInFlightRef.current = false
        generationRef.current += 1
      }
    }

    try {
      preHydrateRef.current?.()
    } catch {
      // Pre-hydration compatibility work is best effort. Restore treats
      // inaccessible storage as an empty partition.
    }
    const restored = store.restore(identityKey)
    if (restored.kind === 'snapshot') {
      const restoredView = {
        anchor: restored.snapshot.anchor,
        layout: restored.snapshot.layout,
      }
      liveViewRef.current = restoredView
      publishRestore(identityKey, { kind: 'view', view: restoredView })
      dispatch({
        type: 'HYDRATE',
        snapshot: { ...restored.snapshot, meta: restored.snapshot.pageMeta },
      })
    } else if (restored.kind === 'expired' && !restored.replayable) {
      liveViewRef.current = null
      clearRestore()
      dispatch({
        type: 'TERMINAL_EXPIRED',
        replayable: false,
        generation: transitionGeneration,
      })
    } else if (adapterRef.current.isReplayableIdentity?.(identityRef.current) === false) {
      liveViewRef.current = null
      clearRestore()
      dispatch({
        type: 'TERMINAL_EXPIRED',
        replayable: false,
        generation: transitionGeneration,
      })
    } else {
      liveViewRef.current = null
      publishRestore(identityKey, { kind: 'top' })
      if (autoLoad) {
        void requestPages(
          { kind: 'initial', cursor: null, targetDepth: 1 },
          identityRef.current,
          identityKey,
        )
      }
    }

    return () => {
      inflightRef.current?.abort()
      inflightRef.current = null
      requestInFlightRef.current = false
      generationRef.current += 1
      saveState(
        store,
        stateRef.current,
        liveViewRef.current ?? { anchor: null, layout: null },
        retentionRef.current,
      )
    }
  }, [autoLoad, clearRestore, identityKey, publishRestore, ready, requestPages, saveState, store])

  // While `ready` is false the scope (tab claim, user id) is a placeholder: a
  // request would fetch against it and a fake page would commit as a real
  // result. Callers such as a seed effect fire inside that window on every
  // remount, so the actions are inert until the effect above can restore.
  const loadMore = useCallback(async (): Promise<void> => {
    if (!readyRef.current) return
    const current = stateRef.current
    if (current.status === 'loading' || current.terminal) return
    if (current.status === 'error') {
      if (current.failedRequest?.kind === 'append') {
        await requestPages(current.failedRequest, identityRef.current, current.identityKey)
      }
      return
    }
    if (!current.hasMore) return
    const request: BrowseRequestPlan<Cursor> =
      current.items.length === 0
        ? { kind: 'initial', cursor: null, targetDepth: 1 }
        : { kind: 'append', cursor: current.cursor, targetDepth: 1 }
    await requestPages(request, identityRef.current, current.identityKey)
  }, [requestPages])

  const refresh = useCallback(async (options?: BrowseRefreshOptions): Promise<void> => {
    if (!readyRef.current) return
    const current = stateRef.current
    if (
      current.terminal ||
      adapterRef.current.isReplayableIdentity?.(identityRef.current) === false
    ) {
      return
    }
    inflightRef.current?.abort()
    inflightRef.current = null
    requestInFlightRef.current = false
    await requestPages(
      {
        kind: 'refresh',
        cursor: null,
        targetDepth: options?.depth === 'first' ? 1 : Math.max(1, current.pages.length),
      },
      identityRef.current,
      current.identityKey,
    )
  }, [requestPages])

  const retry = useCallback(async (): Promise<void> => {
    if (!readyRef.current) return
    const current = stateRef.current
    if (
      !current.failedRequest ||
      current.terminal ||
      adapterRef.current.isReplayableIdentity?.(identityRef.current) === false
    ) {
      return
    }
    await requestPages(current.failedRequest, identityRef.current, current.identityKey)
  }, [requestPages])

  const cancelPending = useCallback(() => {
    inflightRef.current?.abort()
    inflightRef.current = null
    requestInFlightRef.current = false
    generationRef.current += 1
  }, [])

  const patchItems = useCallback((patch: BrowseListPatch<Item>): void => {
    // Until `ready` the scope is a placeholder partition. After unmount the
    // refs keep the last real scope: a card's change that settles once the
    // user has left (opened the work mid-request) still reaches the snapshot
    // this list restores on return.
    if (!readyRef.current) return
    const { storage: targetStorage, scope: targetScope } = publishTargetRef.current
    publishBrowseListPatch({
      storage: targetStorage,
      scope: targetScope,
      patch,
      validateItem: adapterRef.current.validateItem,
    })
  }, [])

  const replacePage = useCallback(
    (
      page: BrowsePageResult<Item, Cursor>,
      view: BrowseCheckpoint = { anchor: null, layout: null },
      saveOptions?: BrowseSnapshotSaveOptions,
    ): boolean => {
      inflightRef.current?.abort()
      inflightRef.current = null
      requestInFlightRef.current = false
      const generation = ++generationRef.current
      const currentKey = stateRef.current.identityKey
      dispatch({ type: 'REQUEST_STARTED', generation })
      dispatch({ type: 'PAGE_SUCCEEDED', identityKey: currentKey, generation, mode: 'replace', page })
      liveViewRef.current = view
      return storeRef.current.save(
        currentKey,
        {
          pages: [page.items],
          cursor: page.cursor,
          hasMore: page.hasMore,
          total: page.total,
          anchor: view.anchor,
          layout: view.layout,
          pageMeta: page.meta,
        },
        saveOptions ?? retentionRef.current,
      )
    },
    [],
  )

  // Identity commits from a layout effect, one render after `identityKey`
  // changes. Items are kept for visual continuity across the switch, but every
  // field that *describes* the list — totals, continuation, request outcome,
  // source metadata — belongs to the identity that produced it and must read
  // as unknown until the new one commits. Consumers guard on null; handing
  // them the previous identity's numbers makes those guards unsound.
  //
  // Until `ready`, nothing has been restored or requested, so the buffer is
  // empty because it is unresolved, not because the list is: publishing 'idle'
  // there reads as "No results" and flashes before the snapshot hydrates.
  const publishedState = useMemo<BrowseSessionState<Item, Cursor>>(() => {
    if (state.identityKey === identityKey) {
      return ready ? { ...state, pending: false } : { ...state, pending: false, status: 'loading' }
    }
    return {
      ...state,
      pending: true,
      cursor: null,
      hasMore: true,
      total: null,
      status: 'loading',
      error: null,
      requestKind: null,
      failedRequest: null,
      terminal: null,
      meta: null,
    }
  }, [identityKey, ready, state])

  return {
    state: publishedState,
    loadMore,
    refresh,
    retry,
    checkpoint,
    updateView,
    restoreInstruction:
      state.identityKey === identityKey && restoreInstruction?.identityKey === identityKey
        ? restoreInstruction
        : null,
    acknowledgeRestore,
    // Compatibility for callers migrating to the one-shot instruction API.
    restoredView:
      state.identityKey !== identityKey || restoreInstruction?.identityKey !== identityKey
        ? null
        : restoreInstruction.target.kind === 'view'
          ? restoreInstruction.target.view
          : { anchor: { itemId: null, offset: 0, scrollY: 0 }, layout: null },
    replacePage,
    cancelPending,
    patchItems,
  }
}
