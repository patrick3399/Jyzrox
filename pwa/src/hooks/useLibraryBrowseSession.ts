'use client'

import { useCallback, useEffect, useMemo, useRef } from 'react'
import { api, type SearchGalleryItem } from '@/lib/api'
import {
  canonicalLibraryBrowseIdentity,
  isLibraryBrowseCursor,
  isSearchGalleryItem,
  invalidateLegacyLibraryScroll,
  LIBRARY_BROWSE_SCHEMA_VERSION,
  LIBRARY_BROWSE_SOURCE_ID,
  libraryBrowseIdentityKey,
  libraryBrowseSearchQuery,
  type LibraryBrowseIdentity,
} from '@/lib/browse/library'
import type { BrowseSnapshotScope } from '@/lib/browse/snapshotStore'
import { useBrowseSession } from '@/hooks/useBrowseSession'
import { useBrowseTabScope } from '@/hooks/useBrowseTabScope'
import { useWsJobs } from '@/lib/ws'

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

  useEffect(() => {
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

  useEffect(
    () => () => {
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current)
    },
    [],
  )

  return session
}
