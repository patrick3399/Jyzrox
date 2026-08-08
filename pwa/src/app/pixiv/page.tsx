'use client'

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { LayoutGrid, List } from 'lucide-react'
import { useRouter, useSearchParams } from 'next/navigation'
import useSWR from 'swr'
import { CredentialBanner } from '@/components/CredentialBanner'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { VirtualGrid } from '@/components/VirtualGrid'
import { useGridKeyboard } from '@/hooks/useGridKeyboard'
import { useIllustActions } from '@/hooks/useIllustActions'
import { usePixivBrowseSession } from '@/hooks/usePixivBrowseSession'
import { useProfile } from '@/hooks/useProfile'
import { api } from '@/lib/api'
import { decideAnchorRestore, type BrowseAnchor } from '@/lib/browse/anchor'
import {
  parsePixivIdentity,
  serializePixivIdentity,
  type PixivBrowseIdentity,
  type PixivBrowseItem,
} from '@/lib/browse/pixiv'
import type { BrowseLayoutSnapshot } from '@/lib/browse/snapshotStore'
import { t } from '@/lib/i18n'
import type { PixivIllust, PixivUserPreview } from '@/lib/types'
import { useLocale } from '@/components/LocaleProvider'
import { toast } from 'sonner'

const SORT_OPTIONS = [
  { value: 'date_desc', label: () => t('pixiv.sortDateDesc') },
  { value: 'date_asc', label: () => t('pixiv.sortDateAsc') },
  { value: 'popular_desc', label: () => t('pixiv.sortPopularDesc') },
]

const DURATION_OPTIONS = [
  { value: '', label: () => t('pixiv.durationAll') },
  { value: 'within_last_day', label: () => t('pixiv.durationDay') },
  { value: 'within_last_week', label: () => t('pixiv.durationWeek') },
  { value: 'within_last_month', label: () => t('pixiv.durationMonth') },
]

const RANKING_MODES = [
  { value: 'daily', label: () => t('browse.rankingDaily') },
  { value: 'weekly', label: () => t('browse.rankingWeekly') },
  { value: 'monthly', label: () => t('browse.rankingMonthly') },
  { value: 'rookie', label: () => t('browse.rankingRookie') },
]

const RANKING_CONTENT = [
  { value: 'all', label: () => t('browse.rankingAll') },
  { value: 'illust', label: () => t('browse.rankingIllust') },
  { value: 'manga', label: () => t('browse.rankingManga') },
  { value: 'ugoira', label: () => t('browse.rankingUgoira') },
]

type Tab = 'feed' | 'following' | 'ranking' | 'bookmarks'
type ViewMode = 'grid' | 'list'

function pixivItemKey(item: PixivBrowseItem): string {
  switch (item.kind) {
    case 'illust':
      return `illust:${item.illust.id}`
    case 'ranking':
      return `ranking:${item.entry.illust_id}`
    case 'user':
      return `user:${item.preview.user.id}`
  }
}

