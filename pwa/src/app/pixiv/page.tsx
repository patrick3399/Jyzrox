'use client'

import { useState, useEffect, useRef, Suspense } from 'react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import useSWR from 'swr'
import useSWRInfinite from 'swr/infinite'
import { api } from '@/lib/api'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { VirtualGrid } from '@/components/VirtualGrid'
import { CredentialBanner } from '@/components/CredentialBanner'
import { toast } from 'sonner'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import type { PixivIllust, PixivSearchResult, PixivUserPreview } from '@/lib/types'

// ── Illust card ──────────────────────────────────────────────────────────

function IllustCard({ illust }: { illust: PixivIllust }) {
  const [downloading, setDownloading] = useState(false)
  const [bookmarked, setBookmarked] = useState(illust.is_bookmarked)
  const [bookmarking, setBookmarking] = useState(false)
  const thumbUrl = api.pixiv.imageProxyUrl(illust.image_urls.square_medium)

  const handleDownload = async (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (downloading) return
    setDownloading(true)
    try {
      await api.download.enqueue(`https://www.pixiv.net/artworks/${illust.id}`)
      toast.success(t('browse.addedToQueue'))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToSave'))
    } finally {
      setDownloading(false)
    }
  }

  const handleBookmark = async (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (bookmarking) return
    setBookmarking(true)
    try {
      if (bookmarked) {
        await api.pixiv.deleteBookmark(illust.id)
        setBookmarked(false)
      } else {
        await api.pixiv.addBookmark(illust.id)
        setBookmarked(true)
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToSave'))
    } finally {
      setBookmarking(false)
    }
  }

  return (
    <Link href={`/pixiv/illust/${illust.id}`} className="group block">
      <div className="relative aspect-square overflow-hidden rounded-lg bg-vault-input">
        <img
          src={thumbUrl}
          alt={illust.title}
          className="w-full h-full object-cover transition-transform duration-200 group-hover:scale-105"
          loading="lazy"
          onError={(e) => {
            ;(e.currentTarget as HTMLImageElement).style.display = 'none'
          }}
        />
        {illust.page_count > 1 && (
          <span className="absolute top-1.5 right-1.5 bg-black/70 text-white text-[10px] px-1.5 py-0.5 rounded font-medium">
            {illust.page_count} {t('pixiv.pages')}
          </span>
        )}
        <button
          onClick={handleBookmark}
          disabled={bookmarking}
          className={`absolute top-1.5 left-1.5 opacity-0 group-hover:opacity-100 transition-opacity bg-black/70 text-white text-xs px-1.5 py-0.5 rounded disabled:opacity-50 ${bookmarked ? 'text-yellow-400' : ''}`}
        >
          {bookmarked ? '★' : '☆'}
        </button>
        <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-200" />
        <button
          onClick={handleDownload}
          disabled={downloading}
          className="absolute bottom-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity bg-vault-accent text-white text-xs px-2 py-1 rounded hover:bg-vault-accent/80 disabled:opacity-50"
        >
          {downloading ? t('pixiv.downloading') : t('pixiv.download')}
        </button>
      </div>
      <div className="mt-1.5 px-0.5">
        <p className="text-sm text-vault-text truncate font-medium">{illust.title}</p>
        <p className="text-xs text-vault-text-secondary truncate">{illust.user.name}</p>
        {(illust.total_view > 0 || illust.total_bookmarks > 0) && (
          <div className="flex items-center gap-2 mt-0.5 text-[10px] text-vault-text-secondary">
            <span>{illust.total_view.toLocaleString()} {t('pixiv.views')}</span>
            <span>{illust.total_bookmarks.toLocaleString()} {t('pixiv.bookmarks')}</span>
          </div>
        )}
      </div>
    </Link>
  )
}

// ── Sort/Duration option constants ───────────────────────────────────────

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

// ── SearchResults component ──────────────────────────────────────────────

function SearchResults({
  query,
  credentialsMissing,
  onClear,
}: {
  query: string
  credentialsMissing: boolean
  onClear: () => void
}) {
  const [sort, setSort] = useState('date_desc')
  const [duration, setDuration] = useState('')

  // Map sort values for public API: date_desc→date_d, date_asc→date, popular_desc→popular_d
  const publicOrder = sort === 'date_asc' ? 'date' : sort === 'popular_desc' ? 'popular_d' : 'date_d'

  const getKey = (pageIndex: number, previous: PixivSearchResult | null) => {
    if (!query) return null
    if (pageIndex > 0 && previous?.next_offset === null) return null
    const offset = pageIndex === 0 ? 0 : (previous?.next_offset ?? 0)
    if (credentialsMissing) {
      const page = Math.floor(offset / 60) + 1
      return ['/pixiv/search-public', query, publicOrder, page]
    }
    return ['/pixiv/search', query, sort, duration, offset]
  }

  const { data, size, setSize, isValidating, error } = useSWRInfinite<PixivSearchResult>(
    getKey,
    (key) => {
      if (key[0] === '/pixiv/search-public') {
        const [, word, order, page] = key as [string, string, string, number]
        return api.pixiv.searchPublic({ word, order, page })
      }
      const [, word, s, d, offset] = key as [string, string, string, string, number]
      return api.pixiv.search({
        word,
        sort: s,
        duration: d || undefined,
        offset,
      })
    },
    { revalidateFirstPage: false },
  )

  const allIllusts = data?.flatMap((page) => page.illusts) ?? []
  const hasMore = data ? data[data.length - 1]?.next_offset !== null : false
  const isLoading = !data && isValidating

  return (
    <div className="space-y-4">
      {/* Results header with clear button */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm text-vault-text-secondary">
          <span>{t('browse.resultsFor', { query })}</span>
        </div>
        <button
          onClick={onClear}
          className="text-xs text-vault-text-muted hover:text-vault-text transition-colors"
        >
          {t('browse.clearSearch')}
        </button>
      </div>

      {/* Filters */}
      <div className="flex gap-2 flex-wrap">
        <select
          value={sort}
          onChange={(e) => setSort(e.target.value)}
          className="px-3 py-1.5 rounded-lg bg-vault-input border border-vault-border text-vault-text text-sm focus:outline-none focus:border-vault-accent"
        >
          {SORT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label()}
            </option>
          ))}
        </select>
        {!credentialsMissing && (
          <select
            value={duration}
            onChange={(e) => setDuration(e.target.value)}
            className="px-3 py-1.5 rounded-lg bg-vault-input border border-vault-border text-vault-text text-sm focus:outline-none focus:border-vault-accent"
          >
            {DURATION_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label()}
              </option>
            ))}
          </select>
        )}
      </div>

      {/* Loading / Error / Empty / Results */}
      {isLoading && (
        <div className="flex justify-center py-12">
          <LoadingSpinner />
        </div>
      )}

      {error && (
        <div className="bg-red-900/20 border border-red-800/50 rounded-lg p-4 text-sm">
          <p className="text-red-400">{t('browse.failedLoadResults')}</p>
        </div>
      )}

      {!isLoading && !error && allIllusts.length === 0 && (
        <p className="text-center py-8 text-vault-text-secondary">{t('pixiv.noResults')}</p>
      )}

      <VirtualGrid
        items={allIllusts}
        columns={{ base: 2, sm: 3, md: 4, lg: 5, xl: 6 }}
        gap={12}
        estimateHeight={200}
        renderItem={(illust) => (
          <IllustCard key={illust.id} illust={illust} />
        )}
        onLoadMore={hasMore ? () => setSize(size + 1) : undefined}
        hasMore={hasMore}
        isLoading={isValidating}
      />
    </div>
  )
}

