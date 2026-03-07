'use client'

import { useMemo, useState, useEffect, Suspense } from 'react'
import { useParams, useSearchParams, useRouter } from 'next/navigation'
import { useEhGallery, useEhGalleryImages } from '@/hooks/useGalleries'
import Reader from '@/components/Reader'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import type { GalleryImage } from '@/lib/types'

export default function EhProxyReaderPageWrapper() {
  return (
    <Suspense>
      <EhProxyReaderPage />
    </Suspense>
  )
}

function EhProxyReaderPage() {
  const { gid: gidStr, token } = useParams<{ gid: string; token: string }>()
  const searchParams = useSearchParams()
  const router = useRouter()
  const gid = Number(gidStr)
  const startPage = Number(searchParams.get('page') || '1')

  const { data: gallery, error: galleryError, isLoading: galleryLoading } = useEhGallery(gid, token)
  const { data: imageMap, error: imagesError, isLoading: imagesLoading } = useEhGalleryImages(gid, token)

  // Track loading time
  const [loadingTooLong, setLoadingTooLong] = useState(false)
  useEffect(() => {
    if (gallery && imageMap) return
    const timer = setTimeout(() => setLoadingTooLong(true), 8000)
    return () => clearTimeout(timer)
  }, [gallery, imageMap])

  // Build GalleryImage[] from imageMap for the Reader component
  const images: GalleryImage[] = useMemo(() => {
    if (!gallery || !imageMap) return []
    return Array.from({ length: gallery.pages }, (_, i) => ({
      id: i + 1,
      gallery_id: gid,
      page_num: i + 1,
      filename: null,
      width: null,
      height: null,
      file_path: null,
      thumb_path: null,
      file_size: null,
      file_hash: null,
      media_type: 'image' as const,
    }))
  }, [gallery, imageMap, gid])

  const error = galleryError || imagesError

  if (error) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-black text-white">
        <div className="text-center">
          <p className="text-lg font-semibold text-red-400">Error</p>
          <p className="mt-1 text-sm opacity-70">{error.message}</p>
          <button
            onClick={() => router.back()}
            className="mt-4 px-4 py-2 bg-neutral-800 rounded text-sm hover:bg-neutral-700 transition-colors"
          >
            Go back
          </button>
        </div>
      </div>
    )
  }

  if (!gallery || !imageMap) {
    return (
      <div className="flex h-screen w-full items-center justify-center bg-black text-white">
        <div className="text-center">
          <LoadingSpinner />
          <p className="mt-3 text-sm opacity-50">
            {!gallery && galleryLoading ? 'Loading metadata...' : 'Loading image tokens...'}
          </p>
          {gallery && (
            <p className="mt-1 text-xs opacity-30">{gallery.pages} pages</p>
          )}
          {loadingTooLong && (
            <div className="mt-4 space-y-2">
              <p className="text-xs text-yellow-500">Loading is taking longer than expected...</p>
              <button
                onClick={() => router.back()}
                className="px-4 py-2 bg-neutral-800 rounded text-xs hover:bg-neutral-700 transition-colors"
              >
                Go back
              </button>
            </div>
          )}
        </div>
      </div>
    )
  }

  return (
    <Reader
      galleryId={0}
      sourceId={String(gid)}
      downloadStatus="proxy_only"
      images={images}
      totalPages={gallery.pages}
      initialPage={Math.min(startPage, gallery.pages)}
      previews={imageMap.previews}
    />
  )
}