function IllustCard({
  illust,
  viewMode,
  onNavigate,
  onBookmark,
}: {
  illust: PixivIllust
  viewMode: ViewMode
  onNavigate: () => void
  onBookmark: (illustId: number, bookmarked: boolean) => void
}) {
  const { downloading, bookmarked, bookmarking, handleDownload, handleBookmark } = useIllustActions(
    illust,
    (nextBookmarked) => onBookmark(illust.id, nextBookmarked),
  )
  const thumbUrl = api.pixiv.imageProxyUrl(illust.image_urls.square_medium)
  const tags = illust.tags ?? []
  const visibleTags = tags.slice(0, 4)
  const extraTagCount = tags.length - visibleTags.length
  const imageError = (event: React.SyntheticEvent<HTMLImageElement>) => {
    event.currentTarget.style.display = 'none'
  }

  if (viewMode === 'list') {
    return (
      <div className="group flex w-full gap-3 rounded-lg border border-vault-border bg-vault-card p-3 text-left hover:border-vault-accent">
        <button type="button" onClick={onNavigate} className="flex min-w-0 flex-1 gap-3 text-left">
          <img
            src={thumbUrl}
            alt={illust.title}
            className="h-[72px] w-[72px] shrink-0 rounded object-cover"
            loading="lazy"
            onError={imageError}
          />
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium text-vault-text">
              {illust.title}
            </span>
            <span className="block truncate text-xs text-vault-text-secondary">
              {illust.user.name}
            </span>
            {visibleTags.length > 0 && (
              <span className="mt-1 flex flex-wrap gap-1">
                {visibleTags.map((tag) => (
                  <span
                    key={tag.name}
                    className="max-w-[100px] truncate rounded border border-vault-border bg-vault-input px-1.5 py-0.5 text-[10px] text-vault-text-muted"
                  >
                    {tag.name}
                  </span>
                ))}
                {extraTagCount > 0 && (
                  <span className="text-[10px] text-vault-text-muted">+{extraTagCount}</span>
                )}
              </span>
            )}
            <span className="mt-1 flex gap-3 text-[10px] text-vault-text-secondary">
              <span>
                {(illust.total_view ?? 0).toLocaleString()} {t('pixiv.views')}
              </span>
              <span>
                {(illust.total_bookmarks ?? 0).toLocaleString()} {t('pixiv.bookmarks')}
              </span>
            </span>
          </span>
        </button>
        <button
          type="button"
          onClick={handleBookmark}
          disabled={bookmarking}
          className={bookmarked ? 'text-yellow-400' : 'text-vault-text-muted'}
        >
          {bookmarked ? '★' : '☆'}
        </button>
        <button
          type="button"
          onClick={handleDownload}
          disabled={downloading}
          className="rounded bg-vault-accent px-2 py-1 text-xs text-white disabled:opacity-50"
        >
          {downloading ? t('pixiv.downloading') : t('pixiv.download')}
        </button>
      </div>
    )
  }

  return (
    <div className="group relative block w-full text-left">
      <button type="button" onClick={onNavigate} className="block w-full text-left">
        <span className="relative block aspect-square overflow-hidden rounded-lg bg-vault-input">
          <img
            src={thumbUrl}
            alt={illust.title}
            className="h-full w-full object-cover transition-transform group-hover:scale-105"
            loading="lazy"
            onError={imageError}
          />
          {illust.page_count > 1 && (
            <span className="absolute right-1.5 top-1.5 rounded bg-black/70 px-1.5 py-0.5 text-[10px] text-white">
              {illust.page_count} {t('pixiv.pages')}
            </span>
          )}
        </span>
        <span className="mt-1.5 block truncate text-sm font-medium text-vault-text">
          {illust.title}
        </span>
        <span className="block truncate text-xs text-vault-text-secondary">{illust.user.name}</span>
        <span className="mt-0.5 flex gap-2 text-[10px] text-vault-text-secondary">
          <span>
            {(illust.total_view ?? 0).toLocaleString()} {t('pixiv.views')}
          </span>
          <span>
            {(illust.total_bookmarks ?? 0).toLocaleString()} {t('pixiv.bookmarks')}
          </span>
        </span>
      </button>
      <button
        type="button"
        onClick={handleBookmark}
        disabled={bookmarking}
        className={`absolute left-1.5 top-1.5 rounded bg-black/70 px-1.5 py-0.5 ${bookmarked ? 'text-yellow-400' : 'text-white'}`}
      >
        {bookmarked ? '★' : '☆'}
      </button>
      <button
        type="button"
        onClick={handleDownload}
        disabled={downloading}
        className="absolute bottom-12 right-2 rounded bg-vault-accent px-2 py-1 text-xs text-white disabled:opacity-50"
      >
        {downloading ? t('pixiv.downloading') : t('pixiv.download')}
      </button>
    </div>
  )
}

function RankingCard({ entry, onOpen }: { entry: Record<string, unknown>; onOpen: () => void }) {
  const title = typeof entry.title === 'string' ? entry.title : ''
  const userName = typeof entry.user_name === 'string' ? entry.user_name : ''
  const imageUrl = typeof entry.url === 'string' ? api.pixiv.imageProxyUrl(entry.url) : ''
  return (
    <button type="button" onClick={onOpen} className="group block w-full text-left">
      <span className="relative block aspect-square overflow-hidden rounded-lg bg-vault-input">
        {imageUrl && (
          <img
            src={imageUrl}
            alt={title}
            className="h-full w-full object-cover transition-transform group-hover:scale-105"
            loading="lazy"
          />
        )}
        <span className="absolute left-1.5 top-1.5 rounded bg-black/70 px-1.5 py-0.5 text-[10px] font-bold text-white">
          #{String(entry.rank ?? '')}
        </span>
      </span>
      <span className="mt-1.5 block truncate text-sm font-medium text-vault-text">{title}</span>
      <span className="block truncate text-xs text-vault-text-secondary">{userName}</span>
    </button>
  )
}

