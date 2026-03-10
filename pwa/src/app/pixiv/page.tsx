'use client'

import { useState, Suspense } from 'react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import useSWR from 'swr'
import useSWRInfinite from 'swr/infinite'
import { api } from '@/lib/api'
import { LoadingSpinner } from '@/components/LoadingSpinner'
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
        <div className="flex items-center gap-2 mt-0.5 text-[10px] text-vault-text-secondary">
          <span>{illust.total_view.toLocaleString()} {t('pixiv.views')}</span>
          <span>{illust.total_bookmarks.toLocaleString()} {t('pixiv.bookmarks')}</span>
        </div>
      </div>
    </Link>
  )
}

// ── Search Tab ───────────────────────────────────────────────────────────

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

function SearchTab({ credentialsMissing }: { credentialsMissing: boolean }) {
  const [query, setQuery] = useState('')
  const [submittedQuery, setSubmittedQuery] = useState('')
  const [sort, setSort] = useState('date_desc')
  const [duration, setDuration] = useState('')

  const getKey = (pageIndex: number, previous: PixivSearchResult | null) => {
    if (!submittedQuery) return null
    if (pageIndex > 0 && previous?.next_offset === null) return null
    const offset = pageIndex === 0 ? 0 : (previous?.next_offset ?? 0)
    return ['/pixiv/search', submittedQuery, sort, duration, offset]
  }

  const { data, size, setSize, isValidating, error } = useSWRInfinite<PixivSearchResult>(
    getKey,
    ([, word, s, d, offset]) =>
      api.pixiv.search({
        word: word as string,
        sort: s as string,
        duration: (d as string) || undefined,
        offset: offset as number,
      }),
    { revalidateFirstPage: false },
  )

  const allIllusts = data?.flatMap((page) => page.illusts) ?? []
  const hasMore = data ? data[data.length - 1]?.next_offset !== null : false
  const isLoading = !data && isValidating

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    if (!query.trim()) return
    setSubmittedQuery(query.trim())
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

  return (
    <div className="space-y-4">
      {/* Search form */}
      <form onSubmit={handleSearch} className="flex gap-2">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t('pixiv.searchPlaceholder')}
          className="flex-1 px-3 py-2 rounded-lg bg-vault-input border border-vault-border text-vault-text placeholder-vault-text-secondary focus:outline-none focus:border-vault-accent text-sm"
        />
        <button
          type="submit"
          className="px-4 py-2 rounded-lg bg-vault-accent text-white text-sm font-medium hover:bg-vault-accent/80 transition-colors"
        >
          {t('pixiv.search')}
        </button>
      </form>

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
      </div>

      {/* Results */}
      {isLoading && (
        <div className="flex justify-center py-12">
          <LoadingSpinner />
        </div>
      )}

      {error && (
        <p className="text-center py-8 text-red-400">{t('browse.failedLoadResults')}</p>
      )}

      {!isLoading && !error && submittedQuery && allIllusts.length === 0 && (
        <p className="text-center py-8 text-vault-text-secondary">{t('pixiv.noResults')}</p>
      )}

      {allIllusts.length > 0 && (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
            {allIllusts.map((illust) => (
              <IllustCard key={illust.id} illust={illust} />
            ))}
          </div>

          {hasMore && (
            <div className="flex justify-center pt-4">
              <button
                onClick={() => setSize(size + 1)}
                disabled={isValidating}
                className="px-6 py-2 rounded-lg bg-vault-card border border-vault-border text-vault-text text-sm hover:bg-vault-card-hover transition-colors disabled:opacity-50"
              >
                {isValidating ? t('pixiv.loading') : t('pixiv.loadMore')}
              </button>
            </div>
          )}
        </>
      )}
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
    return <p className="text-center py-8 text-red-400">{t('common.failedToLoad')}</p>
  }

  if (allIllusts.length === 0) {
    return <p className="text-center py-8 text-vault-text-secondary">{t('pixiv.noResults')}</p>
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
        {allIllusts.map((illust) => (
          <IllustCard key={illust.id} illust={illust} />
        ))}
      </div>

      {hasMore && (
        <div className="flex justify-center pt-4">
          <button
            onClick={() => setSize(size + 1)}
            disabled={isValidating}
            className="px-6 py-2 rounded-lg bg-vault-card border border-vault-border text-vault-text text-sm hover:bg-vault-card-hover transition-colors disabled:opacity-50"
          >
            {isValidating ? t('pixiv.loading') : t('pixiv.loadMore')}
          </button>
        </div>
      )}
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
    return <p className="text-center py-8 text-red-400">{t('common.failedToLoad')}</p>
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

// ── Main Page ────────────────────────────────────────────────────────────

type Tab = 'search' | 'feed' | 'following'

function PixivPageInner() {
  useLocale()
  const searchParams = useSearchParams()
  const initialTab = (searchParams.get('tab') as Tab | null) ?? 'search'
  const [activeTab, setActiveTab] = useState<Tab>(initialTab)

  // Check credentials
  const { data: credData, isLoading: credLoading } = useSWR('/api/settings/credentials', () =>
    api.settings.getCredentials(),
  )
  const credentialsMissing = credLoading ? false : !credData?.['pixiv']?.configured

  const tabs: { key: Tab; label: () => string }[] = [
    { key: 'search', label: () => t('pixiv.searchTab') },
    { key: 'feed', label: () => t('pixiv.feedTab') },
    { key: 'following', label: () => t('pixiv.followingTab') },
  ]

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold text-vault-text">{t('pixiv.title')}</h1>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-vault-border">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`px-4 py-2.5 text-sm font-medium transition-colors border-b-2 -mb-px ${
              activeTab === tab.key
                ? 'border-vault-accent text-vault-accent'
                : 'border-transparent text-vault-text-secondary hover:text-vault-text'
            }`}
          >
            {tab.label()}
          </button>
        ))}
      </div>

      {/* Tab content */}
      {activeTab === 'search' && <SearchTab credentialsMissing={credentialsMissing} />}
      {activeTab === 'feed' && <FeedTab credentialsMissing={credentialsMissing} />}
      {activeTab === 'following' && <FollowingTab credentialsMissing={credentialsMissing} />}
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
