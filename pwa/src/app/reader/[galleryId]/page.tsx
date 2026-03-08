'use client'
import { useEffect, useRef, useState } from 'react'
import { useParams } from 'next/navigation'
import { api } from '@/lib/api'
import Reader from '@/components/Reader'
import type { Gallery, GalleryImage, ReadProgress } from '@/lib/types'

interface LoadedData {
  gallery: Gallery
  images: GalleryImage[]
  progress: ReadProgress | null
}

export default function ReaderPage() {
  const { galleryId } = useParams<{ galleryId: string }>()
  const id = Number(galleryId)

  const [data, setData] = useState<LoadedData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const historyRecordedRef = useRef(false)

  useEffect(() => {
    if (!id || isNaN(id)) {
      setError('Invalid gallery ID.')
      return
    }

    let cancelled = false

    async function load() {
      try {
        const [gallery, imagesResp, progress] = await Promise.all([
          api.library.getGallery(id),
          api.library.getImages(id),
          api.library.getProgress(id).catch(() => null),
        ])

        if (!cancelled) {
          setData({
            gallery,
            images: imagesResp.images,
            progress,
          })

          // Record browse history — fire and forget
          if (!historyRecordedRef.current) {
            try {
              if (localStorage.getItem('history_enabled') !== 'false') {
                historyRecordedRef.current = true
                api.history
                  .record({
                    source: gallery.source || 'local',
                    source_id: String(gallery.id),
                    title: gallery.title,
                    thumb: gallery.cover_thumb || '',
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
  }, [id])

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

  // source_id is the numeric EH gid stored as a string in Gallery
  const sourceId = gallery.source_id

  const initialPage =
    progress?.last_page && progress.last_page > 0 ? Math.min(progress.last_page, gallery.pages) : 1

  return (
    <Reader
      galleryId={gallery.id}
      sourceId={sourceId}
      downloadStatus={gallery.download_status}
      images={images}
      totalPages={gallery.pages}
      initialPage={initialPage}
    />
  )
}