function UserPreviewCard({
  preview,
  onOpen,
  onFollow,
}: {
  preview: PixivUserPreview
  onOpen: () => void
  onFollow: () => void
}) {
  const [followed, setFollowed] = useState(true)
  const [toggling, setToggling] = useState(false)

  const handleToggleFollow = async (event: React.MouseEvent) => {
    event.preventDefault()
    event.stopPropagation()
    if (toggling) return
    setToggling(true)
    try {
      if (followed) await api.pixiv.unfollowUser(preview.user.id)
      else await api.pixiv.followUser(preview.user.id)
      setFollowed((value) => !value)
      onFollow()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('common.failedToSave'))
    } finally {
      setToggling(false)
    }
  }

  return (
    <div className="group relative block w-full overflow-hidden rounded-lg border border-vault-border bg-vault-card text-left hover:border-vault-accent">
      <button type="button" onClick={onOpen} className="block w-full text-left">
        {preview.illusts.length > 0 ? (
          <span className="grid grid-cols-3 gap-0.5">
            {preview.illusts.slice(0, 3).map((illust) => (
              <img
                key={illust.id}
                src={api.pixiv.imageProxyUrl(illust.image_urls.square_medium)}
                alt=""
                className="aspect-square h-full w-full bg-vault-input object-cover"
                onError={(event) => {
                  event.currentTarget.style.display = 'none'
                }}
              />
            ))}
          </span>
        ) : (
          <span className="flex aspect-[3/1] items-center justify-center bg-vault-input text-[10px] uppercase tracking-widest text-vault-text-muted">
            {t('pixiv.noWorks')}
          </span>
        )}
        <span className="flex items-center gap-2 p-2 pr-20">
          {preview.user.profile_image ? (
            <img
              src={api.pixiv.imageProxyUrl(preview.user.profile_image)}
              alt={preview.user.name}
              className="h-7 w-7 shrink-0 rounded-full bg-vault-input object-cover"
              onError={(event) => {
                event.currentTarget.style.display = 'none'
              }}
            />
          ) : (
            <span className="h-7 w-7 shrink-0 rounded-full bg-vault-input" />
          )}
          <span className="min-w-0 flex-1 truncate text-xs font-medium text-vault-text">
            {preview.user.name}
          </span>
        </span>
      </button>
      <button
        type="button"
        onClick={handleToggleFollow}
        disabled={toggling}
        className="absolute bottom-2 right-2 rounded px-1.5 py-0.5 text-[10px] text-vault-text-secondary disabled:opacity-50"
      >
        {toggling ? '…' : followed ? t('pixiv.unfollow') : t('pixiv.follow')}
      </button>
    </div>
  )
}

