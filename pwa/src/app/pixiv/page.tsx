'use client'

import { useState, useEffect, useRef, Suspense } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import useSWR from 'swr'
import useSWRInfinite from 'swr/infinite'
import { api } from '@/lib/api'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { VirtualGrid } from '@/components/VirtualGrid'
import { CredentialBanner } from '@/components/CredentialBanner'
import { toast } from 'sonner'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import type { PixivIllust, PixivSearchResult, FollowedArtist } from '@/lib/types'

// ── Illust card ──────────────────────────────────────────────────────────

function IllustCard({ illust }: { illust: PixivIllust }) {
  const [downloading, setDownloading] = useState(false)
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

// ── Following Tab ────────────────────────────────────────────────────────

function FollowingTab({ credentialsMissing }: { credentialsMissing: boolean }) {
  const { data, error, isLoading, mutate } = useSWR(
    credentialsMissing ? null : '/artists/followed/pixiv',
    () => api.artists.listFollowed({ source: 'pixiv', limit: 100 }),
  )

  const [checkingUpdates, setCheckingUpdates] = useState(false)

  const handleUnfollow = async (artistId: string) => {
    try {
      await api.artists.unfollow(artistId, 'pixiv')
      toast.success(t('pixiv.unfollow'))
      mutate()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToSave'))
    }
  }

  const handleToggleAutoDownload = async (artistId: string, current: boolean) => {
    try {
      await api.artists.patchFollow(artistId, { auto_download: !current }, 'pixiv')
      mutate()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToSave'))
    }
  }

  const handleCheckUpdates = async () => {
    setCheckingUpdates(true)
    try {
      await api.artists.checkUpdates()
      toast.success(t('pixiv.checkUpdates'))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToSave'))
    } finally {
      setCheckingUpdates(false)
    }
  }

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

  const artists = data?.artists ?? []

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-sm text-vault-text-secondary">
          {artists.length} {t('pixiv.following')}
        </p>
        <button
          onClick={handleCheckUpdates}
          disabled={checkingUpdates}
          className="px-4 py-1.5 rounded-lg bg-vault-card border border-vault-border text-vault-text text-sm hover:bg-vault-card-hover transition-colors disabled:opacity-50"
        >
          {checkingUpdates ? t('pixiv.loading') : t('pixiv.checkUpdates')}
        </button>
      </div>

      {artists.length === 0 && (
        <p className="text-center py-8 text-vault-text-secondary">{t('pixiv.noResults')}</p>
      )}

      <div className="space-y-2">
        {artists.map((artist: FollowedArtist) => (
          <div
            key={artist.id}
            className="flex items-center gap-3 p-3 rounded-lg bg-vault-card border border-vault-border"
          >
            {artist.artist_avatar ? (
              <img
                src={api.pixiv.imageProxyUrl(artist.artist_avatar)}
                alt={artist.artist_name ?? ''}
                className="w-10 h-10 rounded-full object-cover bg-vault-input shrink-0"
                onError={(e) => {
                  ;(e.currentTarget as HTMLImageElement).style.display = 'none'
                }}
              />
            ) : (
              <div className="w-10 h-10 rounded-full bg-vault-input shrink-0" />
            )}

            <div className="flex-1 min-w-0">
              <Link
                href={`/pixiv/user/${artist.artist_id}`}
                className="text-sm font-medium text-vault-text hover:text-vault-accent truncate block"
              >
                {artist.artist_name ?? artist.artist_id}
              </Link>
              {artist.last_checked_at && (
                <p className="text-[11px] text-vault-text-secondary">
                  {new Date(artist.last_checked_at).toLocaleDateString()}
                </p>
              )}
            </div>

            <div className="flex items-center gap-2 shrink-0">
              <label className="flex items-center gap-1.5 text-xs text-vault-text-secondary cursor-pointer">
                <input
                  type="checkbox"
                  checked={artist.auto_download}
                  onChange={() => handleToggleAutoDownload(artist.artist_id, artist.auto_download)}
                  className="w-3.5 h-3.5 accent-vault-accent"
                />
                {t('pixiv.autoDownload')}
              </label>
              <button
                onClick={() => handleUnfollow(artist.artist_id)}
                className="px-2.5 py-1 rounded text-xs bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors"
              >
                {t('pixiv.unfollow')}
              </button>
            </div>
          </div>
        ))}
      </div>
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

function RankingTab() {
  const [mode, setMode] = useState('daily')
  const [content, setContent] = useState('all')
  const [page, setPage] = useState(1)

  const { data, error, isLoading } = useSWR(
    ['/pixiv/ranking', mode, content, page],
    () => api.pixiv.ranking({ mode, content, page }),
  )

  const contents = data?.contents ?? []

  return (
    <div className="space-y-4">
      {/* Filters */}
      <div className="flex gap-2 flex-wrap">
        <select
          value={mode}
          onChange={(e) => { setMode(e.target.value); setPage(1) }}
          className="px-3 py-1.5 rounded-lg bg-vault-input border border-vault-border text-vault-text text-sm focus:outline-none focus:border-vault-accent"
        >
          {RANKING_MODES.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label()}
            </option>
          ))}
        </select>
        <select
          value={content}
          onChange={(e) => { setContent(e.target.value); setPage(1) }}
          className="px-3 py-1.5 rounded-lg bg-vault-input border border-vault-border text-vault-text text-sm focus:outline-none focus:border-vault-accent"
        >
          {RANKING_CONTENT.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label()}
            </option>
          ))}
        </select>
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

      {!isLoading && !error && contents.length === 0 && (
        <p className="text-center py-8 text-vault-text-secondary">{t('pixiv.noResults')}</p>
      )}

      {contents.length > 0 && (
        <>
          <VirtualGrid
            items={contents}
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
          />

          {/* Pagination */}
          <div className="flex justify-center gap-2 pt-4">
            <button
              onClick={() => setPage(Math.max(1, page - 1))}
              disabled={page <= 1}
              className="px-4 py-2 rounded-lg bg-vault-card border border-vault-border text-vault-text text-sm hover:bg-vault-card-hover disabled:opacity-50"
            >
              {t('common.prev')}
            </button>
            <span className="px-4 py-2 text-sm text-vault-text-secondary">{page}</span>
            <button
              onClick={() => setPage(page + 1)}
              disabled={contents.length < 50}
              className="px-4 py-2 rounded-lg bg-vault-card border border-vault-border text-vault-text text-sm hover:bg-vault-card-hover disabled:opacity-50"
            >
              {t('common.next')}
            </button>
          </div>
        </>
      )}
    </div>
  )
}

