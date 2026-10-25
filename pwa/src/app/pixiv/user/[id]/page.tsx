'use client'

import { useState, useEffect } from 'react'
import { use } from 'react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import useSWR from 'swr'
import useSWRInfinite from 'swr/infinite'
import { api } from '@/lib/api'
import { BackButton } from '@/components/BackButton'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { useScrollPositionRestore } from '@/hooks/useScrollRestore'
import { commitBrowseUrl } from '@/lib/browse/browseHistory'
import { smartBack } from '@/lib/navBack'
import { toast } from 'sonner'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { ArrowLeft, ExternalLink } from 'lucide-react'
import type { PixivIllust, PixivSearchResult } from '@/lib/types'

type UserTab = 'works' | 'bookmarks'

// Where the page was scrolled to when the user left through a link, so
// artist -> artwork -> back lands on the same card. Kept per artist and
// sub-tab, consumed once on the next mount.
const scrollStorageKey = (userId: number, tab: UserTab) => `pixiv_user_scroll:${userId}:${tab}`

function readSavedScroll(key: string): number | null {
  if (typeof window === 'undefined') return null
  try {
    const raw = window.sessionStorage.getItem(key)
    if (raw === null) return null
    const value = Number(raw)
    return Number.isFinite(value) && value >= 0 ? value : null
  } catch {
    return null
  }
}

function writeSavedScroll(key: string, scrollY: number): void {
  try {
    window.sessionStorage.setItem(key, String(Math.round(scrollY)))
  } catch {
    // Best effort: without it back simply opens at the top.
  }
}

function clearSavedScroll(key: string): void {
  try {
    window.sessionStorage.removeItem(key)
  } catch {
    // Best effort.
  }
}

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
        <div className="absolute inset-0 bg-gradient-to-t from-black/70 via-transparent to-transparent opacity-100 can-hover:opacity-0 can-hover:group-hover:opacity-100 transition-opacity duration-200" />
        <button
          onClick={handleDownload}
          disabled={downloading}
          className="absolute bottom-2 right-2 opacity-100 can-hover:opacity-0 can-hover:group-hover:opacity-100 transition-opacity bg-vault-accent text-white text-xs px-2 py-1 rounded hover:bg-vault-accent/80 disabled:opacity-50"
        >
          {downloading ? t('pixiv.downloading') : t('pixiv.download')}
        </button>
      </div>
      <p className="mt-1 text-xs text-vault-text truncate px-0.5">{illust.title}</p>
    </Link>
  )
}

