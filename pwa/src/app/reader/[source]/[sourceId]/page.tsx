'use client'
import { useEffect, useRef, useState } from 'react'
import { useParams, useSearchParams } from 'next/navigation'
import { api } from '@/lib/api'
import Reader from '@/components/Reader'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { t } from '@/lib/i18n'
import type { Gallery, GalleryImage, ReadProgress } from '@/lib/types'

interface LoadedData {
  gallery: Gallery
  images: GalleryImage[]
  progress: ReadProgress | null
  favoritedImageIds: number[]
}

export default function ReaderPage() {
  const { source, sourceId } = useParams<{ source: string; sourceId: string }>()
  const searchParams = useSearchParams()
  const urlPage = parseInt(searchParams.get('page') ?? '', 10) || 0

  const [data, setData] = useState<LoadedData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const historyRecordedRef = useRef(false)

  useEffect(() => {
    if (!source || !sourceId) {
      setError('Invalid gallery source or ID.')
      return
    }

    let cancelled = false

    async function load() {
      try {
        const [gallery, imagesResp, progress] = await Promise.all([
          api.library.getGallery(source, sourceId),
          api.library.getImages(source, sourceId),
          api.library.getProgress(source, sourceId).catch(() => null),
        ])

        if (!cancelled) {
          setData({
            gallery,
            images: imagesResp.images,
            progress,
            favoritedImageIds: imagesResp.favorited_image_ids ?? [],
          })

          // Record browse history — fire and forget
          if (!historyRecordedRef.current) {
            try {
              if (localStorage.getItem('history_enabled') !== 'false') {
                historyRecordedRef.current = true
                api.history
                  .record({
                    source: gallery.source,
                    source_id: gallery.source_id,
                    title: gallery.title,
                    thumb: gallery.cover_thumb || undefined,
                  })
                  .catch(() => {})
              }
            } catch {
              // localStorage may be unavailable in some contexts
            }
          }
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Failed to load gallery.')
        }
      }
    }

    load()
    return () => {
      cancelled = true
    }
  }, [source, sourceId])

  useEffect(() => {
    if (data?.gallery.download_status !== 'downloading') return
    let cancelled = false
    const interval = setInterval(async () => {
      try {
        const [gallery, imagesResp] = await Promise.all([
          api.library.getGallery(source, sourceId),
          api.library.getImages(source, sourceId),
        ])
        if (!cancelled) {
          setData((prev) =>
            prev
              ? {
                  ...prev,
                  gallery,
                  images: imagesResp.images,
                  favoritedImageIds: imagesResp.favorited_image_ids ?? [],
                }
              : prev,
          )
        }
      } catch {
        // silently ignore revalidation errors
      }
    }, 5000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [source, sourceId, data?.gallery.download_status])

  if (error) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-black text-white">
        <div className="text-center">
          <p className="text-lg font-semibold text-red-400">Error</p>
          <p className="mt-1 text-sm opacity-70">{error}</p>
        </div>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-black text-white">
        <div className="text-center">
          <div className="mx-auto mb-3 h-8 w-8 animate-spin rounded-full border-2 border-white/20 border-t-white" />
          <p className="text-sm opacity-50">Loading gallery…</p>
        </div>
      </div>
    )
  }

  const { gallery, images, progress } = data

  // Downloading but no images imported yet — show waiting screen.
  // The 5s polling effect above will keep refreshing until images arrive.
  if (images.length === 0 && gallery.download_status === 'downloading') {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-black text-white">
        <div className="text-center">
          <div className="mx-auto mb-3 h-8 w-8 animate-spin rounded-full border-2 border-white/20 border-t-white" />
          <p className="text-sm opacity-70">{t('reader.downloadingWait')}</p>
        </div>
      </div>
    )
  }

  // During download, gallery.pages is 0 (only updated at finalize).
  // Use the highest imported page_num as the ceiling so ?page=N doesn't clamp to 0.
  const pageCeiling =
    gallery.download_status === 'downloading' && images.length > 0
      ? images.reduce((max, img) => Math.max(max, img.page_num), gallery.pages)
      : gallery.pages

  // URL ?page= takes priority over saved progress
  let initialPage =
    urlPage > 0
      ? pageCeiling > 0
        ? Math.min(urlPage, pageCeiling)
        : 1
      : progress?.last_page && progress.last_page > 0
        ? pageCeiling > 0
          ? Math.min(progress.last_page, pageCeiling)
          : 1
        : 1

  return (
    <ErrorBoundary>
      <Reader
        source={gallery.source}
        sourceId={gallery.source_id}
        downloadStatus={gallery.download_status}
        images={images}
        totalPages={
          gallery.download_status === 'downloading'
            ? Math.max(gallery.pages, images.length)
            : gallery.pages
        }
        initialPage={initialPage}
        initialFavoritedImageIds={data.favoritedImageIds}
      />
    </ErrorBoundary>
  )
}