// ── Feed Tab ─────────────────────────────────────────────────────────────

function FeedTab({ credentialsMissing }: { credentialsMissing: boolean }) {
  const getKey = (pageIndex: number, previous: PixivSearchResult | null) => {
    if (credentialsMissing) return null
    if (pageIndex > 0 && previous?.next_offset === null) return null
    const offset = pageIndex === 0 ? 0 : (previous?.next_offset ?? 0)
    return ['/pixiv/following/feed', offset]
  }

  const { data, size, setSize, isValidating, error } = useSWRInfinite<PixivSearchResult>(
    getKey,
    ([, offset]) => api.pixiv.getFollowingFeed(offset as number),
    { revalidateFirstPage: false },
  )

  const allIllusts = data?.flatMap((page) => page.illusts) ?? []
  const hasMore = data ? data[data.length - 1]?.next_offset !== null : false
  const isLoading = !data && isValidating

  if (credentialsMissing) {
    return (
      <div className="text-center py-16 text-vault-text-secondary">
        <p>{t('pixiv.noCredentials')}</p>
        <Link href="/credentials" className="text-vault-accent underline mt-2 inline-block">
          {t('nav.credentials')}
        </Link>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <LoadingSpinner />
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-red-900/20 border border-red-800/50 rounded-lg p-4 text-sm">
        <p className="text-red-400">{t('common.failedToLoad')}</p>
      </div>
    )
  }

  if (allIllusts.length === 0) {
    return <p className="text-center py-8 text-vault-text-secondary">{t('pixiv.noResults')}</p>
  }

  return (
    <div className="space-y-4">
      <VirtualGrid
        items={allIllusts}
        columns={{ base: 2, sm: 3, md: 4, lg: 6, xl: 8 }}
        gap={12}
        estimateHeight={200}
        renderItem={(illust) => (
          <IllustCard key={illust.id} illust={illust} />
        )}
        onLoadMore={hasMore ? () => setSize(size + 1) : undefined}
        hasMore={hasMore}
        isLoading={isValidating}
      />
    </div>
  )
}