export default function UserProfilePage({ params }: { params: Promise<{ id: string }> }) {
  useLocale()
  const router = useRouter()
  const { id } = use(params)
  const userId = parseInt(id, 10)

  const validId = !isNaN(userId)

  // User profile + first batch of recent works
  const {
    data: userResult,
    error,
    isLoading,
  } = useSWR(
    validId ? `/api/pixiv/user/${userId}` : null,
    (_, { signal }: { signal?: AbortSignal } = {}) => api.pixiv.getUser(userId, { signal }),
  )

  const [isFollowing, setIsFollowing] = useState(false)
  const [followLoading, setFollowLoading] = useState(false)
  const [collectionLoading, setCollectionLoading] = useState(false)
  const { data: collection, mutate: mutateCollection } = useSWR(
    validId ? `/api/pixiv/user/${userId}/collection` : null,
    (_, { signal }: { signal?: AbortSignal } = {}) => api.pixiv.getUserCollection(userId, { signal }),
    { refreshInterval: (data) => (data?.job_id ? 3000 : 0) },
  )

  // The sub-tab lives in the URL (`?tab=bookmarks`; works is the bare URL) so
  // it survives artist -> artwork -> back and follows back/forward.
  const searchParams = useSearchParams()
  const activeTab: UserTab = searchParams.get('tab') === 'bookmarks' ? 'bookmarks' : 'works'
  const scrollKey = scrollStorageKey(userId, activeTab)

  const handleTabChange = (tab: UserTab) => {
    if (tab === activeTab) return
    // Same-page transition: write the URL directly rather than through the
    // router (FE-T17), and replace so a tab is not a history entry.
    commitBrowseUrl(
      tab === 'bookmarks' ? `/pixiv/user/${userId}?tab=bookmarks` : `/pixiv/user/${userId}`,
      'replace',
    )
  }

  // Bookmarks are paged by Pixiv's `max_bookmark_id` cursor, which the API hands
  // back as `next_offset`: the only valid way to the next page is that value,
  // so pages append (like works) instead of stepping a numeric offset.
  const getBookmarksKey = (pageIndex: number, previous: PixivSearchResult | null) => {
    if (activeTab !== 'bookmarks' || !validId) return null
    const cursor = pageIndex === 0 ? 0 : previous?.next_offset
    if (cursor === null || cursor === undefined) return null
    return ['pixiv-user-bookmarks', userId, cursor]
  }

  const {
    data: bookmarksData,
    size: bookmarksSize,
    setSize: setBookmarksSize,
    isLoading: bookmarksInitialLoading,
    isValidating: bookmarksLoading,
  } = useSWRInfinite<PixivSearchResult>(
    getBookmarksKey,
    ([, uid, cursor], { signal }: { signal?: AbortSignal } = {}) =>
      api.pixiv.getUserBookmarks(uid as number, cursor as number, { signal }),
    { revalidateFirstPage: false },
  )

  useEffect(() => {
    if (userResult?.user.is_followed !== undefined) {
      setIsFollowing(userResult.user.is_followed)
    }
  }, [userResult?.user.is_followed])

  const handleToggleFollow = async () => {
    if (followLoading) return
    setFollowLoading(true)
    try {
      if (isFollowing) {
        await api.pixiv.unfollowUser(userId)
        setIsFollowing(false)
      } else {
        await api.pixiv.followUser(userId)
        setIsFollowing(true)
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToSave'))
    } finally {
      setFollowLoading(false)
    }
  }

  const handleCollectionSync = async (fullReconcile = false) => {
    if (collectionLoading) return
    if (!collection?.gallery_id) {
      const count = (userResult?.user.total_illusts ?? 0) + (userResult?.user.total_manga ?? 0)
      if (!confirm(t('pixiv.collectionConfirm', { count: String(count) }))) return
    } else if (fullReconcile && !confirm(t('pixiv.collectionReconcileConfirm'))) {
      return
    }
    setCollectionLoading(true)
    try {
      await api.pixiv.syncUserCollection(userId, fullReconcile)
      toast.success(t('pixiv.collectionQueued'))
      await mutateCollection()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToSave'))
    } finally {
      setCollectionLoading(false)
    }
  }

  const handleToggleSubscription = async () => {
    if (collectionLoading) return
    setCollectionLoading(true)
    try {
      if (collection?.subscribed) await api.pixiv.unsubscribeUserCollection(userId)
      else await api.pixiv.subscribeUserCollection(userId)
      await mutateCollection()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToSave'))
    } finally {
      setCollectionLoading(false)
    }
  }

  // Paginated all works
  const getKey = (pageIndex: number, previous: PixivSearchResult | null) => {
    if (!userResult) return null
    if (pageIndex > 0 && previous?.next_offset === null) return null
    const offset = pageIndex === 0 ? 0 : (previous?.next_offset ?? 0)
    return [`/pixiv/user/${userId}/illusts`, offset]
  }

  const {
    data: worksData,
    size,
    setSize,
    isValidating: worksLoading,
  } = useSWRInfinite<PixivSearchResult>(
    getKey,
    ([, offset], { signal }: { signal?: AbortSignal } = {}) =>
      api.pixiv.getUserIllusts(userId, offset as number, { signal }),
    { revalidateFirstPage: false },
  )

  const allWorks = worksData?.flatMap((page) => page.illusts) ?? []
  const hasMoreWorks = worksData ? worksData[worksData.length - 1]?.next_offset !== null : false
  const allBookmarks = bookmarksData?.flatMap((page) => page.illusts) ?? []
  const hasMoreBookmarks = bookmarksData
    ? bookmarksData[bookmarksData.length - 1]?.next_offset != null
    : false

  // Restore only the sub-tab the page opened on, and only once its cards are in
  // the DOM: scrolling earlier would clamp to a short page.
  const [restoreTarget] = useState(() => ({ key: scrollKey, scrollY: readSavedScroll(scrollKey) }))
  useScrollPositionRestore({
    scrollY: restoreTarget.scrollY,
    isReady:
      restoreTarget.key === scrollKey &&
      userResult !== undefined &&
      (activeTab === 'works' ? worksData !== undefined : bookmarksData !== undefined),
    restoreKey: restoreTarget.key,
    onRestored: () => clearSavedScroll(restoreTarget.key),
  })

  // Capture while the page is still laid out: by the time an unmount cleanup
  // runs the router has already scrolled to the top (FE-T12).
  const rememberScrollOnLeave = (event: React.MouseEvent) => {
    if (!(event.target instanceof Element)) return
    // The card's Download button sits inside its link but never navigates.
    if (event.target.closest('button')) return
    const link = event.target.closest('a[href]')
    const href = link?.getAttribute('href')
    if (!link || !href?.startsWith('/') || link.getAttribute('target') === '_blank') return
    writeSavedScroll(scrollKey, window.scrollY)
  }

  if (!validId)
    return (
      <div className="p-8 text-center text-vault-text-secondary">
        <BackButton fallback="/pixiv" />
        {t('common.invalidId')}
      </div>
    )

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <BackButton fallback="/pixiv" />
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  if (error || !userResult) {
    return (
      <div className="p-6 text-center text-vault-text-secondary">
        <p>{t('common.failedToLoad')}</p>
        <button
          onClick={() => smartBack(router, '/pixiv')}
          className="text-vault-accent underline mt-2 inline-block"
        >
          <ArrowLeft size={14} className="inline mr-1" />
          {t('pixiv.title')}
        </button>
      </div>
    )
  }

  const { user, recent_illusts: recentWorks } = userResult

  return (
    <div className="space-y-6" onClickCapture={rememberScrollOnLeave}>
      <BackButton fallback="/pixiv" />

      {/* Profile header */}
      <div className="bg-vault-card border border-vault-border rounded-xl p-6">
        <div className="flex items-start gap-4">
          <img
            src={api.pixiv.imageProxyUrl(user.profile_image)}
            alt={user.name}
            className="w-20 h-20 rounded-full object-cover bg-vault-input shrink-0"
            onError={(e) => {
              ;(e.currentTarget as HTMLImageElement).style.display = 'none'
            }}
          />
          <div className="flex-1 min-w-0 space-y-2">
            <div className="flex items-start gap-3 flex-wrap">
              <div>
                <h1 className="text-xl font-bold text-vault-text">{user.name}</h1>
                <p className="text-sm text-vault-text-secondary">@{user.account}</p>
              </div>
              <div className="flex items-center gap-2 ml-auto shrink-0">
                <button
                  onClick={handleToggleFollow}
                  disabled={followLoading}
                  className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors disabled:opacity-50 ${
                    isFollowing
                      ? 'bg-vault-card border border-vault-border text-vault-text hover:bg-red-500/10 hover:text-red-400'
                      : 'bg-vault-accent text-white hover:bg-vault-accent/80'
                  }`}
                >
                  {followLoading
                    ? t('pixiv.loading')
                    : isFollowing
                      ? t('pixiv.unfollowOnPixiv')
                      : t('pixiv.followOnPixiv')}
                </button>
                <a
                  href={`https://www.pixiv.net/users/${user.id}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="p-1.5 rounded-lg bg-vault-card border border-vault-border text-vault-text-secondary hover:text-vault-text hover:bg-vault-card-hover transition-colors"
                  title={t('pixiv.viewOnPixiv')}
                >
                  <ExternalLink size={16} />
                </a>
              </div>
            </div>

            {/* Stats */}
            <div className="flex gap-4 text-sm">
              <div>
                <span className="font-bold text-vault-text">{user.total_illusts}</span>
                <span className="ml-1 text-vault-text-secondary">{t('pixiv.illusts')}</span>
              </div>
              <div>
                <span className="font-bold text-vault-text">{user.total_manga}</span>
                <span className="ml-1 text-vault-text-secondary">{t('pixiv.manga')}</span>
              </div>
              <div>
                <span className="font-bold text-vault-text">{user.total_novels}</span>
                <span className="ml-1 text-vault-text-secondary">{t('pixiv.novels')}</span>
              </div>
            </div>

            {/* Bio */}
            {user.comment && (
              <p className="text-sm text-vault-text leading-relaxed">{user.comment}</p>
            )}
            <div className="flex flex-wrap gap-2 pt-2 border-t border-vault-border">
              <button
                onClick={() => handleCollectionSync(false)}
                disabled={collectionLoading || Boolean(collection?.job_id)}
                className="px-3 py-1.5 rounded-lg text-sm bg-vault-accent text-white disabled:opacity-50"
              >
                {collection?.job_id
                  ? t('pixiv.collectionSyncing')
                  : collection?.gallery_id
                    ? t('pixiv.collectionSync')
                    : t('pixiv.collectionCreate')}
              </button>
              {collection?.gallery_id && (
                <>
                  <Link
                    href={`/library/pixiv/${encodeURIComponent(collection.gallery_source_id || '')}`}
                    className="px-3 py-1.5 rounded-lg text-sm border border-vault-border text-vault-text"
                  >
                    {t('pixiv.collectionOpen')}
                  </Link>
                  <button
                    onClick={() => handleCollectionSync(true)}
                    disabled={collectionLoading || Boolean(collection.job_id)}
                    className="px-3 py-1.5 rounded-lg text-sm border border-vault-border text-vault-text disabled:opacity-50"
                  >
                    {t('pixiv.collectionReconcile')}
                  </button>
                </>
              )}
              <button
                onClick={handleToggleSubscription}
                disabled={collectionLoading}
                className="px-3 py-1.5 rounded-lg text-sm border border-vault-border text-vault-text disabled:opacity-50"
              >
                {collection?.subscribed
                  ? t('pixiv.collectionUnsubscribe')
                  : t('pixiv.collectionSubscribe')}
              </button>
              {collection && collection.work_count > 0 && (
                <span className="self-center text-xs text-vault-text-secondary">
                  {t('pixiv.collectionWorks', { count: String(collection.work_count) })}
                  {collection.missing_count > 0 && ` · ${t('pixiv.collectionMissing', { count: String(collection.missing_count) })}`}
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Tab bar */}
      <div className="flex gap-1 bg-vault-card border border-vault-border rounded-lg p-1 w-fit">
        <button
          onClick={() => handleTabChange('works')}
          aria-current={activeTab === 'works' ? 'page' : undefined}
          className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
            activeTab === 'works' ? 'bg-vault-accent text-white' : 'text-vault-text-secondary hover:text-vault-text'
          }`}
        >
          {t('pixiv.userWorks')}
        </button>
        <button
          onClick={() => handleTabChange('bookmarks')}
          aria-current={activeTab === 'bookmarks' ? 'page' : undefined}
          className={`px-4 py-2 rounded-md text-sm font-medium transition-colors ${
            activeTab === 'bookmarks' ? 'bg-vault-accent text-white' : 'text-vault-text-secondary hover:text-vault-text'
          }`}
        >
          {t('pixiv.userBookmarks')}
        </button>
      </div>

      {/* Works tab */}
      {activeTab === 'works' && (
        <>
          {/* Recent works */}
          {recentWorks.length > 0 && (
            <div className="space-y-3">
              <h2 className="text-lg font-semibold text-vault-text">{t('pixiv.recentWorks')}</h2>
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
                {recentWorks.map((illust) => (
                  <IllustCard key={illust.id} illust={illust} />
                ))}
              </div>
            </div>
          )}

          {/* All works (paginated) */}
          <div className="space-y-3">
            <h2 className="text-lg font-semibold text-vault-text">{t('pixiv.allWorks')}</h2>

            {allWorks.length === 0 && !worksLoading && (
              <p className="text-vault-text-secondary text-sm">{t('pixiv.noResults')}</p>
            )}

            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
              {allWorks.map((illust) => (
                <IllustCard key={illust.id} illust={illust} />
              ))}
            </div>

            {hasMoreWorks && (
              <div className="flex justify-center pt-2">
                <button
                  onClick={() => setSize(size + 1)}
                  disabled={worksLoading}
                  className="px-6 py-2 rounded-lg bg-vault-card border border-vault-border text-vault-text text-sm hover:bg-vault-card-hover transition-colors disabled:opacity-50"
                >
                  {worksLoading ? t('pixiv.loading') : t('pixiv.loadMore')}
                </button>
              </div>
            )}
          </div>
        </>
      )}

      {/* Bookmarks tab */}
      {activeTab === 'bookmarks' && (
        <div className="space-y-3">
          {bookmarksInitialLoading ? (
            <div className="flex items-center justify-center py-16">
              <LoadingSpinner size="lg" />
            </div>
          ) : allBookmarks.length === 0 ? (
            <p className="text-center py-8 text-vault-text-muted">{t('pixiv.noBookmarks')}</p>
          ) : (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6 gap-3">
                {allBookmarks.map((illust) => (
                  <IllustCard key={illust.id} illust={illust} />
                ))}
              </div>
              {hasMoreBookmarks && (
                <div className="flex justify-center pt-2">
                  <button
                    onClick={() => setBookmarksSize(bookmarksSize + 1)}
                    disabled={bookmarksLoading}
                    className="px-6 py-2 rounded-lg bg-vault-card border border-vault-border text-vault-text text-sm hover:bg-vault-card-hover transition-colors disabled:opacity-50"
                  >
                    {bookmarksLoading ? t('pixiv.loading') : t('pixiv.loadMore')}
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
