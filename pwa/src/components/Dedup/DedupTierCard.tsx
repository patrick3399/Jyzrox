'use client'
import { useState, useEffect } from 'react'
import { t } from '@/lib/i18n'
import type { DedupScanProgress } from '@/lib/types'
import { Toggle, StatBadge, ActionButton } from './DedupTierParts'

export type TierStatus = 'idle' | 'running' | 'paused' | 'complete' | 'waiting' | 'disabled'

interface Props {
  tier: 1 | 2 | 3
  title: string
  description: string
  enabled: boolean
  onToggle: (enabled: boolean) => void
  // Threshold (T1 and T3 only)
  threshold?: number
  thresholdMin?: number
  thresholdMax?: number
  thresholdStep?: number
  thresholdLabel?: string
  thresholdDesc?: string
  onThresholdChange?: (value: number) => void
  onThresholdCommit?: (value: number) => void
  // Tier 2/3 dependency
  requiresTier1?: boolean
  tier1Enabled?: boolean
  // Progress
  tierStatus: TierStatus
  progress: DedupScanProgress
  // Stats
  processing: number
  pending: number
  // Actions
  onStart: (mode: 'reset' | 'pending') => Promise<void>
  onSignal: (signal: 'pause' | 'resume' | 'stop') => Promise<void>
  showScanControls?: boolean
}

export function DedupTierCard({
  tier,
  title,
  description,
  enabled,
  onToggle,
  threshold,
  thresholdMin,
  thresholdMax,
  thresholdStep,
  thresholdLabel,
  thresholdDesc,
  onThresholdChange,
  onThresholdCommit,
  requiresTier1,
  tier1Enabled,
  tierStatus,
  progress,
  processing,
  pending,
  onStart,
  onSignal,
  showScanControls = false,
}: Props) {
  const [localThreshold, setLocalThreshold] = useState<number>(threshold ?? 0)

  useEffect(() => {
    if (threshold !== undefined) setLocalThreshold(threshold)
  }, [threshold])

  const isRunning = tierStatus === 'running'
  const isPaused = tierStatus === 'paused'
  const isActive = isRunning || isPaused
  const isDisabledByDep = requiresTier1 && !tier1Enabled

  // Progress bar
  const percent = isActive ? (progress.percent ?? 0) : 0
  const progressBarColor = isRunning ? 'bg-green-500' : 'bg-amber-500'
  const showProgressBar = isActive

  // Status label
  const statusLabel = {
    idle: null,
    running: null,
    paused: null,
    complete: t('dedup.tierComplete'),
    waiting: t('dedup.tierWaiting'),
    disabled: null,
  }[tierStatus]

  // Toggle aria labels by tier
  const enableLabel =
    tier === 1
      ? t('dedup.enableTier1')
      : tier === 2
        ? t('dedup.enableTier2')
        : t('dedup.enableTier3')
  const disableLabel =
    tier === 1
      ? t('dedup.disableTier1')
      : tier === 2
        ? t('dedup.disableTier2')
        : t('dedup.disableTier3')

  return (
    <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
      {/* Progress bar at top */}
      <div className="h-1 w-full bg-vault-border/30">
        {showProgressBar && (
          <div
            className={`h-full ${progressBarColor} transition-all duration-500 ${isRunning ? 'animate-pulse' : ''}`}
            style={{ width: `${percent}%` }}
          />
        )}
      </div>

      <div className="flex items-stretch">
        {/* Left: content */}
        <div className="flex-1 px-5 py-4 space-y-3 min-w-0">
          {/* Title row */}
          <div className="flex items-center gap-2.5">
            <Toggle
              enabled={enabled}
              disabled={!!isDisabledByDep}
              ariaLabel={enabled ? disableLabel : enableLabel}
              onToggle={() => !isDisabledByDep && onToggle(!enabled)}
            />
            <span
              className={`text-sm font-medium ${!enabled || isDisabledByDep ? 'text-vault-text-muted' : 'text-vault-text'}`}
            >
              {t(title)}
            </span>
            {statusLabel && (
              <span className="ml-auto shrink-0 px-2 py-0.5 rounded text-[10px] font-medium bg-vault-border/40 text-vault-text-muted border border-vault-border">
                {statusLabel}
              </span>
            )}
            {isActive && (
              <span className="ml-auto shrink-0 text-[10px] font-mono text-vault-text-muted">
                {percent}%
              </span>
            )}
          </div>

          {/* Description */}
          <p className="text-xs text-vault-text-muted pl-[52px]">{t(description)}</p>

          {/* Dependency warning */}
          {isDisabledByDep && (
            <p className="text-[10px] text-yellow-500/70 pl-[52px]">
              {t('dedup.tier2RequiresTier1')}
            </p>
          )}

          {/* Threshold slider */}
          {enabled && !isDisabledByDep && threshold !== undefined && thresholdLabel && (
            <div className="pl-[52px] space-y-1">
              <div className="flex items-center justify-between">
                <p className="text-xs text-vault-text-muted">{t(thresholdLabel)}</p>
                <span className="text-xs font-mono text-vault-text">
                  {thresholdStep && thresholdStep < 1 ? localThreshold.toFixed(2) : localThreshold}
                </span>
              </div>
              <input
                type="range"
                min={thresholdMin}
                max={thresholdMax}
                step={thresholdStep}
                value={localThreshold}
                onChange={(e) => {
                  const v = Number(e.target.value)
                  setLocalThreshold(v)
                  onThresholdChange?.(v)
                }}
                onPointerUp={(e) => {
                  const v = Number((e.target as HTMLInputElement).value)
                  onThresholdCommit?.(v)
                }}
                className="w-full accent-vault-accent"
              />
              {thresholdDesc && (
                <p className="text-[10px] text-vault-text-muted">{t(thresholdDesc)}</p>
              )}
            </div>
          )}

          {/* Stats badges */}
          {enabled && !isDisabledByDep && (
            <div className="flex items-center gap-2 pl-[52px]">
              <StatBadge label={t('dedup.processing')} count={processing} accent />
              <StatBadge label={t('dedup.pending')} count={pending} />
            </div>
          )}
        </div>

        {/* Right: action buttons */}
        {showScanControls && (
          <div className="flex flex-col items-center justify-center gap-2 px-3 py-4 border-l border-vault-border/50 shrink-0">
            {tierStatus === 'idle' && (
              <>
                <ActionButton
                  icon="∞"
                  label={t('dedup.scanReset')}
                  onClick={() => onStart('reset')}
                />
                <ActionButton
                  icon="▷"
                  label={t('dedup.scanPending')}
                  onClick={() => onStart('pending')}
                  variant="success"
                />
              </>
            )}
            {isRunning && (
              <>
                <ActionButton
                  icon="⏸"
                  label={t('dedup.scanPause')}
                  onClick={() => onSignal('pause')}
                  variant="warning"
                />
                <ActionButton
                  icon="⏹"
                  label={t('dedup.scanStop')}
                  onClick={() => onSignal('stop')}
                  variant="danger"
                />
              </>
            )}
            {isPaused && (
              <>
                <ActionButton
                  icon="▶"
                  label={t('dedup.scanResume')}
                  onClick={() => onSignal('resume')}
                  variant="success"
                />
                <ActionButton
                  icon="⏹"
                  label={t('dedup.scanStop')}
                  onClick={() => onSignal('stop')}
                  variant="danger"
                />
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
