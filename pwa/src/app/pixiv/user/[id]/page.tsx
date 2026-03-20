'use client'

import { useState, useEffect } from 'react'
import { use } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import useSWR from 'swr'
import useSWRInfinite from 'swr/infinite'
import { api } from '@/lib/api'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { toast } from 'sonner'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { ArrowLeft, ExternalLink } from 'lucide-react'
import type { PixivIllust, PixivSearchResult } from '@/lib/types'

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
  } = useSWR(validId ? `/api/pixiv/user/${userId}` : null, () => api.pixiv.getUser(userId))

  const [isFollowing, setIsFollowing] = useState(false)
  const [followLoading, setFollowLoading] = useState(false)

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
    ([, offset]) => api.pixiv.getUserIllusts(userId, offset as number),
    { revalidateFirstPage: false },
  )

  const allWorks = worksData?.flatMap((page) => page.illusts) ?? []
  const hasMoreWorks = worksData ? worksData[worksData.length - 1]?.next_offset !== null : false

  if (!validId)
    return <div className="p-8 text-center text-vault-text-secondary">{t('common.invalidId')}</div>

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  if (error || !userResult) {
    return (
      <div className="p-6 text-center text-vault-text-secondary">
        <p>{t('common.failedToLoad')}</p>
        <button
          onClick={() => router.back()}
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
    <div className="space-y-6">
      {/* Back link */}
      <button
        onClick={() => router.back()}
        className="inline-flex items-center gap-1.5 text-sm text-vault-text-secondary hover:text-vault-text transition-colors"
      >
        <ArrowLeft size={14} />
        {t('pixiv.title')}
      </button>

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
                      ? t('pixiv.unfollow')
                      : t('pixiv.follow')}
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
          </div>
        </div>
      </div>

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
    </div>
  )
}
