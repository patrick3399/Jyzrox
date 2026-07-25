'use client'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams, useRouter, useSearchParams } from 'next/navigation'
import { api } from '@/lib/api'
import { decodeRouteSegment } from '@/lib/galleryRoutes'
import Reader from '@/components/Reader'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { t } from '@/lib/i18n'
import { useWsConnection, useWsJobs } from '@/lib/ws'
import { createRequestCoalescer } from '@/lib/requestCoalescer'
import {
  numberSetsEqual,
  readerGalleryStateEqual,
  readerImagesEqual,
  READER_DOWNLOAD_REFRESH_INTERVAL_MS,
} from '@/lib/readerRefresh'
import type { Gallery, GalleryImage, ReadProgress } from '@/lib/types'

interface LoadedData {
  gallery: Gallery
  images: GalleryImage[]
  progress: ReadProgress | null
  favoritedImageIds: number[]
}

export default function ReaderPage() {
  const router = useRouter()
  const params = useParams<{ source: string; sourceId: string }>()
  const source = decodeRouteSegment(params.source)
  const sourceId = decodeRouteSegment(params.sourceId)
  const searchParams = useSearchParams()
  const urlPage = parseInt(searchParams.get('page') ?? '', 10) || 0

  const [data, setData] = useState<LoadedData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const historyRecordedRef = useRef(false)
  const { connected } = useWsConnection()
  const { lastJobUpdate } = useWsJobs()

  const refreshCoalescer = useMemo(
    () =>
      createRequestCoalescer(async () => {
        if (!source || !sourceId) return
        try {
          const [gallery, imagesResp] = await Promise.all([
            api.library.getGallery(source, sourceId),
            api.library.getImages(source, sourceId),
          ])
          setData((prev) => {
            if (!prev) return prev
            const nextFavorites = imagesResp.favorited_image_ids ?? []
            if (
              readerGalleryStateEqual(prev.gallery, gallery) &&
              readerImagesEqual(prev.images, imagesResp.images) &&
              numberSetsEqual(prev.favoritedImageIds, nextFavorites)
            ) {
              return prev
            }
            return {
              ...prev,
              gallery,
              images: imagesResp.images,
              favoritedImageIds: nextFavorites,
            }
          })
        } catch {
          // A later event or disconnected fallback poll will retry.
        }
      }, READER_DOWNLOAD_REFRESH_INTERVAL_MS),
    [source, sourceId],
  )

  useEffect(() => () => refreshCoalescer.cancel(), [refreshCoalescer])

  useEffect(() => {
    if (!source || !sourceId) {
      setError('Invalid gallery source or ID.')
      return
    }

    let cancelled = false
    const currentSource = source
    const currentSourceId = sourceId

    async function load() {
      try {
        const [gallery, imagesResp, progress] = await Promise.all([
          api.library.getGallery(currentSource, currentSourceId),
          api.library.getImages(currentSource, currentSourceId),
          api.library.getProgress(currentSource, currentSourceId).catch(() => null),
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

  // FE-T14 fallback poll: only runs when WS is down. While connected, the
  // effect below reacts to WS job-progress events instead — see
  // wsInvalidation.tsx module docstring for why download.* can't drive this
  // via lastEvent, and worker/download.py for progress.gallery_id.
  useEffect(() => {
    if (data?.gallery.download_status !== 'downloading' || !source || !sourceId) return
    if (connected) return
    const interval = setInterval(
      () => refreshCoalescer.trigger(),
      READER_DOWNLOAD_REFRESH_INTERVAL_MS,
    )
    return () => {
      clearInterval(interval)
    }
  }, [source, sourceId, data?.gallery.download_status, connected, refreshCoalescer])

  // WS-driven refresh while downloading and connected: progressive import
  // sets progress.gallery_id on job_update events (see worker/download.py),
  // so a matching update means new pages may have arrived for this gallery.
  useEffect(() => {
    if (data?.gallery.download_status !== 'downloading' || !source || !sourceId) return
    if (!connected || !lastJobUpdate) return
    const progressGalleryId = lastJobUpdate.progress?.gallery_id
    if (progressGalleryId !== data?.gallery.id) return
    refreshCoalescer.trigger()
  }, [lastJobUpdate, source, sourceId, connected, data?.gallery.download_status, data?.gallery.id, refreshCoalescer])

  if (error) {
    return (
      <div className="relative flex h-screen w-full items-center justify-center bg-black text-white">
        <button
          onClick={() => router.back()}
          title={t('reader.goBack')}
          className="absolute left-4 top-4 flex h-10 w-10 items-center justify-center rounded-full bg-white/10 text-xl"
        >
          ✕
        </button>
        <div className="text-center">
          <p className="text-lg font-semibold text-red-400">{t('common.error')}</p>
          <p className="mt-1 text-sm opacity-70">{error}</p>
        </div>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="relative flex h-screen w-full items-center justify-center bg-black text-white">
        <button
          onClick={() => router.back()}
          title={t('reader.goBack')}
          className="absolute left-4 top-4 flex h-10 w-10 items-center justify-center rounded-full bg-white/10 text-xl"
        >
          ✕
        </button>
        <div className="text-center">
          <div className="mx-auto mb-3 h-8 w-8 animate-spin rounded-full border-2 border-white/20 border-t-white" />
          <p className="text-sm opacity-50">{t('reader.loadingGallery')}</p>
        </div>
      </div>
    )
  }

  const { gallery, images, progress } = data

  // Downloading but no images imported yet — show waiting screen.
  // The bounded polling/WS refresh above will keep refreshing until images arrive.
  if (images.length === 0 && gallery.download_status === 'downloading') {
    return (
      <div className="relative flex h-screen w-full items-center justify-center bg-black text-white">
        <button
          onClick={() => router.back()}
          title={t('reader.goBack')}
          className="absolute left-4 top-4 flex h-10 w-10 items-center justify-center rounded-full bg-white/10 text-xl"
        >
          ✕
        </button>
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
  const initialPage =
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
