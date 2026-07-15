'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { t } from '@/lib/i18n'
import { useStatusBarClock } from './hooks'
import type { ReaderSettings, ReadingDirection, ViewMode } from './types'

// ── SeekBar ───────────────────────────────────────────────────────────

function SeekBar({
  currentPage,
  totalPages,
  onSeek,
  readingDirection,
}: {
  currentPage: number
  totalPages: number
  onSeek: (page: number) => void
  readingDirection?: 'ltr' | 'rtl' | 'vertical'
}) {
  const barRef = useRef<HTMLDivElement>(null)
  const [dragging, setDragging] = useState(false)
  const [previewPage, setPreviewPage] = useState<number | null>(null)
  const draggingRef = useRef(false)

  const isRtl = readingDirection === 'rtl'
  const getPageFromX = useCallback(
    (clientX: number) => {
      if (!barRef.current) return currentPage
      const rect = barRef.current.getBoundingClientRect()
      let ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width))
      if (isRtl) ratio = 1 - ratio
      return Math.max(1, Math.round(ratio * totalPages))
    },
    [currentPage, totalPages, isRtl],
  )

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation()
    onSeek(getPageFromX(e.clientX))
  }

  const handleMouseDown = (e: React.MouseEvent) => {
    e.stopPropagation()
    draggingRef.current = true
    setDragging(true)
    setPreviewPage(getPageFromX(e.clientX))
    e.preventDefault()
  }

  useEffect(() => {
    if (!dragging) return
    const handleMouseMove = (e: MouseEvent) => {
      if (draggingRef.current) setPreviewPage(getPageFromX(e.clientX))
    }
    const handleMouseUp = (e: MouseEvent) => {
      if (draggingRef.current) {
        const page = getPageFromX(e.clientX)
        onSeek(page)
      }
      draggingRef.current = false
      setDragging(false)
      setPreviewPage(null)
    }
    window.addEventListener('mousemove', handleMouseMove)
    window.addEventListener('mouseup', handleMouseUp)
    return () => {
      window.removeEventListener('mousemove', handleMouseMove)
      window.removeEventListener('mouseup', handleMouseUp)
    }
  }, [dragging, getPageFromX, onSeek])

  const handleTouchStart = (e: React.TouchEvent) => {
    e.stopPropagation()
    draggingRef.current = true
    setDragging(true)
    setPreviewPage(getPageFromX(e.touches[0].clientX))
  }

  const handleTouchMove = (e: React.TouchEvent) => {
    e.stopPropagation()
    if (draggingRef.current) setPreviewPage(getPageFromX(e.touches[0].clientX))
  }

  const handleTouchEnd = (e: React.TouchEvent) => {
    e.stopPropagation()
    if (previewPage != null) onSeek(previewPage)
    draggingRef.current = false
    setDragging(false)
    setPreviewPage(null)
  }

  const displayPage = previewPage ?? currentPage
  const progress = totalPages > 1 ? ((displayPage - 1) / (totalPages - 1)) * 100 : 0

  return (
    <div
      ref={barRef}
      className="flex-1 relative cursor-pointer py-2 -my-2 select-none"
      onClick={handleClick}
      onMouseDown={handleMouseDown}
      onTouchStart={handleTouchStart}
      onTouchMove={handleTouchMove}
      onTouchEnd={handleTouchEnd}
    >
      <div className="h-1.5 rounded-full bg-white/20 relative">
        <div
          className="h-full rounded-full bg-white/70"
          style={isRtl ? { width: `${progress}%`, marginLeft: 'auto' } : { width: `${progress}%` }}
        />
        <div
          className="absolute w-3 h-3 rounded-full bg-white shadow"
          style={
            isRtl
              ? { right: `${progress}%`, top: '50%', transform: 'translate(50%, -50%)' }
              : { left: `${progress}%`, top: '50%', transform: 'translate(-50%, -50%)' }
          }
        />
      </div>
      {previewPage != null && (
        <div
          className="absolute -top-8 bg-black/80 text-white text-xs px-2 py-1 rounded pointer-events-none"
          style={
            isRtl
              ? { right: `${progress}%`, transform: 'translateX(50%)' }
              : { left: `${progress}%`, transform: 'translateX(-50%)' }
          }
        >
          {previewPage}
        </div>
      )}
    </div>
  )
}

// ── StatusBar ─────────────────────────────────────────────────────────

interface StatusBarProps {
  currentPage: number
  totalPages: number
  settings: ReaderSettings
  countdown: number
  autoAdvanceEnabled: boolean
  onPageSelect: (page: number) => void
  readingDirection?: 'ltr' | 'rtl' | 'vertical'
}

