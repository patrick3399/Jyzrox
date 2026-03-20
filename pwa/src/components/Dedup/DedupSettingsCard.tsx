'use client'
import { useState, useEffect } from 'react'
import { t } from '@/lib/i18n'
import { toast } from 'sonner'
import {
  useDedupStats,
  useDedupSettings,
  useUpdateDedupSetting,
  useDedupScanProgress,
  useUpdateDedupThreshold,
} from '@/hooks/useDedup'
import { api } from '@/lib/api'
import { DedupTierCard, type TierStatus } from '@/components/Dedup/DedupTierCard'
import type { DedupScanProgress } from '@/lib/types'

function getTierStatus(tier: 1 | 2 | 3, progress: DedupScanProgress, enabled: boolean): TierStatus {
  if (!enabled) return 'disabled'
  if (progress.status === 'idle') return 'idle'
  const activeTier = progress.tier ?? 1
  if (tier < activeTier) return 'complete'
  if (tier > activeTier) return 'waiting'
  return progress.status as TierStatus
}

export function DedupSettingsCard() {
  const { data: features, mutate: mutateFeatures } = useDedupSettings()
  const { data: stats } = useDedupStats()
  const { trigger: updateSetting } = useUpdateDedupSetting()
  const { trigger: triggerThreshold } = useUpdateDedupThreshold()
  const { progress, startScan, sendSignal } = useDedupScanProgress()

  const phashEnabled = features?.dedup_phash_enabled ?? false
  const heuristicEnabled = features?.dedup_heuristic_enabled ?? false
  const opencvEnabled = features?.dedup_opencv_enabled ?? false

  const [localThreshold, setLocalThreshold] = useState<number>(
    features?.dedup_phash_threshold ?? 10,
  )
  const [localOpencvThreshold, setLocalOpencvThreshold] = useState<number>(
    features?.dedup_opencv_threshold ?? 0.85,
  )

  useEffect(() => {
    setLocalThreshold(features?.dedup_phash_threshold ?? 10)
  }, [features?.dedup_phash_threshold])

  useEffect(() => {
    setLocalOpencvThreshold(features?.dedup_opencv_threshold ?? 0.85)
  }, [features?.dedup_opencv_threshold])

  const handleToggle = async (feature: string, enabled: boolean) => {
    try {
      await updateSetting({ feature, enabled })
      mutateFeatures()
      toast.success(t('dedup.settingUpdated'))
    } catch {
      toast.error(t('dedup.settingFailed'))
    }
  }

  const handleStart = async (mode: 'reset' | 'pending') => {
    try {
      await startScan(mode)
      toast.success(t('dedup.scanQueued'))
    } catch {
      toast.error(t('dedup.scanFailed'))
    }
  }

  const handleSignal = async (signal: 'pause' | 'resume' | 'stop') => {
    try {
      await sendSignal(signal)
    } catch {
      toast.error(t('dedup.scanSignalFailed'))
    }
  }

  // Per-tier stat counts
  const activeTier = progress.tier ?? 1
  const isScanning = progress.status !== 'idle'

  const t1Processing = isScanning && activeTier === 1 ? (progress.current ?? 0) : 0
  const t1Pending =
    isScanning && activeTier === 1
      ? Math.max(0, (progress.total ?? 0) - (progress.current ?? 0))
      : 0

  const t2Processing = isScanning && activeTier === 2 ? (progress.current ?? 0) : 0
  const t2Pending =
    isScanning && activeTier === 2
      ? Math.max(0, (progress.total ?? 0) - (progress.current ?? 0))
      : (stats?.needs_t2 ?? 0)

  const t3Processing = isScanning && activeTier === 3 ? (progress.current ?? 0) : 0
  const t3Pending =
    isScanning && activeTier === 3
      ? Math.max(0, (progress.total ?? 0) - (progress.current ?? 0))
      : (stats?.needs_t3 ?? 0)

  const tier1Status = getTierStatus(1, progress, phashEnabled)
  const tier2Status = getTierStatus(2, progress, heuristicEnabled)
  const tier3Status = getTierStatus(3, progress, opencvEnabled)

  return (
    <div className="space-y-3">
      {/* Tier 0 note */}
      <p className="text-xs text-vault-text-muted px-1">{t('dedup.tier0Note')}</p>

      {/* Tier 1 */}
      <DedupTierCard
        tier={1}
        title="dedup.tier1"
        description="dedup.tier1Desc"
        enabled={phashEnabled}
        onToggle={(enabled) => handleToggle('dedup_phash_enabled', enabled)}
        threshold={localThreshold}
        thresholdMin={0}
        thresholdMax={20}
        thresholdStep={1}
        thresholdLabel="dedup.hammingThreshold"
        thresholdDesc="dedup.hammingThresholdDesc"
        onThresholdChange={setLocalThreshold}
        onThresholdCommit={async (v) => {
          try {
            await triggerThreshold(v)
            mutateFeatures()
          } catch {
            toast.error(t('dedup.settingFailed'))
          }
        }}
        tierStatus={tier1Status}
        progress={progress}
        processing={t1Processing}
        pending={t1Pending}
        onStart={handleStart}
        onSignal={handleSignal}
      />

      {/* Tier 2 */}
      <DedupTierCard
        tier={2}
        title="dedup.tier2"
        description="dedup.tier2Desc"
        enabled={heuristicEnabled}
        onToggle={(enabled) => handleToggle('dedup_heuristic_enabled', enabled)}
        requiresTier1
        tier1Enabled={phashEnabled}
        tierStatus={tier2Status}
        progress={progress}
        processing={t2Processing}
        pending={t2Pending}
        onStart={handleStart}
        onSignal={handleSignal}
      />

      {/* Tier 3 */}
      <DedupTierCard
        tier={3}
        title="dedup.tier3"
        description="dedup.tier3Desc"
        enabled={opencvEnabled}
        onToggle={(enabled) => handleToggle('dedup_opencv_enabled', enabled)}
        threshold={localOpencvThreshold}
        thresholdMin={0.5}
        thresholdMax={1.0}
        thresholdStep={0.01}
        thresholdLabel="dedup.opencvThreshold"
        thresholdDesc="dedup.opencvThresholdDesc"
        onThresholdChange={setLocalOpencvThreshold}
        onThresholdCommit={async (v) => {
          try {
            await api.settings.setFeatureValue('dedup_opencv_threshold', v)
            mutateFeatures()
          } catch {
            toast.error(t('dedup.settingFailed'))
          }
        }}
        requiresTier1
        tier1Enabled={phashEnabled}
        tierStatus={tier3Status}
        progress={progress}
        processing={t3Processing}
        pending={t3Pending}
        onStart={handleStart}
        onSignal={handleSignal}
      />
    </div>
  )
}
