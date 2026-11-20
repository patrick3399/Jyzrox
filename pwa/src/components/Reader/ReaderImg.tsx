'use client'
import { createContext, useContext, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import type { ReaderImage } from './types'
import { t } from '@/lib/i18n'

// ── Retry layer ───────────────────────────────────────────────────────
// The paged views stack their tap zones over the page, and the image scale
// classes switch pointer events off, so a Retry button rendered inside the page
// can never take a tap. Those views expose a layer above the zones and a failed
// page renders its notice there. With no layer (webtoon) the notice stays inline.
export const RetryLayerContext = createContext<HTMLElement | null>(null)

interface ReaderImgProps {
  image: ReaderImage
  className?: string
  style?: React.CSSProperties
  draggable?: boolean
  loading?: 'lazy' | 'eager'
  dataPage?: number
  innerRef?: React.Ref<HTMLImageElement>
  onLoad?: () => void
  onError?: () => void
}

// Transient load errors are expected in EH proxy mode: a direct page jump
// races the paginated pToken fetch, so /api/eh/image-proxy 404s until the
// token lands in Redis (seconds later). Auto-retry with backoff before
// latching the terminal failure UI.
const AUTO_RETRY_DELAYS_MS = [1000, 2000, 3000, 5000, 8000]

export function ReaderImg({
  image,
  className,
  style,
  draggable = false,
  loading,
  dataPage,
  innerRef,
  onLoad,
  onError,
}: ReaderImgProps) {
  const [failed, setFailed] = useState(false)
  const [retryWait, setRetryWait] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [autoRetriesUsed, setAutoRetriesUsed] = useState(0)
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  // Reset error/retry state whenever the underlying image changes.
  const url = image.url
  useEffect(() => {
    clearTimeout(retryTimerRef.current)
    retryTimerRef.current = undefined
    setFailed(false)
    setRetryWait(false)
    setAttempt(0)
    setAutoRetriesUsed(0)
  }, [url])

  // Cancel any pending auto-retry on unmount.
  useEffect(() => () => clearTimeout(retryTimerRef.current), [])

  const retryLayer = useContext(RetryLayerContext)

  if (failed) {
    const notice = (
      <div className="flex flex-col items-center gap-2">
        <span className="text-3xl text-white/40" aria-hidden>
          ⚠
        </span>
        <p className="text-xs text-white/60">{t('reader.imageLoadFailed')}</p>
        <button
          onClick={(e) => {
            e.stopPropagation()
            setFailed(false)
            setAutoRetriesUsed(0)
            setAttempt((a) => a + 1)
          }}
          className="pointer-events-auto rounded bg-white/10 px-3 py-1 text-xs text-white hover:bg-white/20"
        >
          {t('reader.retry')}
        </button>
      </div>
    )
    return (
      <div
        className={`flex flex-col items-center justify-center bg-black/50 ${className ?? ''}`}
        style={{ minHeight: '200px', minWidth: '200px', ...style }}
      >
        {retryLayer ? createPortal(notice, retryLayer) : notice}
      </div>
    )
  }

  // Waiting for an auto-retry: show a quiet loading placeholder instead of
  // the browser's broken-image icon (the parent spinner keeps spinning —
  // onError is only propagated once retries are exhausted).
  if (retryWait) {
    return (
      <div
        role="status"
        aria-label={t('common.loading')}
        className={`flex items-center justify-center bg-black/50 ${className ?? ''}`}
        style={{ minHeight: '200px', minWidth: '200px', ...style }}
      >
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-white/20 border-t-white/60" />
      </div>
    )
  }

  // Cache-buster forces a real network re-request on retry.
  const src =
    attempt > 0 && url ? `${url}${url.includes('?') ? '&' : '?'}_r=${attempt}` : (url ?? '')
  const canAutoRetry = Boolean(url?.startsWith('/api/eh/image-proxy/'))

  return (
    <img
      ref={innerRef}
      src={src}
      alt={`Page ${image.pageNum}`}
      className={className}
      style={style}
      draggable={draggable}
      loading={loading}
      data-page={dataPage}
      onLoad={onLoad}
      onError={() => {
        if (canAutoRetry && autoRetriesUsed < AUTO_RETRY_DELAYS_MS.length) {
          const delay = AUTO_RETRY_DELAYS_MS[autoRetriesUsed]
          setAutoRetriesUsed(autoRetriesUsed + 1)
          setRetryWait(true)
          retryTimerRef.current = setTimeout(() => {
            setAttempt((a) => a + 1)
            setRetryWait(false)
          }, delay)
        } else {
          setFailed(true)
          onError?.()
        }
      }}
    />
  )
}