function PixivPageInner() {
  useLocale()
  const router = useRouter()
  const searchParams = useSearchParams()
  const searchString = searchParams.toString()
  const { data: credentials, isLoading: credentialsLoading } = useSWR(
    '/api/settings/credentials',
    () => api.settings.getCredentials(),
  )
  const { data: profile, isLoading: profileLoading } = useProfile()
  const credentialsMissing = credentialsLoading ? false : !credentials?.pixiv?.configured
  const searchBackend = credentialsMissing ? 'public' : 'authenticated'
  const [initialIdentity] = useState(() =>
    parsePixivIdentity(new URLSearchParams(searchString), searchBackend),
  )
  const initialTab: Tab =
    initialIdentity.surface === 'feed' ||
    initialIdentity.surface === 'following' ||
    initialIdentity.surface === 'bookmarks'
      ? initialIdentity.surface
      : 'ranking'
  const [activeTab, setActiveTab] = useState<Tab>(initialTab)
  // Which surface the current history entry belongs to, so a commit can tell a
  // surface change from a filter change. Kept in sync with URLs that arrive from
  // outside the page (back/forward) as well as ones this page writes.
  const identitySurfaceRef = useRef(initialIdentity.surface)
  const [searchQuery, setSearchQuery] = useState(
    initialIdentity.surface === 'search' ? initialIdentity.query : '',
  )
  const [submittedQuery, setSubmittedQuery] = useState(
    initialIdentity.surface === 'search' ? initialIdentity.query : '',
  )
  const [searchSort, setSearchSort] = useState(
    initialIdentity.surface === 'search' ? initialIdentity.sort : 'date_desc',
  )
  const [searchDuration, setSearchDuration] = useState(
    initialIdentity.surface === 'search' ? initialIdentity.duration : '',
  )
  const [rankingMode, setRankingMode] = useState(
    initialIdentity.surface === 'ranking' ? initialIdentity.mode : 'daily',
  )
  const [rankingContent, setRankingContent] = useState(
    initialIdentity.surface === 'ranking' ? initialIdentity.content : 'all',
  )
  const [rankingR18, setRankingR18] = useState(
    initialIdentity.surface === 'ranking' && initialIdentity.r18,
  )
  const [bookmarksRestrict, setBookmarksRestrict] = useState<'public' | 'private'>(
    initialIdentity.surface === 'bookmarks' ? initialIdentity.restrict : 'public',
  )
  const [viewMode, setViewMode] = useState<ViewMode>(() => {
    if (typeof window === 'undefined') return 'grid'
    try {
      return window.localStorage.getItem('pixiv_view_mode') === 'list' ? 'list' : 'grid'
    } catch {
      return 'grid'
    }
  })

  useEffect(() => {
    const incoming = parsePixivIdentity(new URLSearchParams(searchString), searchBackend)
    identitySurfaceRef.current = incoming.surface
    if (incoming.surface === 'search') {
      setSearchQuery(incoming.query)
      setSubmittedQuery(incoming.query)
      setSearchSort(incoming.sort)
      setSearchDuration(incoming.duration)
      return
    }
    setSearchQuery('')
    setSubmittedQuery('')
    if (incoming.surface === 'ranking') {
      setActiveTab('ranking')
      setRankingMode(incoming.mode)
      setRankingContent(incoming.content)
      setRankingR18(incoming.r18)
    } else if (incoming.surface === 'bookmarks') {
      setActiveTab('bookmarks')
      setBookmarksRestrict(incoming.restrict)
    } else {
      setActiveTab(incoming.surface)
    }
  }, [searchBackend, searchString])

  const handleViewModeChange = (nextMode: ViewMode) => {
    setViewMode(nextMode)
    try {
      window.localStorage.setItem('pixiv_view_mode', nextMode)
    } catch {
      // View preference is best effort.
    }
  }

  const identity = useMemo<PixivBrowseIdentity>(() => {
    if (submittedQuery) {
      return {
        surface: 'search',
        query: submittedQuery,
        sort: searchSort,
        duration: searchDuration,
        backend: searchBackend,
      }
    }
    if (activeTab === 'ranking') {
      return {
        surface: 'ranking',
        mode: rankingMode,
        content: rankingContent,
        r18: rankingR18,
      }
    }
    if (activeTab === 'bookmarks') {
      return { surface: 'bookmarks', restrict: bookmarksRestrict }
    }
    if (activeTab === 'following') return { surface: 'following', restrict: 'public' }
    return { surface: 'feed' }
  }, [
    activeTab,
    bookmarksRestrict,
    rankingContent,
    rankingMode,
    rankingR18,
    searchBackend,
    searchDuration,
    searchSort,
    submittedQuery,
  ])

  const session = usePixivBrowseSession({
    identity,
    profileReady: !profileLoading,
    credentialsReady: !credentialsLoading,
    credentialsConfigured: !credentialsMissing,
    userId: profile?.username,
  })
  const {
    state,
    checkpoint,
    loadMore,
    refresh,
    retry,
    restoreInstruction,
    acknowledgeRestore,
    updateView,
  } = session
  const visibleRangeRef = useRef({ startIndex: 0, endIndex: 0 })
  const layoutRef = useRef<BrowseLayoutSnapshot | null>(null)
  const [measuredLayout, setMeasuredLayout] = useState<BrowseLayoutSnapshot | null>(null)
  const elementRef = useRef(new Map<number, HTMLElement>())
  const scrollYRef = useRef(0)
  const liveViewRevisionRef = useRef(0)
  const persistedViewRevisionRef = useRef(0)
  const handledRestoreKeyRef = useRef<string | null>(null)
  const scrollAnimationFrameRef = useRef<number | null>(null)
  const checkpointTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const captureView = useCallback(() => {
    const index = visibleRangeRef.current.startIndex
    const item = state.items[index]
    const element = elementRef.current.get(index)
    const anchor: BrowseAnchor = {
      itemId: item ? pixivItemKey(item) : null,
      offset: element?.getBoundingClientRect().top ?? 0,
      scrollY: scrollYRef.current,
    }
    return { anchor, layout: layoutRef.current }
  }, [state.items])

  const persistView = useCallback(() => {
    checkpoint(captureView())
    persistedViewRevisionRef.current = liveViewRevisionRef.current
  }, [captureView, checkpoint])

  const flushPendingViewWork = useCallback(() => {
    if (scrollAnimationFrameRef.current !== null) {
      cancelAnimationFrame(scrollAnimationFrameRef.current)
      scrollAnimationFrameRef.current = null
    }
    if (checkpointTimerRef.current !== null) {
      clearTimeout(checkpointTimerRef.current)
      checkpointTimerRef.current = null
    }
    scrollYRef.current = window.scrollY
    liveViewRevisionRef.current += 1
  }, [])

  /** Commit a new browse identity to the URL.
   *
   *  A surface is a place the user navigated to, so it must be reachable by
   *  back: this page has no back FAB, and on mobile the edge swipe is the only
   *  back affordance, so collapsing ranking -> feed into one entry means backing
   *  out of Pixiv entirely instead of stepping back a surface. Filters inside a
   *  surface are not places — their controls stay on screen, and one entry per
   *  ranking-mode change would make leaving take one swipe per control touched.
   *  Same rule as the E-Hentai tabs. */
  const commitIdentity = useCallback(
    (nextIdentity: PixivBrowseIdentity) => {
      flushPendingViewWork()
      checkpoint(captureView())
      persistedViewRevisionRef.current = liveViewRevisionRef.current
      const url = `/pixiv?${serializePixivIdentity(nextIdentity).toString()}`
      const changesSurface = nextIdentity.surface !== identitySurfaceRef.current
      identitySurfaceRef.current = nextIdentity.surface
      if (changesSurface) router.push(url, { scroll: false })
      else router.replace(url, { scroll: false })
    },
    [captureView, checkpoint, flushPendingViewWork, router],
  )

  const openPixivItem = useCallback(
    (illustId: number) => {
      flushPendingViewWork()
      checkpoint(captureView())
      persistedViewRevisionRef.current = liveViewRevisionRef.current
      router.push(`/pixiv/illust/${illustId}`)
    },
    [captureView, checkpoint, flushPendingViewWork, router],
  )
  const openPixivUser = useCallback(
    (userId: number) => {
      flushPendingViewWork()
      checkpoint(captureView())
      persistedViewRevisionRef.current = liveViewRevisionRef.current
      router.push(`/pixiv/user/${userId}`)
    },
    [captureView, checkpoint, flushPendingViewWork, router],
  )

  useEffect(() => {
    scrollYRef.current = window.scrollY
    const onScroll = () => {
      if (scrollAnimationFrameRef.current !== null)
        cancelAnimationFrame(scrollAnimationFrameRef.current)
      scrollAnimationFrameRef.current = requestAnimationFrame(() => {
        scrollAnimationFrameRef.current = null
        scrollYRef.current = window.scrollY
        liveViewRevisionRef.current += 1
        updateView(captureView())
      })
      if (checkpointTimerRef.current !== null) clearTimeout(checkpointTimerRef.current)
      checkpointTimerRef.current = setTimeout(() => {
        checkpointTimerRef.current = null
        persistView()
      }, 250)
    }
    const onPageHide = () => {
      if (checkpointTimerRef.current !== null) {
        clearTimeout(checkpointTimerRef.current)
        checkpointTimerRef.current = null
      }
      scrollYRef.current = window.scrollY
      persistView()
    }
    window.addEventListener('scroll', onScroll, { passive: true })
    window.addEventListener('pagehide', onPageHide)
    return () => {
      window.removeEventListener('scroll', onScroll)
      window.removeEventListener('pagehide', onPageHide)
      if (scrollAnimationFrameRef.current !== null) {
        cancelAnimationFrame(scrollAnimationFrameRef.current)
        scrollAnimationFrameRef.current = null
      }
      if (checkpointTimerRef.current !== null) {
        clearTimeout(checkpointTimerRef.current)
        checkpointTimerRef.current = null
      }
    }
  }, [captureView, persistView, updateView])

  const restoreDecision = useMemo(
    () =>
      restoreInstruction?.target.kind === 'view' && restoreInstruction.target.view.anchor
        ? decideAnchorRestore(restoreInstruction.target.view.anchor, state.items, pixivItemKey)
        : null,
    [restoreInstruction, state.items],
  )
  const restoreKey = restoreInstruction?.key ?? null
  const layoutReady = measuredLayout !== null
  const restoreRequest =
    layoutReady && restoreKey && restoreDecision?.kind === 'anchor'
      ? { key: restoreKey, index: restoreDecision.index }
      : undefined

  useEffect(() => {
    if (!restoreInstruction || restoreInstruction.identityKey !== state.identityKey) return
    if (handledRestoreKeyRef.current === restoreInstruction.key) return
    if (restoreInstruction.target.kind === 'top') {
      handledRestoreKeyRef.current = restoreInstruction.key
      window.scrollTo({ top: 0 })
      acknowledgeRestore(restoreInstruction.key)
      return
    }
    if (!layoutReady) return
    if (!restoreInstruction.target.view.anchor) {
      handledRestoreKeyRef.current = restoreInstruction.key
      window.scrollTo({ top: 0 })
      acknowledgeRestore(restoreInstruction.key)
      return
    }
    if (restoreDecision?.kind !== 'pixel' && restoreDecision?.kind !== 'top') return
    handledRestoreKeyRef.current = restoreInstruction.key
    window.scrollTo({ top: restoreDecision.kind === 'pixel' ? restoreDecision.scrollY : 0 })
    acknowledgeRestore(restoreInstruction.key)
  }, [
    acknowledgeRestore,
    layoutReady,
    restoreDecision,
    restoreInstruction,
    state.identityKey,
  ])

  const handleRestoreApplied = useCallback(
    (request: { key: string; index: number }) => {
      if (
        !restoreInstruction ||
        handledRestoreKeyRef.current === request.key ||
        restoreInstruction.identityKey !== state.identityKey ||
        request.key !== restoreInstruction.key ||
        restoreDecision?.kind !== 'anchor'
      )
        return
      const element = elementRef.current.get(request.index)
      if (!element) return
      window.scrollBy({ top: element.getBoundingClientRect().top - restoreDecision.offset })
      updateView(captureView())
      handledRestoreKeyRef.current = request.key
      acknowledgeRestore(request.key)
    },
    [
      acknowledgeRestore,
      captureView,
      restoreDecision,
      restoreInstruction,
      state.identityKey,
      updateView,
    ],
  )

  const onBookmark = useCallback(() => {
    void refresh()
  }, [refresh])
  const patchItemsFromServer = useCallback(() => {
    void refresh()
  }, [refresh])
  const onFollow = useCallback(() => patchItemsFromServer(), [patchItemsFromServer])
  const loadMoreRetry = retry

  const [colCount, setColCount] = useState(2)
  const handleKeyboardEnter = useCallback(
    (index: number) => {
      const item = state.items[index]
      if (item?.kind === 'illust') openPixivItem(item.illust.id)
      else if (item?.kind === 'ranking') openPixivItem(item.entry.illust_id)
      else if (item?.kind === 'user') openPixivUser(item.preview.user.id)
    },
    [openPixivItem, openPixivUser, state.items],
  )
  const { focusedIndex, registerElement } = useGridKeyboard({
    totalItems: state.items.length,
    colCount,
    onEnter: handleKeyboardEnter,
    enabled: state.items.length > 0,
  })
  const handleRegisterElement = useCallback(
    (index: number, element: HTMLElement | null) => {
      if (element) elementRef.current.set(index, element)
      else elementRef.current.delete(index)
      registerElement(index, element)
    },
    [registerElement],
  )
  const handleVisibleRange = useCallback((range: { startIndex: number; endIndex: number }) => {
    visibleRangeRef.current = range
  }, [])
  const handleLayout = useCallback(
    (layout: { colCount: number; containerWidth: number; scrollMargin: number }) => {
      layoutRef.current = {
        columns: layout.colCount,
        width: layout.containerWidth,
        mode: viewMode,
      }
      setMeasuredLayout(layoutRef.current)
      setColCount(layout.colCount)
    },
    [viewMode],
  )

  const handleSearchSubmit = () => {
    const query = searchQuery.trim()
    if (!query) return
    setSubmittedQuery(query)
    commitIdentity({
      surface: 'search',
      query,
      sort: searchSort,
      duration: searchDuration,
      backend: searchBackend,
    })
  }
  const handleClearSearch = () => {
    setSearchQuery('')
    setSubmittedQuery('')
    commitIdentity({
      surface: activeTab === 'ranking' ? 'ranking' : activeTab,
      ...(activeTab === 'ranking'
        ? { mode: rankingMode, content: rankingContent, r18: rankingR18 }
        : activeTab === 'bookmarks'
          ? { restrict: bookmarksRestrict }
          : activeTab === 'following'
            ? { restrict: 'public' as const }
            : {}),
    } as PixivBrowseIdentity)
  }
  const handleTabChange = (tab: Tab) => {
    setActiveTab(tab)
    setSearchQuery('')
    setSubmittedQuery('')
    if (tab === 'ranking')
      commitIdentity({
        surface: 'ranking',
        mode: rankingMode,
        content: rankingContent,
        r18: rankingR18,
      })
    else if (tab === 'bookmarks')
      commitIdentity({ surface: 'bookmarks', restrict: bookmarksRestrict })
    else if (tab === 'following') commitIdentity({ surface: 'following', restrict: 'public' })
    else commitIdentity({ surface: 'feed' })
  }

  const isPrivateSurface =
    identity.surface === 'feed' ||
    identity.surface === 'following' ||
    identity.surface === 'bookmarks' ||
    (identity.surface === 'search' && identity.backend === 'authenticated')
  const isSessionLoading = state.status === 'loading'
  const initialLoading = isSessionLoading && state.items.length === 0
  const showCredentialGate = credentialsMissing && isPrivateSurface
  const gridColumns =
    identity.surface === 'following'
      ? { base: 2, sm: 3, md: 4, lg: 5 }
      : identity.surface === 'ranking'
        ? { base: 3, sm: 4, md: 5, lg: 7, xl: 8, xxl: 10 }
        : viewMode === 'list'
          ? { base: 1 }
          : { base: 2, sm: 3, md: 4, lg: 6, xl: 8 }

  return (
    <div className="space-y-4">
      {credentialsMissing && <CredentialBanner source="pixiv" />}
      <div className="flex gap-2">
        <input
          type="text"
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') handleSearchSubmit()
            if (event.key === 'Escape') handleClearSearch()
          }}
          placeholder={t('pixiv.searchPlaceholder')}
          className="flex-1 rounded-lg border border-vault-border bg-vault-card px-4 py-2.5 text-sm text-vault-text"
        />
        <button
          type="button"
          onClick={handleSearchSubmit}
          className="rounded-lg bg-vault-accent px-4 py-2.5 text-sm font-medium text-white"
        >
          {t('pixiv.search')}
        </button>
        <div className="flex overflow-hidden rounded-lg border border-vault-border">
          <button
            type="button"
            onClick={() => handleViewModeChange('grid')}
            aria-label={t('browse.gridView')}
            aria-pressed={viewMode === 'grid'}
            className={`px-3 ${viewMode === 'grid' ? 'bg-vault-input text-vault-text' : 'text-vault-text-muted'}`}
          >
            <LayoutGrid size={18} />
          </button>
          <button
            type="button"
            onClick={() => handleViewModeChange('list')}
            aria-label={t('browse.listView')}
            aria-pressed={viewMode === 'list'}
            className={`px-3 ${viewMode === 'list' ? 'bg-vault-input text-vault-text' : 'text-vault-text-muted'}`}
          >
            <List size={18} />
          </button>
        </div>
      </div>

      {identity.surface === 'search' ? (
        <div className="flex flex-wrap items-center gap-2">
          <span className="mr-auto text-sm text-vault-text-secondary">
            {t('browse.resultsFor', { query: identity.query })}
          </span>
          <select
            value={searchSort}
            onChange={(event) => {
              const sort = event.target.value
              setSearchSort(sort)
              commitIdentity({ ...identity, sort })
            }}
            className="rounded-lg border border-vault-border bg-vault-input px-3 py-1.5 text-sm"
          >
            {SORT_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label()}
              </option>
            ))}
          </select>
          {!credentialsMissing && (
            <select
              value={searchDuration}
              onChange={(event) => {
                const duration = event.target.value
                setSearchDuration(duration)
                commitIdentity({ ...identity, duration })
              }}
              className="rounded-lg border border-vault-border bg-vault-input px-3 py-1.5 text-sm"
            >
              {DURATION_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label()}
                </option>
              ))}
            </select>
          )}
          <button
            type="button"
            onClick={handleClearSearch}
            className="text-xs text-vault-text-muted"
          >
            {t('browse.clearSearch')}
          </button>
        </div>
      ) : (
        <div className="flex gap-1 overflow-x-auto border-b border-vault-border">
          <button
            type="button"
            onClick={() => handleTabChange('ranking')}
            aria-current={activeTab === 'ranking' ? 'page' : undefined}
            className={`border-b-2 px-4 py-2 text-sm ${activeTab === 'ranking' ? 'border-vault-accent text-vault-text' : 'border-transparent text-vault-text-muted'}`}
          >
            {t('browse.ranking')}
          </button>
          {!credentialsMissing && (
            <>
              <button
                type="button"
                onClick={() => handleTabChange('feed')}
                aria-current={activeTab === 'feed' ? 'page' : undefined}
                className={`border-b-2 px-4 py-2 text-sm ${activeTab === 'feed' ? 'border-blue-400 text-vault-text' : 'border-transparent text-vault-text-muted'}`}
              >
                {t('pixiv.feedTab')}
              </button>
              <button
                type="button"
                onClick={() => handleTabChange('following')}
                aria-current={activeTab === 'following' ? 'page' : undefined}
                className={`border-b-2 px-4 py-2 text-sm ${activeTab === 'following' ? 'border-[#e91e63] text-vault-text' : 'border-transparent text-vault-text-muted'}`}
              >
                {t('pixiv.followingTab')}
              </button>
              <button
                type="button"
                onClick={() => handleTabChange('bookmarks')}
                aria-current={activeTab === 'bookmarks' ? 'page' : undefined}
                className={`border-b-2 px-4 py-2 text-sm ${activeTab === 'bookmarks' ? 'border-[#ff9800] text-vault-text' : 'border-transparent text-vault-text-muted'}`}
              >
                {t('pixiv.bookmarks')}
              </button>
            </>
          )}
        </div>
      )}

      {identity.surface === 'ranking' && (
        <div className="flex flex-wrap gap-2">
          <select
            value={rankingMode}
            onChange={(event) => {
              const mode = event.target.value
              setRankingMode(mode)
              commitIdentity({ ...identity, mode })
            }}
            className="rounded-lg border border-vault-border bg-vault-input px-3 py-1.5 text-sm"
          >
            {RANKING_MODES.filter(
              (option) => !rankingR18 || option.value === 'daily' || option.value === 'weekly',
            ).map((option) => (
              <option key={option.value} value={option.value}>
                {option.label()}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={() => {
              const r18 = !rankingR18
              setRankingR18(r18)
              commitIdentity({ ...identity, r18 })
            }}
            disabled={credentialsMissing}
            aria-pressed={rankingR18}
            className={`rounded-lg border px-3 py-1.5 text-sm ${rankingR18 ? 'border-pink-500 bg-pink-600 text-white' : 'border-vault-border bg-vault-input text-vault-text-secondary'}`}
          >
            {t('browse.r18')}
          </button>
          {!rankingR18 && (
            <select
              value={rankingContent}
              onChange={(event) => {
                const content = event.target.value
                setRankingContent(content)
                commitIdentity({ ...identity, content })
              }}
              className="rounded-lg border border-vault-border bg-vault-input px-3 py-1.5 text-sm"
            >
              {RANKING_CONTENT.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label()}
                </option>
              ))}
            </select>
          )}
        </div>
      )}

      {identity.surface === 'bookmarks' && (
        <div className="flex justify-end">
          <select
            value={bookmarksRestrict}
            onChange={(event) => {
              const restrict = event.target.value === 'private' ? 'private' : 'public'
              setBookmarksRestrict(restrict)
              commitIdentity({ surface: 'bookmarks', restrict })
            }}
            className="rounded-lg border border-vault-border bg-vault-input px-3 py-1.5 text-sm"
          >
            <option value="public">{t('pixiv.visibilityPublic')}</option>
            <option value="private">{t('pixiv.visibilityPrivate')}</option>
          </select>
        </div>
      )}

      {showCredentialGate && (
        <div className="py-16 text-center text-vault-text-secondary">
          <p>{t('pixiv.noCredentials')}</p>
          <button
            type="button"
            onClick={() => router.push('/credentials')}
            className="mt-2 text-vault-accent underline"
          >
            {t('nav.credentials')}
          </button>
        </div>
      )}

      {initialLoading && (
        <div className="flex justify-center py-12">
          <LoadingSpinner />
        </div>
      )}
      {state.status === 'error' && (
        <div className="rounded-lg border border-red-800/50 bg-red-900/20 p-4 text-sm">
          <p className="text-red-400">{t('common.failedToLoad')}</p>
          <button
            type="button"
            onClick={() => void loadMoreRetry()}
            className="mt-2 text-vault-accent"
          >
            {t('common.retry')}
          </button>
        </div>
      )}
      {!showCredentialGate &&
        !initialLoading &&
        state.items.length === 0 &&
        state.status !== 'error' && (
          <p className="py-8 text-center text-vault-text-secondary">{t('pixiv.noResults')}</p>
        )}

      {!showCredentialGate && (
        <VirtualGrid
          items={state.items}
          columns={gridColumns}
          getItemKey={pixivItemKey}
          gap={viewMode === 'list' ? 8 : identity.surface === 'ranking' ? 8 : 12}
          estimateHeight={viewMode === 'list' ? 100 : identity.surface === 'following' ? 180 : 200}
          focusedIndex={focusedIndex}
          onColCountChange={setColCount}
          onRegisterElement={handleRegisterElement}
          onVisibleRangeChange={handleVisibleRange}
          onLayoutChange={handleLayout}
          restoreRequest={restoreRequest}
          onRestoreApplied={handleRestoreApplied}
          renderItem={(item) => {
            if (item.kind === 'user') {
              const preview = item.preview as unknown as PixivUserPreview
              return (
                <UserPreviewCard
                  preview={preview}
                  onOpen={() => openPixivUser(preview.user.id)}
                  onFollow={onFollow}
                />
              )
            }
            if (item.kind === 'ranking') {
              return (
                <RankingCard
                  entry={item.entry}
                  onOpen={() => openPixivItem(item.entry.illust_id)}
                />
              )
            }
            const illust = item.illust as unknown as PixivIllust
            if (identity.surface === 'search')
              return (
                <IllustCard
                  illust={illust}
                  viewMode={viewMode}
                  onNavigate={() => openPixivItem(illust.id)}
                  onBookmark={onBookmark}
                />
              )
            if (identity.surface === 'feed')
              return (
                <IllustCard
                  illust={illust}
                  viewMode={viewMode}
                  onNavigate={() => openPixivItem(illust.id)}
                  onBookmark={onBookmark}
                />
              )
            if (identity.surface === 'bookmarks')
              return (
                <IllustCard
                  illust={illust}
                  viewMode={viewMode}
                  onNavigate={() => openPixivItem(illust.id)}
                  onBookmark={onBookmark}
                />
              )
            return (
              <IllustCard
                illust={illust}
                viewMode={viewMode}
                onNavigate={() => openPixivItem(illust.id)}
                onBookmark={onBookmark}
              />
            )
          }}
          onLoadMore={state.status === 'error' ? undefined : state.hasMore ? loadMore : undefined}
          hasMore={state.hasMore && state.status !== 'error'}
          isLoading={isSessionLoading}
        />
      )}
      {state.items.length > 0 && !state.hasMore && state.status !== 'loading' && (
        <p className="py-4 text-center text-xs text-vault-text-muted">
          {t('browse.noMoreResults')}
        </p>
      )}
    </div>
  )
}

export default function PixivPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[60vh] items-center justify-center">
          <LoadingSpinner size="lg" />
        </div>
      }
    >
      <PixivPageInner />
    </Suspense>
  )
}
