'use client'

import { useCallback, useMemo, useState } from 'react'
import { api } from '@/lib/api'
import {
  canonicalPixivIdentity,
  clearPixivLegacyBrowseState,
  isPixivBrowseItem,
  isPixivCursor,
  PIXIV_BROWSE_SCHEMA_VERSION,
  PIXIV_BROWSE_SOURCE_ID,
  pixivIdentityKey,
  type PixivBrowseIdentity,
  type PixivBrowseItem,
  type PixivCursor,
} from '@/lib/browse/pixiv'
import type { BrowsePageResult } from '@/lib/browse/reducer'
import type { BrowseSnapshotScope } from '@/lib/browse/snapshotStore'
import { useBrowseSession } from '@/hooks/useBrowseSession'
import { useBrowseTabScope } from '@/hooks/useBrowseTabScope'

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

export type UsePixivBrowseSessionOptions = {
  identity: PixivBrowseIdentity
  profileReady: boolean
  credentialsReady: boolean
  credentialsConfigured: boolean
  userId?: string
  tabId?: string
  storage?: Storage
}

type SearchResponse = {
  illusts?: unknown[]
  next_offset?: number | null
  total?: number
}

type FollowingResponse = {
  user_previews?: unknown[]
  next_offset?: number | null
  total?: number
}

type RankingResponse = {
  contents?: unknown[]
  has_next?: boolean
  rank_total?: number
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value > 0
}

function isNonNegativeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 0
}

function finiteTotal(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null
}

function isIllustRecord(value: unknown): value is { id: number } & Record<string, unknown> {
  return isRecord(value) && isPositiveInteger(value.id)
}

function isUserPreviewRecord(
  value: unknown,
): value is { user: { id: number } & Record<string, unknown> } & Record<string, unknown> {
  return isRecord(value) && isRecord(value.user) && isPositiveInteger(value.user.id)
}

function isRankingRecord(value: unknown): value is { illust_id: number } & Record<string, unknown> {
  return isRecord(value) && isPositiveInteger(value.illust_id)
}

function toIllustItems(values: readonly unknown[] | undefined): PixivBrowseItem[] {
  return (values ?? [])
    .filter(isIllustRecord)
    .map((illust) => ({ kind: 'illust' as const, illust }))
}

function toUserItems(values: readonly unknown[] | undefined): PixivBrowseItem[] {
  return (values ?? [])
    .filter(isUserPreviewRecord)
    .map((preview) => ({ kind: 'user' as const, preview }))
}

function toRankingItems(values: readonly unknown[] | undefined): PixivBrowseItem[] {
  return (values ?? [])
    .filter(isRankingRecord)
    .map((entry) => ({ kind: 'ranking' as const, entry }))
}

function offsetValue(cursor: PixivCursor | null): number {
  return cursor?.kind === 'offset' ? cursor.value : 0
}

function pageValue(cursor: PixivCursor | null): number {
  return cursor?.kind === 'page' ? cursor.value : 1
}

function nextOffsetPage(
  response: SearchResponse | FollowingResponse,
  items: PixivBrowseItem[],
): BrowsePageResult<PixivBrowseItem, PixivCursor> {
  const nextOffset = isNonNegativeInteger(response.next_offset) ? response.next_offset : null
  return {
    items,
    cursor: nextOffset === null ? null : { kind: 'offset', value: nextOffset },
    hasMore: nextOffset !== null,
    total: finiteTotal(response.total),
  }
}

function getItemId(item: PixivBrowseItem): string {
  switch (item.kind) {
    case 'illust':
      return `illust:${item.illust.id}`
    case 'ranking':
      return `ranking:${item.entry.illust_id}`
    case 'user':
      return `user:${item.preview.user.id}`
  }
}

function canLoadIdentity(identity: PixivBrowseIdentity, credentialsConfigured: boolean): boolean {
  if (identity.surface === 'ranking') return true
  if (identity.surface === 'search' && identity.backend === 'public') return true
  return credentialsConfigured
}

