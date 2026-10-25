'use client'

import { use, useEffect } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import useSWR from 'swr'
import { api } from '@/lib/api'
import Reader from '@/components/Reader'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { ReaderFallbackScreen } from '@/components/Reader/ReaderFallbackScreen'
import { useLocale } from '@/components/LocaleProvider'
import { t } from '@/lib/i18n'
import type { GalleryImage } from '@/lib/types'

const AUTHOR_COLLECTION_PREFIX = 'user:'

/** Where the reader's exits lead when there is no history to go back to: the
 *  artwork (or artist) the reader was opened from, never the library default. */
function readerExitHref(id: string, illustId: number): string {
  if (id.startsWith(AUTHOR_COLLECTION_PREFIX)) {
    const authorId = id.slice(AUTHOR_COLLECTION_PREFIX.length)
    return /^\d+$/.test(authorId) ? `/pixiv/user/${authorId}` : '/pixiv'
  }
  return Number.isNaN(illustId) ? '/pixiv' : `/pixiv/illust/${illustId}`
}

export default function PixivReaderPage({ params }: { params: Promise<{ id: string }> }) {
  useLocale()
  const { id } = use(params)
  const router = useRouter()
  const isAuthorCollection = id.startsWith(AUTHOR_COLLECTION_PREFIX)
  const illustId = parseInt(id, 10)
  const backHref = readerExitHref(id, illustId)
  const searchParams = useSearchParams()
  const initialPage = Math.max(1, parseInt(searchParams.get('page') ?? '1', 10) || 1)

  useEffect(() => {
    if (!isAuthorCollection) return
    const query = searchParams.toString()
    router.replace(
      `/reader/gallery/pixiv/${encodeURIComponent(id)}${query ? `?${query}` : ''}`,
    )
  }, [id, isAuthorCollection, router, searchParams])

  const { data: pagesData, error: pagesError } = useSWR(
    isNaN(illustId) || isAuthorCollection ? null : `/api/pixiv/illust/${illustId}/pages`,
    () => api.pixiv.getIllustPages(illustId),
  )

  if (isAuthorCollection) {
    return (
      <ReaderFallbackScreen backHref={backHref}>
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-white/20 border-t-white" />
      </ReaderFallbackScreen>
    )
  }

  if (isNaN(illustId)) {
    return (
      <ReaderFallbackScreen backHref={backHref}>
        <div className="text-center">
          <p className="text-lg font-semibold text-red-400">{t('common.error')}</p>
          <p className="mt-1 text-sm opacity-70">{t('common.invalidId')}</p>
        </div>
      </ReaderFallbackScreen>
    )
  }

  const error = pagesError

  if (error) {
    return (
      <ReaderFallbackScreen backHref={backHref}>
        <div className="text-center">
          <p className="text-lg font-semibold text-red-400">{t('common.error')}</p>
          <p className="mt-1 text-sm opacity-70">
            {error instanceof Error ? error.message : t('common.failedToLoad')}
          </p>
        </div>
      </ReaderFallbackScreen>
    )
  }

  if (!pagesData) {
    return (
      <ReaderFallbackScreen backHref={backHref}>
        <div className="text-center">
          <div className="mx-auto mb-3 h-8 w-8 animate-spin rounded-full border-2 border-white/20 border-t-white" />
          <p className="text-sm opacity-50">{t('pixiv.loading')}</p>
        </div>
      </ReaderFallbackScreen>
    )
  }

  const images: GalleryImage[] = pagesData.pages.map((page) => ({
    id: page.page_num,
    gallery_id: 0,
    page_num: page.page_num,
    filename: null,
    width: null,
    height: null,
    file_path: api.pixiv.imageProxyUrl(page.url),
    thumb_path: null,
    file_size: null,
    file_hash: null,
    media_type: 'image' as const,
    duration: null,
  }))

  return (
    <ErrorBoundary>
      <Reader
        source="pixiv"
        sourceId={String(illustId)}
        downloadStatus="complete"
        images={images}
        totalPages={pagesData.page_count}
        initialPage={Math.min(initialPage, pagesData.page_count)}
        backHref={backHref}
      />
    </ErrorBoundary>
  )
}
