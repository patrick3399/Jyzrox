'use client'

import { useState, useEffect } from 'react'
import { use } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import useSWR from 'swr'
import { api } from '@/lib/api'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { toast } from 'sonner'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { ExternalLink, ArrowLeft, BookOpen } from 'lucide-react'
import { BackButton } from '@/components/BackButton'

function sanitizeHtml(html: string): string {
  return html
    .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
    .replace(/\s*on\w+\s*=\s*["'][^"']*["']/gi, '')
    .replace(/javascript:/gi, '')
}

export default function IllustDetailPage({ params }: { params: Promise<{ id: string }> }) {
  useLocale()
  const { id } = use(params)
  const illustId = parseInt(id, 10)

  const router = useRouter()

  const { data: illust, error, isLoading } = useSWR(
    isNaN(illustId) ? null : `/api/pixiv/illust/${illustId}`,
    () => api.pixiv.getIllust(illustId),
  )

  const { data: bookmarkData, mutate: mutateBookmark } = useSWR(
    isNaN(illustId) ? null : `/api/pixiv/illust/${illustId}/bookmark`,
    () => api.pixiv.getBookmarkStatus(illustId),
  )
  const isBookmarked = bookmarkData?.is_bookmarked ?? illust?.is_bookmarked ?? false

  const [downloading, setDownloading] = useState(false)
  const [bookmarking, setBookmarking] = useState(false)

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault()
        if (!isNaN(illustId)) router.push(`/reader/pixiv/${illustId}`)
      }
      if (e.key === 'ArrowUp' || e.key === 'Escape') {
        e.preventDefault()
        history.length > 1 ? router.back() : router.push('/pixiv')
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [illustId, router])

  if (isNaN(illustId)) return <div className="p-8 text-center text-vault-text-secondary">{t('common.invalidId')}</div>

  const handleBookmark = async () => {
    if (bookmarking) return
    setBookmarking(true)
    try {
      if (isBookmarked) {
        await api.pixiv.deleteBookmark(illustId)
      } else {
        await api.pixiv.addBookmark(illustId)
      }
      mutateBookmark()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToSave'))
    } finally {
      setBookmarking(false)
    }
  }

  const handleDownload = async () => {
    if (downloading) return
    setDownloading(true)
    try {
      await api.download.enqueue(`https://www.pixiv.net/artworks/${illustId}`)
      toast.success(t('browse.addedToQueue'))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToSave'))
    } finally {
      setDownloading(false)
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  if (error || !illust) {
    return (
      <div className="p-6 text-center text-vault-text-secondary">
        <p>{t('common.failedToLoad')}</p>
        <button onClick={() => router.back()} className="text-vault-accent underline mt-2 inline-block">
          <ArrowLeft size={14} className="inline mr-1" />
          {t('pixiv.title')}
        </button>
      </div>
    )
  }

  const mainImageUrl = api.pixiv.imageProxyUrl(illust.image_urls.large)
  const squareUrl = api.pixiv.imageProxyUrl(illust.image_urls.square_medium)

  return (
    <div className="space-y-6">
      {/* Back link */}
      <BackButton fallback="/pixiv" />

      <div className="grid md:grid-cols-[1fr_320px] gap-6">
        {/* Main image */}
        <div className="space-y-3">
          <div className="rounded-xl overflow-hidden bg-vault-input">
            <img
              src={mainImageUrl}
              alt={illust.title}
              className="w-full object-contain max-h-[80vh]"
              loading="eager"
              onError={(e) => {
                // fallback to square_medium
                ;(e.currentTarget as HTMLImageElement).src = squareUrl
              }}
            />
          </div>

          {/* Multi-page thumbnails */}
          {illust.page_count > 1 && (
            <div className="space-y-2">
              <p className="text-sm text-vault-text-secondary">
                {illust.page_count} {t('pixiv.pages')}
              </p>
              <p className="text-xs text-vault-text-secondary italic">
                {t('pixiv.download')} {t('pixiv.viewAllPages')}
              </p>
            </div>
          )}
        </div>

        {/* Info panel */}
        <div className="space-y-4">
          {/* Title & artist */}
          <div>
            <h1 className="text-xl font-bold text-vault-text leading-snug">{illust.title}</h1>
            <Link
              href={`/pixiv/user/${illust.user.id}`}
              className="flex items-center gap-2 mt-2 group"
            >
              <img
                src={api.pixiv.imageProxyUrl(illust.user.profile_image)}
                alt={illust.user.name}
                className="w-8 h-8 rounded-full object-cover bg-vault-input"
                onError={(e) => {
                  ;(e.currentTarget as HTMLImageElement).style.display = 'none'
                }}
              />
              <span className="text-sm text-vault-accent group-hover:underline">
                {illust.user.name}
              </span>
            </Link>
          </div>

          {/* Actions */}
          <div className="flex gap-2">
            <button
              onClick={handleDownload}
              disabled={downloading}
              className="flex-1 py-2 rounded-lg bg-vault-accent text-white text-sm font-medium hover:bg-vault-accent/80 transition-colors disabled:opacity-50"
            >
              {downloading ? t('pixiv.downloading') : t('pixiv.download')}
            </button>
            <button
              onClick={handleBookmark}
              disabled={bookmarking}
              title={isBookmarked ? t('pixiv.unfollow') : t('pixiv.bookmarks')}
              className={`w-10 h-10 flex items-center justify-center rounded-lg border text-base transition-colors disabled:opacity-50 ${
                isBookmarked
                  ? 'bg-yellow-500/20 border-yellow-500/50 text-yellow-400 hover:bg-red-500/10 hover:text-red-400'
                  : 'bg-vault-card border-vault-border text-vault-text hover:bg-vault-card-hover'
              }`}
            >
              {bookmarking ? '·' : isBookmarked ? '★' : '☆'}
            </button>
            <Link
              href={`/reader/pixiv/${illustId}`}
              className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-vault-card border border-vault-border text-vault-text text-sm hover:bg-vault-card-hover transition-colors"
            >
              <BookOpen size={14} />
              {t('pixiv.read')}
            </Link>
            <a
              href={`https://www.pixiv.net/artworks/${illust.id}`}
              target="_blank"
              rel="noopener noreferrer"
              title={t('pixiv.viewOnPixiv')}
              className="w-10 h-10 flex items-center justify-center rounded-lg bg-vault-card border border-vault-border text-vault-text-secondary hover:text-vault-text hover:bg-vault-card-hover transition-colors"
            >
              <ExternalLink size={16} />
            </a>
          </div>

          {/* Stats */}
          <div className="grid grid-cols-2 gap-2">
            <div className="bg-vault-card border border-vault-border rounded-lg p-2.5 text-center">
              <p className="text-lg font-bold text-vault-text">
                {illust.total_view.toLocaleString()}
              </p>
              <p className="text-xs text-vault-text-secondary">{t('pixiv.views')}</p>
            </div>
            <div className="bg-vault-card border border-vault-border rounded-lg p-2.5 text-center">
              <p className="text-lg font-bold text-vault-text">
                {illust.total_bookmarks.toLocaleString()}
              </p>
              <p className="text-xs text-vault-text-secondary">{t('pixiv.bookmarks')}</p>
            </div>
          </div>

          {/* Date */}
          <div className="text-sm text-vault-text-secondary">
            {new Date(illust.create_date).toLocaleDateString()}
          </div>

          {/* Tags */}
          {illust.tags.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-xs font-medium text-vault-text-secondary uppercase tracking-wider">
                {t('common.tags')}
              </p>
              <div className="flex flex-wrap gap-1.5">
                {illust.tags.map((tag) => (
                  <span
                    key={tag.name}
                    className="px-2 py-0.5 rounded-full bg-vault-input text-xs text-vault-text border border-vault-border"
                    title={tag.translated_name ?? undefined}
                  >
                    {tag.name}
                    {tag.translated_name && (
                      <span className="ml-1 text-vault-text-secondary">
                        ({tag.translated_name})
                      </span>
                    )}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Caption */}
          {illust.caption && (
            <div className="space-y-1.5">
              <p className="text-xs font-medium text-vault-text-secondary uppercase tracking-wider">
                {t('pixiv.caption')}
              </p>
              <div
                className="text-sm text-vault-text leading-relaxed prose prose-invert max-w-none prose-a:text-vault-accent"
                dangerouslySetInnerHTML={{ __html: sanitizeHtml(illust.caption) }}
              />
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
