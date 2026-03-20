'use client'
import { useState, useEffect } from 'react'
import { t } from '@/lib/i18n'
import type { DedupScanProgress } from '@/lib/types'

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
}

function Toggle({
  enabled,
  disabled,
  ariaLabel,
  onToggle,
}: {
  enabled: boolean
  disabled?: boolean
  ariaLabel: string
  onToggle: () => void
}) {
  return (
    <button
      onClick={onToggle}
      disabled={disabled}
      aria-label={ariaLabel}
      aria-pressed={enabled}
      className={`relative shrink-0 inline-flex h-5 w-9 rounded-full border-2 border-transparent transition-colors ${
        enabled ? 'bg-green-600' : 'bg-vault-border'
      } ${disabled ? 'opacity-40 cursor-not-allowed' : ''}`}
    >
      <span
        className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition ${
          enabled ? 'translate-x-4' : 'translate-x-0'
        }`}
      />
    </button>
  )
}

function StatBadge({ label, count, accent }: { label: string; count: number; accent?: boolean }) {
  return (
    <div
      className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs ${
        accent
          ? 'bg-blue-500/10 border border-blue-500/20 text-blue-400'
          : 'bg-vault-border/40 border border-vault-border text-vault-text-muted'
      }`}
    >
      <span>{label}</span>
      <span className="font-mono font-semibold">{count}</span>
    </div>
  )
}

function ActionButton({
  icon,
  label,
  onClick,
  variant = 'default',
}: {
  icon: string
  label: string
  onClick: () => void
  variant?: 'default' | 'danger' | 'warning' | 'success'
}) {
  const variantClass = {
    default:
      'bg-vault-border/40 border border-vault-border text-vault-text-muted hover:bg-vault-border/70 hover:text-vault-text',
    danger: 'bg-red-500/10 border border-red-500/20 text-red-400 hover:bg-red-500/20',
    warning: 'bg-amber-500/10 border border-amber-500/20 text-amber-400 hover:bg-amber-500/20',
    success: 'bg-green-500/10 border border-green-500/20 text-green-400 hover:bg-green-500/20',
  }[variant]

  return (
    <button
      onClick={onClick}
      className={`flex flex-col items-center justify-center gap-0.5 w-14 py-2 rounded-lg text-[10px] font-medium transition-colors ${variantClass}`}
    >
      <span className="text-base leading-none">{icon}</span>
      <span>{label}</span>
    </button>
  )
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
      </div>
    </div>
  )
}