// ── Main Page ────────────────────────────────────────────────────────────

type Tab = 'feed' | 'following' | 'ranking'

function PixivPageInner() {
  useLocale()
  const searchParams = useSearchParams()
  const rawTab = searchParams.get('tab') as Tab | null
  const initialTab: Tab =
    rawTab === 'feed' || rawTab === 'following' ? rawTab : 'ranking'
  const [activeTab, setActiveTab] = useState<Tab>(initialTab)

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
              onClick={() => setActiveTab('ranking')}
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
                  onClick={() => setActiveTab('feed')}
                  className={`shrink-0 ml-3 md:ml-auto px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                    activeTab === 'feed'
                      ? 'border-blue-400 text-vault-text'
                      : 'border-transparent text-vault-text-muted hover:text-vault-text'
                  }`}
                >
                  {t('pixiv.feedTab')}
                </button>
                <button
                  onClick={() => setActiveTab('following')}
                  className={`shrink-0 px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                    activeTab === 'following'
                      ? 'border-[#e91e63] text-vault-text'
                      : 'border-transparent text-vault-text-muted hover:text-vault-text'
                  }`}
                >
                  {t('pixiv.followingTab')}
                </button>
              </>
            )}
          </div>

          {/* Tab content */}
          {activeTab === 'ranking' && <RankingTab />}
          {activeTab === 'feed' && !credentialsMissing && <FeedTab credentialsMissing={false} />}
          {activeTab === 'following' && !credentialsMissing && <FollowingTab credentialsMissing={false} />}
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