// ── UserPreviewCard ───────────────────────────────────────────────────────

function UserPreviewCard({ preview }: { preview: PixivUserPreview }) {
  const [followed, setFollowed] = useState(true) // all users in following list are followed
  const [toggling, setToggling] = useState(false)

  const handleToggleFollow = async (e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    if (toggling) return
    setToggling(true)
    try {
      if (followed) {
        await api.pixiv.unfollowUser(preview.user.id)
        setFollowed(false)
      } else {
        await api.pixiv.followUser(preview.user.id)
        setFollowed(true)
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToSave'))
    } finally {
      setToggling(false)
    }
  }

  return (
    <Link
      href={`/pixiv/user/${preview.user.id}`}
      className="group block rounded-lg bg-vault-card border border-vault-border overflow-hidden hover:border-vault-accent transition-colors"
    >
      {/* Recent works grid */}
      {preview.illusts.length > 0 ? (
        <div className="grid grid-cols-3 gap-0.5">
          {preview.illusts.slice(0, 3).map((illust) => (
            <div key={illust.id} className="relative aspect-square w-full bg-vault-input">
              <img
                src={api.pixiv.imageProxyUrl(illust.image_urls.square_medium)}
                alt=""
                className="absolute inset-0 w-full h-full object-cover"
                onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none' }}
              />
            </div>
          ))}
        </div>
      ) : (
        <div className="flex items-center justify-center bg-vault-input" style={{ aspectRatio: '3/1' }}>
          <span className="text-[10px] text-vault-text-muted uppercase tracking-widest">{t('pixiv.noWorks')}</span>
        </div>
      )}
      {/* Artist info row */}
      <div className="flex items-center gap-2 p-2">
        {preview.user.profile_image ? (
          <img
            src={api.pixiv.imageProxyUrl(preview.user.profile_image)}
            alt={preview.user.name}
            className="w-7 h-7 rounded-full object-cover bg-vault-input shrink-0"
            onError={(e) => { (e.currentTarget as HTMLImageElement).style.display = 'none' }}
          />
        ) : (
          <div className="w-7 h-7 rounded-full bg-vault-input shrink-0" />
        )}
        <p className="text-xs font-medium text-vault-text truncate flex-1">
          {preview.user.name}
        </p>
        <button
          onClick={handleToggleFollow}
          disabled={toggling}
          className={`shrink-0 text-[10px] px-1.5 py-0.5 rounded transition-colors disabled:opacity-50 ${
            followed
              ? 'text-vault-text-secondary hover:text-red-400'
              : 'text-vault-accent'
          }`}
        >
          {toggling ? '...' : followed ? t('pixiv.unfollow') : t('pixiv.follow')}
        </button>
      </div>
    </Link>
  )
}

// ── Following Tab ────────────────────────────────────────────────────────

function FollowingTab({ credentialsMissing }: { credentialsMissing: boolean }) {
  const getKey = (pageIndex: number, previous: { user_previews: PixivUserPreview[]; next_offset: number | null } | null) => {
    if (credentialsMissing) return null
    if (pageIndex > 0 && previous?.next_offset === null) return null
    const offset = pageIndex === 0 ? 0 : (previous?.next_offset ?? 0)
    return ['/pixiv/following', offset]
  }

  const { data, size, setSize, isValidating, error } = useSWRInfinite(
    getKey,
    ([, offset]) => api.pixiv.getFollowing('public', offset as number),
    { revalidateFirstPage: false },
  )

  const allPreviews = data?.flatMap((page) => page.user_previews) ?? []
  const hasMore = data ? data[data.length - 1]?.next_offset !== null : false
  const isLoading = !data && isValidating

  if (credentialsMissing) {
    return (
      <div className="text-center py-16 text-vault-text-secondary">
        <p>{t('pixiv.noCredentials')}</p>
        <Link href="/credentials" className="text-vault-accent underline mt-2 inline-block">
          {t('nav.credentials')}
        </Link>
      </div>
    )
  }

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <LoadingSpinner />
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-red-900/20 border border-red-800/50 rounded-lg p-4 text-sm">
        <p className="text-red-400">{t('common.failedToLoad')}</p>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {allPreviews.length === 0 && !isValidating && (
        <p className="text-center py-8 text-vault-text-secondary">{t('pixiv.noResults')}</p>
      )}

      <VirtualGrid
        items={allPreviews}
        columns={{ base: 2, sm: 3, md: 4, lg: 5 }}
        gap={12}
        estimateHeight={180}
        renderItem={(preview: PixivUserPreview) => (
          <UserPreviewCard key={preview.user.id} preview={preview} />
        )}
        onLoadMore={hasMore ? () => setSize(size + 1) : undefined}
        hasMore={hasMore}
        isLoading={isValidating}
      />
    </div>
  )
}

