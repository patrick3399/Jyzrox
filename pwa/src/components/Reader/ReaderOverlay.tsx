'use client'
import { useEffect, useRef, useState } from 'react'
import type { ViewMode, ScaleMode, ReadingDirection } from './types'
import { t } from '@/lib/i18n'

interface ReaderOverlayProps {
  currentPage: number
  totalPages: number
  viewMode: ViewMode
  scaleMode: ScaleMode
  readingDirection: ReadingDirection
  autoAdvanceEnabled: boolean
  autoAdvanceSeconds: number
  onBack: () => void
  onViewModeChange: (mode: ViewMode) => void
  onScaleModeChange: (mode: ScaleMode) => void
  onReadingDirectionChange: (dir: ReadingDirection) => void
  onAutoAdvanceToggle: () => void
  onAutoAdvanceIntervalChange: (s: number) => void
  onShowHelp: () => void
  onPageSelect: (page: number) => void
  onOpenGrid: () => void
}

export function ReaderOverlay({
  currentPage,
  totalPages,
  viewMode,
  scaleMode,
  readingDirection,
  autoAdvanceEnabled,
  autoAdvanceSeconds,
  onBack,
  onViewModeChange,
  onScaleModeChange,
  onReadingDirectionChange,
  onAutoAdvanceToggle,
  onAutoAdvanceIntervalChange,
  onShowHelp,
  onPageSelect,
  onOpenGrid,
}: ReaderOverlayProps) {
  const VIEW_MODES: { mode: ViewMode; icon: string; label: string }[] = [
    { mode: 'single', icon: '▣', label: t('reader.viewModeSingleShort') },
    { mode: 'webtoon', icon: '▥', label: t('reader.viewModeWebtoonShort') },
    { mode: 'double', icon: '◫', label: t('reader.viewModeDoubleShort') },
  ]

  const SCALE_MODES: { mode: ScaleMode; icon: string; label: string }[] = [
    { mode: 'fit-both', icon: '⊞', label: t('reader.scaleFitBothShort') },
    { mode: 'fit-width', icon: '↔', label: t('reader.scaleFitWidthShort') },
    { mode: 'fit-height', icon: '↕', label: t('reader.scaleFitHeightShort') },
    { mode: 'original', icon: '1:1', label: t('reader.scaleOriginalShort') },
  ]

  const DIRECTIONS: { dir: ReadingDirection; icon: string; label: string }[] = [
    { dir: 'ltr', icon: '→', label: t('reader.dirLtrShort') },
    { dir: 'rtl', icon: '←', label: t('reader.dirRtlShort') },
    { dir: 'vertical', icon: '↓', label: t('reader.dirVerticalShort') },
  ]

  const cycleViewMode = () => {
    const idx = VIEW_MODES.findIndex((v) => v.mode === viewMode)
    onViewModeChange(VIEW_MODES[(idx + 1) % VIEW_MODES.length].mode)
  }

  const cycleScaleMode = () => {
    const idx = SCALE_MODES.findIndex((s) => s.mode === scaleMode)
    onScaleModeChange(SCALE_MODES[(idx + 1) % SCALE_MODES.length].mode)
  }

  const cycleDirection = () => {
    const idx = DIRECTIONS.findIndex((d) => d.dir === readingDirection)
    onReadingDirectionChange(DIRECTIONS[(idx + 1) % DIRECTIONS.length].dir)
  }

  const currentView = VIEW_MODES.find((v) => v.mode === viewMode) ?? VIEW_MODES[0]
  const currentScale = SCALE_MODES.find((s) => s.mode === scaleMode) ?? SCALE_MODES[0]
  const currentDir = DIRECTIONS.find((d) => d.dir === readingDirection) ?? DIRECTIONS[0]

  const cycleBtnClass =
    'w-10 h-10 rounded text-lg font-medium transition-colors bg-white/10 hover:bg-white/20 text-white border border-white/20 flex items-center justify-center shrink-0'

  // Page jump dialog
  const [showJump, setShowJump] = useState(false)
  const [jumpInput, setJumpInput] = useState('')
  const jumpInputRef = useRef<HTMLInputElement>(null)

  const openJump = () => {
    setJumpInput(String(currentPage))
    setShowJump(true)
  }

  const closeJump = () => setShowJump(false)

  const commitJump = () => {
    const page = parseInt(jumpInput, 10)
    if (!isNaN(page) && page >= 1 && page <= totalPages) {
      onPageSelect(page)
    }
    closeJump()
  }

  useEffect(() => {
    if (showJump) {
      // Only auto-focus on non-touch devices; on mobile, focusing triggers
      // the soft keyboard which shifts the iOS visual viewport.
      const isTouch = window.matchMedia('(pointer: coarse)').matches
      if (isTouch) return
      const t = setTimeout(() => jumpInputRef.current?.select(), 50)
      return () => clearTimeout(t)
    }
  }, [showJump])

  useEffect(() => {
    if (!showJump) return
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeJump()
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [showJump])

  return (
    <div
      className="bg-black/70 text-white text-sm backdrop-blur-sm"
      style={{ paddingTop: 'min(env(safe-area-inset-top), 45px)' }}
    >
      {/* Row 1: page indicator · cycle buttons (left-aligned) · auto-advance toggle · help · close */}
      <div className="flex items-center gap-2 px-4 py-2">
        {/* Page indicator */}
        <div className="relative">
          <button
            onClick={openJump}
            className="font-mono tabular-nums whitespace-nowrap text-xs bg-white/10 hover:bg-white/20 rounded px-1.5 py-0.5 transition-colors"
            title={t('reader.jumpToPage')}
          >
            {currentPage} / {totalPages}
          </button>
          {showJump && (
            <>
              <div className="fixed inset-0 z-30" onClick={closeJump} />
              <div className="absolute top-full left-0 mt-1 z-40 bg-black/90 border border-white/20 rounded-lg p-3 flex items-center gap-2 shadow-xl min-w-[140px]">
                <input
                  ref={jumpInputRef}
                  type="number"
                  min={1}
                  max={totalPages}
                  value={jumpInput}
                  onChange={(e) => setJumpInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') commitJump()
                    else if (e.key === 'Escape') closeJump()
                    e.stopPropagation()
                  }}
                  className="w-16 bg-white/10 border border-white/20 rounded px-2 py-1 text-xs text-white text-center tabular-nums focus:outline-none focus:border-white/50"
                />
                <button
                  onClick={commitJump}
                  className="bg-white text-black rounded px-2 py-1 text-xs font-medium hover:bg-white/90 shrink-0"
                >
                  {t('reader.go')}
                </button>
              </div>
            </>
          )}
        </div>

        {/* Cycle buttons immediately after page indicator */}
        <button onClick={cycleViewMode} className={cycleBtnClass} title={currentView.label}>
          <span>{currentView.icon}</span>
        </button>
        <button onClick={cycleScaleMode} className={cycleBtnClass} title={currentScale.label}>
          <span>{currentScale.icon}</span>
        </button>
        {viewMode !== 'webtoon' && (
          <button onClick={cycleDirection} className={cycleBtnClass} title={currentDir.label}>
            <span>{currentDir.icon}</span>
          </button>
        )}
        <button
          onClick={onOpenGrid}
          className={cycleBtnClass}
          title={t('reader.gridOverview')}
          aria-label={t('reader.gridOverview')}
        >
          <span>▦</span>
        </button>

        <div className="flex-1" />

        {/* Auto advance toggle only (slider in Row 2 when enabled) */}
        <button
          onClick={onAutoAdvanceToggle}
          className={`relative w-9 h-5 rounded-full transition-colors shrink-0 ${autoAdvanceEnabled ? 'bg-vault-accent' : 'bg-white/20'}`}
          aria-label={t('reader.autoAdvance')}
          title={t('reader.autoAdvance')}
        >
          <span
            className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform ${autoAdvanceEnabled ? 'translate-x-4' : ''}`}
          />
        </button>

        {/* Help + Close */}
        <button
          onClick={onShowHelp}
          className="w-10 h-10 rounded bg-white/10 hover:bg-white/20 border border-white/20 text-white/80 hover:text-white transition-colors flex items-center justify-center shrink-0"
          title={t('reader.helpButton')}
        >
          ?
        </button>
        <button
          onClick={onBack}
          className="w-10 h-10 rounded bg-red-600 hover:bg-red-500 text-white font-bold transition-colors flex items-center justify-center shrink-0"
          title={t('reader.goBack')}
        >
          ✕
        </button>
      </div>

      {/* Row 2: auto advance slider — only shown when enabled */}
      {autoAdvanceEnabled && (
        <div className="flex items-center gap-2 px-4 pb-2">
          <span className="text-[11px] text-white/60 shrink-0">{t('reader.autoAdvance')}</span>
          <input
            type="range"
            min={2}
            max={30}
            step={1}
            value={autoAdvanceSeconds}
            onChange={(e) => onAutoAdvanceIntervalChange(Number(e.target.value))}
            className="flex-1 accent-white"
          />
          <span className="text-[11px] tabular-nums whitespace-nowrap w-6 text-right">
            {autoAdvanceSeconds}s
          </span>
        </div>
      )}
    </div>
  )
}
