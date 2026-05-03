'use client'

import { Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { api } from '@/lib/api'
import Reader from '@/components/Reader'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import type { BrowseImage, GalleryImage } from '@/lib/types'

type FavoriteReaderImage = GalleryImage & {
  gallery_source: string | null
  gallery_source_id: string | null
}

function toReaderImage(img: BrowseImage, pageNum: number): FavoriteReaderImage {
  return {
    id: img.id,
    gallery_id: img.gallery_id,
    page_num: pageNum,
    filename: `page_${img.page_num}`,
    width: img.width,
    height: img.height,
    file_path: img.file_path,
    thumb_path: img.thumb_path,
    file_size: null,
    file_hash: null,
    media_type: img.media_type,
    duration: null,
    thumbhash: img.thumbhash,
    gallery_source: img.source,
    gallery_source_id: img.source_id,
  }
}

export default function FavoriteReaderPage() {
  return (
    <Suspense>
      <FavoriteReaderInner />
    </Suspense>
  )
}

function FavoriteReaderInner() {
  const searchParams = useSearchParams()
  const startParam = Number(searchParams.get('start')) || 1
  const imageIdParam = Number(searchParams.get('image_id')) || null

  const [images, setImages] = useState<FavoriteReaderImage[] | null>(null)
  const originalImageByPageRef = useRef<Map<number, BrowseImage>>(new Map())
  const [loaded, setLoaded] = useState(0)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    async function loadAll() {
      try {
        const accumulated: BrowseImage[] = []
        let cursor: string | undefined
        let hasNext = true

        while (hasNext) {
          const resp = await api.library.browseImages({
            favorited: true,
            limit: 100,
            cursor,
          })

          if (cancelled) return

          accumulated.push(...resp.images)
          setLoaded(accumulated.length)
          hasNext = resp.has_next
          cursor = resp.next_cursor ?? undefined
        }

        if (!cancelled) {
          originalImageByPageRef.current = new Map(
            accumulated.map((img, index) => [index + 1, img]),
          )
          setImages(accumulated.map((img, index) => toReaderImage(img, index + 1)))
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Failed to load favorite images.')
        }
      }
    }

    loadAll()
    return () => {
      cancelled = true
    }
  }, [])

  const handleHideImage = useCallback(async (reindexedPageNum: number) => {
    const original = originalImageByPageRef.current.get(reindexedPageNum)
    if (!original?.source || !original.source_id) throw new Error('Image not found')

    await api.library.deleteImage(original.source, original.source_id, original.page_num)
    originalImageByPageRef.current.delete(reindexedPageNum)
  }, [])

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

  if (!images) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-black text-white">
        <div className="text-center">
          <div className="mx-auto mb-3 h-8 w-8 animate-spin rounded-full border-2 border-white/20 border-t-white" />
          <p className="text-sm opacity-50">Loading favorite images... {loaded}</p>
        </div>
      </div>
    )
  }

  if (images.length === 0) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-black text-white">
        <p className="text-sm opacity-60">No favorite images found.</p>
      </div>
    )
  }

  const targetPage = imageIdParam
    ? (images.find((img) => img.id === imageIdParam)?.page_num ?? startParam)
    : startParam

  return (
    <ErrorBoundary>
      <Reader
        source=""
        sourceId=""
        downloadStatus="complete"
        images={images}
        totalPages={images.length}
        initialPage={Math.min(targetPage, images.length)}
        initialFavoritedImageIds={images.map((img) => img.id)}
        onHideImage={handleHideImage}
      />
    </ErrorBoundary>
  )
}