export function StatusBar({
  currentPage,
  totalPages,
  settings,
  countdown,
  autoAdvanceEnabled,
  onPageSelect,
  readingDirection,
}: StatusBarProps) {
  const clock = useStatusBarClock(settings.statusBarEnabled && settings.statusBarShowClock)

  if (!settings.statusBarEnabled) return null

  return (
    <div
      className="reader-status-bar flex items-center gap-3 px-3"
      style={{ height: 24, background: 'rgba(0,0,0,0.55)' }}
    >
      {settings.statusBarShowClock && clock && (
        <span className="text-[11px] text-white/80 tabular-nums shrink-0">{clock}</span>
      )}

      {settings.statusBarShowProgress && (
        <SeekBar
          currentPage={currentPage}
          totalPages={totalPages}
          onSeek={onPageSelect}
          readingDirection={readingDirection}
        />
      )}

      {settings.statusBarShowPageCount && (
        <span className="text-[11px] text-white/80 tabular-nums shrink-0">
          {currentPage} / {totalPages}
        </span>
      )}

      {autoAdvanceEnabled && (
        <span className="text-[11px] text-white/60 tabular-nums shrink-0">{countdown}s</span>
      )}
    </div>
  )
}

// ── HelpOverlay ───────────────────────────────────────────────────────

interface HelpOverlayProps {
  readingDirection: ReadingDirection
  viewMode: ViewMode
  onDismiss: () => void
}

export function HelpOverlay({ readingDirection, viewMode, onDismiss }: HelpOverlayProps) {
  const isRtl = readingDirection === 'rtl'
  const isVertical = readingDirection === 'vertical'

  const leftLabel = isRtl ? t('reader.helpTapRight') : t('reader.helpTapLeft')
  const rightLabel = isRtl ? t('reader.helpTapLeft') : t('reader.helpTapRight')

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      onDismiss()
      e.stopPropagation()
    }
    window.addEventListener('keydown', handler, { once: true })
    return () => window.removeEventListener('keydown', handler)
  }, [onDismiss])

  return (
    <div className="absolute inset-0 z-50 flex flex-col" onClick={onDismiss}>
      {viewMode === 'webtoon' ? (
        /* Webtoon mode: only center tap zone */
        <div className="flex flex-1 items-center justify-center bg-white/5">
          <div className="text-white text-sm font-medium">{t('reader.helpTapCenter')}</div>
        </div>
      ) : isVertical ? (
        /* Vertical direction: top/middle/bottom zones */
        <div className="flex flex-col flex-1">
          <div className="h-[30%] w-full flex items-center justify-center bg-blue-500/20 border-b border-blue-400/30">
            <div className="text-white text-sm font-medium">{t('reader.helpTapLeft')}</div>
          </div>
          <div className="flex-1 w-full flex items-center justify-center bg-white/5 border-b border-white/10">
            <div className="text-white text-sm font-medium">{t('reader.helpTapCenter')}</div>
          </div>
          <div className="h-[30%] w-full flex items-center justify-center bg-green-500/20">
            <div className="text-white text-sm font-medium">{t('reader.helpTapRight')}</div>
          </div>
        </div>
      ) : (
        /* Horizontal direction: left/center/right zones */
        <div className="flex flex-1">
          <div className="w-[30%] h-full flex items-center justify-center bg-blue-500/20 border-r border-blue-400/30">
            <div className="text-center">
              <div className="text-white text-sm font-medium">{leftLabel}</div>
            </div>
          </div>
          <div className="flex-1 h-full flex items-center justify-center bg-white/5 border-r border-white/10">
            <div className="text-center">
              <div className="text-white text-sm font-medium">{t('reader.helpTapCenter')}</div>
            </div>
          </div>
          <div className="w-[30%] h-full flex items-center justify-center bg-green-500/20">
            <div className="text-center">
              <div className="text-white text-sm font-medium">{rightLabel}</div>
            </div>
          </div>
        </div>
      )}

      {/* Bottom info */}
      <div className="absolute bottom-20 left-0 right-0 flex flex-col items-center gap-2 pointer-events-none">
        <div className="bg-black/80 rounded-lg px-4 py-3 text-center space-y-1.5 max-w-sm">
          {viewMode === 'webtoon' ? (
            <p className="text-white text-sm">{t('reader.helpSwipeRight')}</p>
          ) : (
            <>
              <p className="text-white text-sm">{t('reader.helpSwipe')}</p>
              <p className="text-white/70 text-xs">{t('reader.helpSwipeUp')}</p>
            </>
          )}
          <p className="text-white/70 text-xs">{t('reader.helpDoubleTap')}</p>
          <p className="text-white/70 text-xs">{t('reader.helpPinchZoom')}</p>
          <p className="text-white/60 text-xs">{t('reader.helpKeyboard')}</p>
          <p className="text-white/40 text-xs">{t('reader.helpDismiss')}</p>
        </div>
      </div>
    </div>
  )
}

// ── Reader (main component) ───────────────────────────────────────────
