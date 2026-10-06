'use client'

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef } from 'react'
import { api, type SearchGalleryItem } from '@/lib/api'
import {
  canonicalLibraryBrowseIdentity,
  isLibraryBrowseCursor,
  isSearchGalleryItem,
  invalidateLegacyLibraryScroll,
  LIBRARY_BROWSE_SCHEMA_VERSION,
  LIBRARY_BROWSE_SOURCE_ID,
  libraryBrowseIdentityKey,
  libraryFirstPageChanged,
  libraryBrowseSearchQuery,
  type LibraryBrowseIdentity,
} from '@/lib/browse/library'
import type { BrowseSnapshotScope } from '@/lib/browse/snapshotStore'
import { useBrowseSession } from '@/hooks/useBrowseSession'
import { useBrowseTabScope } from '@/hooks/useBrowseTabScope'
import { useWsConnection, useWsJobs } from '@/lib/ws'

const PAGE_SIZE = 24
const LIBRARY_REFRESH_THROTTLE_MS = 2_000

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

export type UseLibraryBrowseSessionOptions = {
  query: string
  enabled: boolean
  userId?: string
  tabId?: string
  storage?: Storage
}

export function useLibraryBrowseSession({
  query,
  enabled,
  userId,
  tabId: requestedTabId,
  storage: providedStorage,
}: UseLibraryBrowseSessionOptions) {
  const storage =
    providedStorage ?? (typeof window === 'undefined' ? serverStorage : window.sessionStorage)
  const prerequisitesReady = enabled && typeof userId === 'string' && userId.length > 0
  const tabScope = useBrowseTabScope({
    storage,
    enabled: prerequisitesReady,
    requestedTabId,
  })
  const scopeReady = prerequisitesReady && tabScope.ready
  const tabId = tabScope.tabId
  const scope = useMemo<BrowseSnapshotScope>(
    () => ({
      userId: scopeReady ? userId : 'pending',
      tabId,
      sourceId: LIBRARY_BROWSE_SOURCE_ID,
      schemaVersion: LIBRARY_BROWSE_SCHEMA_VERSION,
    }),
    [scopeReady, tabId, userId],
  )
  const identity = useMemo(() => canonicalLibraryBrowseIdentity(query), [query])
  const identityKey = useMemo(() => libraryBrowseIdentityKey(query), [query])
  const preHydrate = useCallback(() => {
    if (scopeReady) invalidateLegacyLibraryScroll(storage)
  }, [scopeReady, storage])
  const fetchPage = useCallback(
    async (requestIdentity: LibraryBrowseIdentity, cursor: string | null, signal: AbortSignal) => {
      if (!scopeReady) return { items: [], cursor: null, hasMore: false, total: 0 }
      const response = await api.search.galleries(
        libraryBrowseSearchQuery(requestIdentity),
        {
          cursor: cursor ?? undefined,
          limit: PAGE_SIZE,
          sort: requestIdentity.sort,
        },
        { signal },
      )
      const nextCursor = response.next_cursor ?? null
      return {
        items: response.items,
        cursor: nextCursor,
        hasMore: response.has_next ?? nextCursor !== null,
        total: response.total ?? null,
      }
    },
    [scopeReady],
  )
  const adapter = useMemo(
    () => ({
      getItemId: (item: SearchGalleryItem) => item.id,
      fetchPage,
      validateCursor: isLibraryBrowseCursor,
      validateItem: isSearchGalleryItem,
    }),
    [fetchPage],
  )

  const session = useBrowseSession<SearchGalleryItem, string, LibraryBrowseIdentity>({
    identity,
    identityKey,
    adapter,
    scope,
    storage,
    ready: scopeReady,
    autoLoad: scopeReady,
    preHydrate,
  })
  const { lastJobUpdate } = useWsJobs()
  const lastRefreshAtRef = useRef(0)
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const refresh = session.refresh

  const seenJobUpdateRef = useRef({ update: lastJobUpdate, ready: false })

  useEffect(() => {
    const seen = seenJobUpdateRef.current
    seenJobUpdateRef.current = { update: lastJobUpdate, ready: scopeReady }
    // A job event is news only to a session that was already live when it
    // arrived. One that predates the initial load or snapshot restore is
    // covered by that load and by the revalidation probe; replaying it in the
    // restore commit refreshes at a depth of one and truncates the snapshot.
    if (!seen.ready || seen.update === lastJobUpdate) return
    if (
      !scopeReady ||
      !lastJobUpdate ||
      (lastJobUpdate.status !== 'done' && lastJobUpdate.status !== 'partial')
    ) {
      return
    }
    const elapsed = Date.now() - lastRefreshAtRef.current
    const runRefresh = () => {
      refreshTimerRef.current = undefined
      lastRefreshAtRef.current = Date.now()
      void refresh()
    }
    if (elapsed >= LIBRARY_REFRESH_THROTTLE_MS) {
      runRefresh()
      return
    }
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current)
    refreshTimerRef.current = setTimeout(runRefresh, LIBRARY_REFRESH_THROTTLE_MS - elapsed)
  }, [lastJobUpdate, refresh, scopeReady])

  // A job event only reaches a mounted page with a live socket. A snapshot
  // restored after a reload, a dropped socket, or a backgrounded PWA would
  // otherwise stay stale, so those moments probe the first page and refresh
  // the loaded depth only when it actually changed.
  const sessionStateRef = useRef(session.state)
  useLayoutEffect(() => {
    sessionStateRef.current = session.state
  }, [session.state])
  const probeControllerRef = useRef<AbortController | null>(null)
  const lastProbeRef = useRef<{ identityKey: string; at: number } | null>(null)

  const revalidate = useCallback(async (): Promise<void> => {
    const before = sessionStateRef.current
    if (
      !scopeReady ||
      before.identityKey !== identityKey ||
      before.status !== 'idle' ||
      before.terminal ||
      before.pages.length === 0
    ) {
      return
    }
    const now = Date.now()
    const lastProbe = lastProbeRef.current
    if (
      lastProbe?.identityKey === identityKey &&
      now - lastProbe.at < LIBRARY_REFRESH_THROTTLE_MS
    ) {
      return
    }
    lastProbeRef.current = { identityKey, at: now }
    probeControllerRef.current?.abort()
    const controller = new AbortController()
    probeControllerRef.current = controller
    let probe: Awaited<ReturnType<typeof fetchPage>>
    try {
      probe = await fetchPage(identity, null, controller.signal)
    } catch {
      // Best effort: the restored buffer stays as it is.
      return
    }
    if (controller.signal.aborted) return
    const current = sessionStateRef.current
    if (current.identityKey !== identityKey || current.status !== 'idle') return
    if (!libraryFirstPageChanged(current, probe)) return
    lastRefreshAtRef.current = Date.now()
    await refresh()
  }, [fetchPage, identity, identityKey, refresh, scopeReady])
  const revalidateRef = useRef(revalidate)
  useLayoutEffect(() => {
    revalidateRef.current = revalidate
  }, [revalidate])

  const restoreInstruction = session.restoreInstruction
  const restoredSnapshotKey =
    restoreInstruction?.target.kind === 'view' ? restoreInstruction.key : null
  const probedRestoreKeyRef = useRef<string | null>(null)
  useEffect(() => {
    if (!restoredSnapshotKey || probedRestoreKeyRef.current === restoredSnapshotKey) return
    probedRestoreKeyRef.current = restoredSnapshotKey
    void revalidateRef.current()
  }, [restoredSnapshotKey])

  const { connected } = useWsConnection()
  const hasConnectedRef = useRef(false)
  useEffect(() => {
    if (!connected) return
    if (hasConnectedRef.current) void revalidateRef.current()
    hasConnectedRef.current = true
  }, [connected])

  useEffect(() => {
    const onVisibilityChange = () => {
      if (document.visibilityState === 'visible') void revalidateRef.current()
    }
    document.addEventListener('visibilitychange', onVisibilityChange)
    return () => document.removeEventListener('visibilitychange', onVisibilityChange)
  }, [])

  useEffect(
    () => () => {
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current)
      probeControllerRef.current?.abort()
    },
    [],
  )

  return session
}