// ── Bookmarks Tab ────────────────────────────────────────────────────────

function BookmarksTab({ credentialsMissing }: { credentialsMissing: boolean }) {
  const [restrict, setRestrict] = useState('public')
  const getKey = (pageIndex: number, previous: PixivSearchResult | null) => {
    if (credentialsMissing) return null
    if (pageIndex > 0 && previous?.next_offset === null) return null
    const offset = pageIndex === 0 ? 0 : (previous?.next_offset ?? 0)
    return ['/pixiv/bookmarks', restrict, offset]
  }

  const { data, size, setSize, isValidating, error } = useSWRInfinite<PixivSearchResult>(
    getKey,
    ([, r, offset]) => api.pixiv.getMyBookmarks(r as string, offset as number),
    { revalidateFirstPage: false },
  )

  const allIllusts = data?.flatMap((page) => page.illusts) ?? []
  const hasMore = data ? data[data.length - 1]?.next_offset !== null : false
  const isLoading = !data && isValidating

  if (credentialsMissing) {
    return (
      <div className="text-center py-16 text-vault-text-secondary">
        <p>{t('pixiv.noCredentials')}</p>
        <Link href="/credentials" className="text-vault-accent underline mt-2 inline-block">
          {t('nav.credentials')}
        </Link>
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end gap-2">
        <select
          value={restrict}
          onChange={(e) => setRestrict(e.target.value)}
          className="px-3 py-1.5 rounded-lg bg-vault-input border border-vault-border text-vault-text text-sm focus:outline-none focus:border-vault-accent"
        >
          <option value="public">{t('browse.rankingAll') || 'Public'}</option>
          <option value="private">Private</option>
        </select>
      </div>

      {isLoading && (
        <div className="flex justify-center py-12">
          <LoadingSpinner />
        </div>
      )}

      {error && (
        <div className="bg-red-900/20 border border-red-800/50 rounded-lg p-4 text-sm">
          <p className="text-red-400">{t('common.failedToLoad')}</p>
        </div>
      )}

      {!isLoading && !error && allIllusts.length === 0 && (
        <p className="text-center py-8 text-vault-text-secondary">{t('pixiv.noResults')}</p>
      )}

      <VirtualGrid
        items={allIllusts}
        columns={{ base: 2, sm: 3, md: 4, lg: 6, xl: 8 }}
        gap={12}
        estimateHeight={200}
        renderItem={(illust) => (
          <IllustCard key={illust.id} illust={illust} />
        )}
        onLoadMore={hasMore ? () => setSize(size + 1) : undefined}
        hasMore={hasMore}
        isLoading={isValidating}
      />
    </div>
  )
}

// ── Ranking Tab ───────────────────────────────────────────────────────────

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

function RankingTab({ credentialsMissing }: { credentialsMissing: boolean }) {
  const [mode, setMode] = useState('daily')
  const [content, setContent] = useState('all')
  const [r18, setR18] = useState(false)

  // R18 only supports daily/weekly; reset mode if incompatible
  const handleR18Toggle = () => {
    setR18((prev) => {
      const next = !prev
      if (next && mode !== 'daily' && mode !== 'weekly') {
        setMode('daily')
      }
      return next
    })
  }

  type RankingPage = {
    contents: Array<Record<string, unknown>>
    rank_total: number
    mode: string
    content: string
    date: string
    page: number
    prev_date: string | null
    next_date: string | null
    has_next?: boolean
  }

  const getKey = (pageIndex: number, previous: RankingPage | null) => {
    if (pageIndex > 0 && previous && previous.contents.length < 50) return null
    const effectiveMode = r18 ? `${mode}_r18` : mode
    return ['/pixiv/ranking', effectiveMode, r18 ? 'all' : content, pageIndex + 1]
  }

  const { data, size, setSize, isValidating, error } = useSWRInfinite<RankingPage>(
    getKey,
    ([, m, c, p]) => api.pixiv.ranking({ mode: m as string, content: c as string, page: p as number }),
    { revalidateFirstPage: false },
  )

  const allContents = data?.flatMap((page) => page.contents) ?? []
  const lastPage = data?.[data.length - 1]
  const hasMore = lastPage
    ? (lastPage as Record<string, unknown>).has_next !== undefined
      ? Boolean((lastPage as Record<string, unknown>).has_next)
      : (lastPage.contents.length ?? 0) >= 50
    : false
  const isLoading = !data && isValidating

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex gap-2 flex-wrap">
        <select
          value={mode}
          onChange={(e) => setMode(e.target.value)}
          className="px-3 py-1.5 rounded-lg bg-vault-input border border-vault-border text-vault-text text-sm focus:outline-none focus:border-vault-accent"
        >
          {RANKING_MODES.filter((o) => !r18 || o.value === 'daily' || o.value === 'weekly').map((o) => (
            <option key={o.value} value={o.value}>
              {o.label()}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={handleR18Toggle}
          disabled={credentialsMissing}
          title={credentialsMissing ? t('browse.r18RequiresCredentials') : undefined}
          className={[
            'px-3 py-1.5 rounded-lg text-sm font-medium border transition-colors',
            r18
              ? 'bg-pink-600 border-pink-500 text-white'
              : 'bg-vault-input border-vault-border text-vault-text-secondary hover:text-vault-text',
            credentialsMissing ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer',
          ].join(' ')}
        >
          {t('browse.r18')}
        </button>
        {!r18 && (
          <select
            value={content}
            onChange={(e) => setContent(e.target.value)}
            className="px-3 py-1.5 rounded-lg bg-vault-input border border-vault-border text-vault-text text-sm focus:outline-none focus:border-vault-accent"
          >
            {RANKING_CONTENT.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label()}
              </option>
            ))}
          </select>
        )}
      </div>

      {isLoading && (
        <div className="flex justify-center py-12">
          <LoadingSpinner />
        </div>
      )}
      {error && (
        <div className="bg-red-900/20 border border-red-800/50 rounded-lg p-4 text-sm">
          <p className="text-red-400">{t('browse.failedLoadResults')}</p>
        </div>
      )}

      {!isLoading && !error && allContents.length === 0 && (
        <p className="text-center py-8 text-vault-text-secondary">{t('pixiv.noResults')}</p>
      )}

      <VirtualGrid
        items={allContents}
        columns={{ base: 3, sm: 4, md: 5, lg: 7, xl: 8, xxl: 10 }}
        gap={8}
        estimateHeight={180}
        renderItem={(item: Record<string, unknown>) => {
          const illustId = item.illust_id as number
          const title = item.title as string
          const userName = item.user_name as string
          const thumbUrl = api.pixiv.imageProxyUrl(item.url as string)
          return (
            <Link key={illustId} href={`/pixiv/illust/${illustId}`} className="group block">
              <div className="relative aspect-square overflow-hidden rounded-lg bg-vault-input">
                <img
                  src={thumbUrl}
                  alt={title}
                  className="w-full h-full object-cover transition-transform duration-200 group-hover:scale-105"
                  loading="lazy"
                  onError={(e) => {
                    ;(e.currentTarget as HTMLImageElement).style.display = 'none'
                  }}
                />
                <div className="absolute top-1.5 left-1.5 bg-black/70 text-white text-[10px] px-1.5 py-0.5 rounded font-bold">
                  #{item.rank as number}
                </div>
              </div>
              <div className="mt-1.5 px-0.5">
                <p className="text-sm text-vault-text truncate font-medium">{title}</p>
                <p className="text-xs text-vault-text-secondary truncate">{userName}</p>
              </div>
            </Link>
          )
        }}
        onLoadMore={hasMore ? () => setSize(size + 1) : undefined}
        hasMore={hasMore}
        isLoading={isValidating}
      />
    </div>
  )
}

