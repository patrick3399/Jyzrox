'use client'

import { Button } from '@/components/ui/button'
import { useMemo, useState, useEffect, Suspense, useCallback } from 'react'
import { useParams, useSearchParams, useRouter } from 'next/navigation'
import { useEhGallery, useEhGalleryImagesPaginated } from '@/hooks/useGalleries'
import Reader from '@/components/Reader'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { ReaderFallbackScreen } from '@/components/Reader/ReaderFallbackScreen'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { t } from '@/lib/i18n'
import { smartBack } from '@/lib/navBack'
import type { GalleryImage } from '@/lib/types'

export default function EhProxyReaderPageWrapper() {
  return (
    <Suspense
      fallback={
        <div className="flex items-center justify-center h-screen">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-white" />
        </div>
      }
    >
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

  const totalPages = gallery?.pages ?? 0

  const {
    tokenMap,
    previewMap,
    isLoading: tokensLoading,
    error: tokensError,
    onPageChange,
    fetchUpTo,
  } = useEhGalleryImagesPaginated(gid, token, totalPages)

  // Track loading time for slow-connection UX
  const [loadingTooLong, setLoadingTooLong] = useState(false)
  useEffect(() => {
    // Consider ready once gallery metadata AND at least one batch of tokens is loaded
    const hasTokens = Object.keys(tokenMap).length > 0
    if (gallery && hasTokens) return
    const timer = setTimeout(() => setLoadingTooLong(true), 8000)
    return () => clearTimeout(timer)
  }, [gallery, tokenMap])

  // Build GalleryImage[] — only create entries for pages whose token is known.
  // Pages without tokens yet are omitted; Reader handles sparse page sets via page_num.
  const images: GalleryImage[] = useMemo(() => {
    if (!gallery || totalPages === 0) return []
    return Array.from({ length: totalPages }, (_, i) => ({
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
      duration: null,
    }))
  }, [gallery, totalPages, gid])

  // Handler passed to Reader so it can notify us when the page changes.
  // The paginated hook uses this to prefetch the next batch.
  const handlePageChange = useCallback(
    (page: number) => {
      onPageChange(page)
    },
    [onPageChange],
  )

  const error = galleryError || tokensError
  // Every exit goes back to the gallery this reader was opened from. A reader
  // URL with nothing behind it (shared link, new tab, PWA relaunch) has no
  // history to step back through, and an unparseable id has no gallery page.
  const backHref = isNaN(gid) ? '/e-hentai' : `/e-hentai/${gid}/${token}`
  const hasInitialTokens = Object.keys(tokenMap).length > 0

  if (isNaN(gid)) {
    return (
      <ReaderFallbackScreen backHref={backHref}>
        <div className="text-center">
          <p className="text-lg font-semibold text-red-400">{t('common.error')}</p>
          <p className="mt-1 text-sm opacity-70">{t('common.invalidId')}</p>
        </div>
      </ReaderFallbackScreen>
    )
  }

  if (error) {
    return (
      <ReaderFallbackScreen backHref={backHref}>
        <div className="text-center">
          <p className="text-lg font-semibold text-red-400">{t('common.error')}</p>
          <p className="mt-1 text-sm opacity-70">{error.message}</p>
          <Button variant="secondary" size="md" className="mt-4"
            onClick={() => smartBack(router, backHref)}
          >
            {t('common.goBack')}
          </Button>
        </div>
      </ReaderFallbackScreen>
    )
  }

  // Wait for gallery metadata + first batch of tokens before showing Reader.
  if (!gallery || !hasInitialTokens) {
    return (
      <ReaderFallbackScreen backHref={backHref}>
        <div className="text-center">
          <LoadingSpinner />
          <p className="mt-3 text-sm opacity-50">
            {!gallery && galleryLoading
              ? t('reader.loadingMetadata')
              : tokensLoading
                ? t('reader.loadingTokens')
                : t('reader.preparingReader')}
          </p>
          {gallery && (
            <p className="mt-1 text-xs opacity-30">
              {gallery.pages} {t('browse.pages')}
            </p>
          )}
          {loadingTooLong && (
            <div className="mt-4 space-y-2">
              <p className="text-xs text-yellow-500">{t('reader.loadingTooLong')}</p>
              <Button variant="secondary" size="sm" className="text-xs"
                onClick={() => smartBack(router, backHref)}
              >
                {t('common.goBack')}
              </Button>
            </div>
          )}
        </div>
      </ReaderFallbackScreen>
    )
  }

  return (
    <ErrorBoundary>
      <Reader
        source="ehentai"
        sourceId={String(gid)}
        downloadStatus="proxy_only"
        images={images}
        totalPages={gallery.pages}
        initialPage={Math.min(startPage, gallery.pages)}
        previews={previewMap}
        onPageChange={handlePageChange}
        onSeekToPage={fetchUpTo}
        backHref={backHref}
      />
    </ErrorBoundary>
  )
}