export function usePixivBrowseSession({
  identity: requestedIdentity,
  profileReady,
  credentialsReady,
  credentialsConfigured,
  userId,
  tabId: requestedTabId,
  storage: providedStorage,
}: UsePixivBrowseSessionOptions) {
  const [storage] = useState<Storage>(
    () =>
      providedStorage ?? (typeof window === 'undefined' ? serverStorage : window.sessionStorage),
  )
  const prerequisitesReady =
    profileReady && credentialsReady && typeof userId === 'string' && userId.length > 0
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
      sourceId: PIXIV_BROWSE_SOURCE_ID,
      schemaVersion: PIXIV_BROWSE_SCHEMA_VERSION,
    }),
    [scopeReady, tabId, userId],
  )
  const identity = useMemo(() => canonicalPixivIdentity(requestedIdentity), [requestedIdentity])
  const identityKey = useMemo(() => pixivIdentityKey(identity), [identity])
  const canLoad = scopeReady && canLoadIdentity(identity, credentialsConfigured)
  const preHydrate = useCallback(() => {
    if (scopeReady) clearPixivLegacyBrowseState(storage)
  }, [scopeReady, storage])

  const fetchPage = useCallback(
    async (
      requestIdentity: PixivBrowseIdentity,
      cursor: PixivCursor | null,
      signal: AbortSignal,
    ): Promise<BrowsePageResult<PixivBrowseItem, PixivCursor>> => {
      if (!scopeReady || !canLoadIdentity(requestIdentity, credentialsConfigured)) {
        return { items: [], cursor: null, hasMore: false, total: 0 }
      }

      switch (requestIdentity.surface) {
        case 'search': {
          if (requestIdentity.backend === 'public') {
            const page = pageValue(cursor)
            const order =
              requestIdentity.sort === 'date_asc'
                ? 'date'
                : requestIdentity.sort === 'popular_desc'
                  ? 'popular_d'
                  : 'date_d'
            const response: SearchResponse = await api.pixiv.searchPublic(
              { word: requestIdentity.query, order, page },
              { signal },
            )
            const items = toIllustItems(response.illusts)
            const hasMore = isNonNegativeInteger(response.next_offset)
            return {
              items,
              cursor: hasMore ? { kind: 'page', value: page + 1 } : null,
              hasMore,
              total: finiteTotal(response.total),
            }
          }
          const response: SearchResponse = await api.pixiv.search(
            {
              word: requestIdentity.query,
              sort: requestIdentity.sort,
              duration: requestIdentity.duration || undefined,
              offset: offsetValue(cursor),
            },
            { signal },
          )
          return nextOffsetPage(response, toIllustItems(response.illusts))
        }
        case 'feed': {
          const response: SearchResponse = await api.pixiv.getFollowingFeed(offsetValue(cursor), {
            signal,
          })
          return nextOffsetPage(response, toIllustItems(response.illusts))
        }
        case 'bookmarks': {
          const response: SearchResponse = await api.pixiv.getMyBookmarks(
            requestIdentity.restrict,
            offsetValue(cursor),
            { signal },
          )
          return nextOffsetPage(response, toIllustItems(response.illusts))
        }
        case 'following': {
          const response: FollowingResponse = await api.pixiv.getFollowing(
            requestIdentity.restrict,
            offsetValue(cursor),
            { signal },
          )
          return nextOffsetPage(response, toUserItems(response.user_previews))
        }
        case 'ranking': {
          const page = pageValue(cursor)
          const response = (await api.pixiv.ranking(
            {
              mode: requestIdentity.r18 ? `${requestIdentity.mode}_r18` : requestIdentity.mode,
              content: requestIdentity.r18 ? 'all' : requestIdentity.content,
              page,
            },
            { signal },
          )) as RankingResponse
          const items = toRankingItems(response.contents)
          const hasMore =
            typeof response.has_next === 'boolean'
              ? response.has_next
              : (response.contents?.length ?? 0) >= 50
          return {
            items,
            cursor: hasMore ? { kind: 'page', value: page + 1 } : null,
            hasMore,
            total: finiteTotal(response.rank_total),
          }
        }
      }
    },
    [credentialsConfigured, scopeReady],
  )
  const adapter = useMemo(
    () => ({
      getItemId,
      fetchPage,
      validateCursor: isPixivCursor,
      validateItem: isPixivBrowseItem,
    }),
    [fetchPage],
  )

  return useBrowseSession<PixivBrowseItem, PixivCursor, PixivBrowseIdentity>({
    identity,
    identityKey,
    adapter,
    scope,
    storage,
    ready: scopeReady,
    autoLoad: canLoad,
    preHydrate,
  })
}