// ── Main Page ────────────────────────────────────────────────────────────

type Tab = 'feed' | 'following' | 'ranking' | 'bookmarks'

function PixivPageInner() {
  useLocale()
  const router = useRouter()
  const searchParams = useSearchParams()
  const rawTab = searchParams.get('tab') as Tab | null
  const initialTab: Tab =
    rawTab === 'feed' || rawTab === 'following' || rawTab === 'bookmarks' ? rawTab : 'ranking'
  const [activeTab, setActiveTab] = useState<Tab>(initialTab)

  const handleTabChange = (tab: Tab) => {
    setActiveTab(tab)
    router.replace(`/pixiv?tab=${tab}`, { scroll: false })
  }

  // Search state
  const [searchQuery, setSearchQuery] = useState('')
  const [submittedQuery, setSubmittedQuery] = useState('')
  const searchInputRef = useRef<HTMLInputElement>(null)

  // Check credentials
  const { data: credData, isLoading: credLoading } = useSWR('/api/settings/credentials', () =>
    api.settings.getCredentials(),
  )
  const credentialsMissing = credLoading ? false : !credData?.['pixiv']?.configured

  // Dismiss search on Escape key
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && submittedQuery) {
        setSubmittedQuery('')
        setSearchQuery('')
      }
    }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [submittedQuery])

  const handleSearchSubmit = () => {
    if (searchQuery.trim()) {
      setSubmittedQuery(searchQuery.trim())
    }
  }

  const handleClearSearch = () => {
    setSubmittedQuery('')
    setSearchQuery('')
    searchInputRef.current?.focus()
  }

  return (
    <div className="space-y-4">
      {credentialsMissing && <CredentialBanner source="pixiv" />}

      {/* Search bar — always visible */}
      <div className="flex gap-2">
        <input
          ref={searchInputRef}
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleSearchSubmit()
            else if (e.key === 'Escape') handleClearSearch()
          }}
          placeholder={t('pixiv.searchPlaceholder')}
          className="flex-1 bg-vault-card border border-vault-border rounded-lg px-4 py-2.5 text-sm text-vault-text placeholder-vault-text-muted focus:outline-none focus:border-vault-accent transition-colors"
        />
        <button
          onClick={handleSearchSubmit}
          className="px-4 py-2.5 bg-vault-accent hover:bg-vault-accent/90 rounded-lg text-white text-sm font-medium transition-colors shrink-0"
        >
          {t('pixiv.search')}
        </button>
      </div>

      {/* Search results mode */}
      {submittedQuery ? (
        <SearchResults
          query={submittedQuery}
          credentialsMissing={credentialsMissing}
          onClear={handleClearSearch}
        />
      ) : (
        <>
          {/* Tab bar — Feed & Following only shown when credentials available */}
          <div className="flex gap-1 border-b border-vault-border overflow-x-auto scrollbar-hide">
            <button
              onClick={() => handleTabChange('ranking')}
              className={`shrink-0 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === 'ranking'
                  ? 'border-vault-accent text-vault-text'
                  : 'border-transparent text-vault-text-muted hover:text-vault-text'
              }`}
            >
              {t('browse.ranking')}
            </button>
            {!credentialsMissing && (
              <>
                <button
                  onClick={() => handleTabChange('feed')}
                  className={`shrink-0 ml-3 md:ml-auto px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                    activeTab === 'feed'
                      ? 'border-blue-400 text-vault-text'
                      : 'border-transparent text-vault-text-muted hover:text-vault-text'
                  }`}
                >
                  {t('pixiv.feedTab')}
                </button>
                <button
                  onClick={() => handleTabChange('following')}
                  className={`shrink-0 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                    activeTab === 'following'
                      ? 'border-[#e91e63] text-vault-text'
                      : 'border-transparent text-vault-text-muted hover:text-vault-text'
                  }`}
                >
                  {t('pixiv.followingTab')}
                </button>
                <button
                  onClick={() => handleTabChange('bookmarks')}
                  className={`shrink-0 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                    activeTab === 'bookmarks'
                      ? 'border-[#ff9800] text-vault-text'
                      : 'border-transparent text-vault-text-muted hover:text-vault-text'
                  }`}
                >
                  {t('pixiv.bookmarks') || 'Bookmarks'}
                </button>
              </>
            )}
          </div>

          {/* Tab content */}
          {activeTab === 'ranking' && <RankingTab credentialsMissing={credentialsMissing} />}
          {activeTab === 'feed' && !credentialsMissing && <FeedTab credentialsMissing={false} />}
          {activeTab === 'following' && !credentialsMissing && <FollowingTab credentialsMissing={false} />}
          {activeTab === 'bookmarks' && !credentialsMissing && <BookmarksTab credentialsMissing={false} />}
        </>
      )}
    </div>
  )
}

export default function PixivPage() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center min-h-[60vh]">
          <LoadingSpinner size="lg" />
        </div>
      }
    >
      <PixivPageInner />
    </Suspense>
  )
}
