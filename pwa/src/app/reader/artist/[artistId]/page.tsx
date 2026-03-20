'use client'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useParams, useSearchParams } from 'next/navigation'
import { api } from '@/lib/api'
import Reader from '@/components/Reader'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import type { ArtistImageItem, GalleryImage } from '@/lib/types'

export default function ArtistReaderPage() {
  const { artistId } = useParams<{ artistId: string }>()
  const searchParams = useSearchParams()

  const decodedArtistId = decodeURIComponent(artistId)
  const startParam = Number(searchParams.get('start')) || 1

  const [images, setImages] = useState<GalleryImage[] | null>(null)
  const originalImagesRef = useRef<ArtistImageItem[]>([])
  const [loaded, setLoaded] = useState(0)
  const [total, setTotal] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!decodedArtistId) {
      setError('Invalid artist ID.')
      return
    }

    let cancelled = false

    async function loadAll() {
      try {
        const accumulated: GalleryImage[] = []
        let page = 0
        let hasNext = true

        while (hasNext) {
          const resp = await api.library.getArtistImages(decodedArtistId, {
            page,
            limit: 200,
            sort: 'newest',
          })

          if (cancelled) return

          if (page === 0) {
            setTotal(resp.total)
          }

          accumulated.push(...resp.images)
          setLoaded(accumulated.length)

          hasNext = resp.has_next
          page += 1
        }

        if (!cancelled) {
          originalImagesRef.current = accumulated as ArtistImageItem[]
          const reindexed: GalleryImage[] = accumulated.map((img, i) => ({
            ...img,
            page_num: i + 1,
          }))
          setImages(reindexed)
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Failed to load artist images.')
        }
      }
    }

    loadAll()
    return () => {
      cancelled = true
    }
  }, [decodedArtistId])

  const handleHideImage = useCallback(async (reindexedPageNum: number) => {
    const originalIndex = reindexedPageNum - 1
    const original = originalImagesRef.current[originalIndex]
    if (!original) throw new Error('Image not found')

    await api.library.deleteImage(
      original.gallery_source,
      original.gallery_source_id,
      original.page_num,
    )

    originalImagesRef.current = originalImagesRef.current.filter((_, i) => i !== originalIndex)
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
          <p className="text-sm opacity-50">
            {total !== null ? `Loading images... ${loaded}/${total}` : 'Loading images...'}
          </p>
        </div>
      </div>
    )
  }

  return (
    <ErrorBoundary>
      <Reader
        source=""
        sourceId=""
        downloadStatus="complete"
        images={images}
        totalPages={images.length}
        initialPage={startParam}
        onHideImage={handleHideImage}
      />
    </ErrorBoundary>
  )
}
