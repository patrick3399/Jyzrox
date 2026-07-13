'use client'

import { use, useEffect } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import useSWR from 'swr'
import { api } from '@/lib/api'
import Reader from '@/components/Reader'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { useLocale } from '@/components/LocaleProvider'
import { t } from '@/lib/i18n'
import type { GalleryImage } from '@/lib/types'

export default function PixivReaderPage({ params }: { params: Promise<{ id: string }> }) {
  useLocale()
  const { id } = use(params)
  const router = useRouter()
  const isAuthorCollection = id.startsWith('user:')
  const illustId = parseInt(id, 10)
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

  const { data: illust, error: illustError } = useSWR(
    isNaN(illustId) || isAuthorCollection ? null : `/api/pixiv/illust/${illustId}`,
    () => api.pixiv.getIllust(illustId),
  )

  if (isAuthorCollection) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-black text-white">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-white/20 border-t-white" />
      </div>
    )
  }

  if (isNaN(illustId)) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-black text-white">
        <div className="text-center">
          <p className="text-lg font-semibold text-red-400">{t('common.error')}</p>
          <p className="mt-1 text-sm opacity-70">{t('common.invalidId')}</p>
        </div>
      </div>
    )
  }

  const error = pagesError || illustError

  if (error) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-black text-white">
        <div className="text-center">
          <p className="text-lg font-semibold text-red-400">{t('common.error')}</p>
          <p className="mt-1 text-sm opacity-70">
            {error instanceof Error ? error.message : t('common.failedToLoad')}
          </p>
        </div>
      </div>
    )
  }

  if (!pagesData) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-black text-white">
        <div className="text-center">
          <div className="mx-auto mb-3 h-8 w-8 animate-spin rounded-full border-2 border-white/20 border-t-white" />
          <p className="text-sm opacity-50">{t('pixiv.loading')}</p>
        </div>
      </div>
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

  const title = illust?.title ?? `Pixiv #${illustId}`

  return (
    <ErrorBoundary>
      <Reader
        source="pixiv"
        sourceId={title}
        downloadStatus="complete"
        images={images}
        totalPages={pagesData.page_count}
        initialPage={Math.min(initialPage, pagesData.page_count)}
      />
    </ErrorBoundary>
  )
}
