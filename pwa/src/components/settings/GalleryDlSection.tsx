'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import type { GdlUpgradeEvent } from '@/lib/types'
import { useWsGdlUpgrade } from '@/lib/ws'

export function GalleryDlSection() {
  const [version, setVersion] = useState<{ current: string | null; latest: string | null } | null>(
    null,
  )
  const [operating, setOperating] = useState(false)
  const [lastResult, setLastResult] = useState<GdlUpgradeEvent | null>(null)
  const timerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const fetchVersion = useCallback(async () => {
    try {
      const data = await api.galleryDl.getVersion()
      setVersion(data)
    } catch {
      toast.error(t('common.loadFailed'))
    }
  }, [])

  useEffect(() => {
    fetchVersion()
    return () => clearTimeout(timerRef.current)
  }, [fetchVersion])

  const { lastGdlUpgrade } = useWsGdlUpgrade()
  const seenRef = useRef<GdlUpgradeEvent | null | undefined>(undefined)
  useEffect(() => {
    if (seenRef.current === undefined) {
      seenRef.current = lastGdlUpgrade
      return
    }
    if (!lastGdlUpgrade || lastGdlUpgrade === seenRef.current) return
    seenRef.current = lastGdlUpgrade

    clearTimeout(timerRef.current)
    setOperating(false)

    const event = lastGdlUpgrade
    if (event.status === 'ok') {
      setLastResult(null)
      void fetchVersion()
      toast.success(
        event.rollback
          ? t('settings.galleryDlRollbackSuccess', { version: event.new_version ?? '' })
          : t('settings.galleryDlUpgradeSuccess', { version: event.new_version ?? '' }),
      )
    } else {
      setLastResult(event)
      const error = event.error ?? t('common.error')
      toast.error(
        event.status === 'rejected'
          ? t('settings.galleryDlUpgradeRejected', { error })
          : t('settings.galleryDlUpgradeFailed', { error }),
      )
    }
  }, [lastGdlUpgrade, fetchVersion])

  const upToDate =
    version?.current != null && version?.latest != null && version.current === version.latest

  const runJob = async (action: () => Promise<unknown>, queuedMessage: string) => {
    setOperating(true)
    setLastResult(null)
    try {
      await action()
      toast.info(queuedMessage)
      clearTimeout(timerRef.current)
      timerRef.current = setTimeout(() => setOperating(false), 90000)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('common.error'))
      setOperating(false)
    }
  }

  if (!version) {
    return (
      <div className="flex justify-center py-8">
        <LoadingSpinner />
      </div>
    )
  }

  return (
    <div>
      <p className="text-xs text-vault-text-muted mb-4">{t('settings.galleryDlDesc')}</p>

      <div className="bg-vault-input border border-vault-border rounded-lg divide-y divide-vault-border mb-4">
        <div className="flex justify-between px-4 py-2.5">
          <span className="text-sm text-vault-text-muted">{t('settings.galleryDlCurrent')}</span>
          <span className="text-sm text-vault-text font-mono">
            {version.current ?? t('settings.galleryDlNotInstalled')}
          </span>
        </div>
        <div className="flex justify-between px-4 py-2.5">
          <span className="text-sm text-vault-text-muted">{t('settings.galleryDlLatest')}</span>
          <span className="text-sm text-vault-text font-mono">
            {version.latest ?? t('settings.galleryDlUnknown')}
          </span>
        </div>
      </div>

      {upToDate && <p className="text-sm text-green-400 mb-4">{t('settings.galleryDlUpToDate')}</p>}

      {lastResult && lastResult.status !== 'ok' && (
        <div className="flex items-start justify-between gap-3 mb-4 px-3 py-2 rounded border border-red-700/50 bg-red-900/20">
          <span className="text-sm text-red-400">
            {lastResult.status === 'rejected'
              ? t('settings.galleryDlLastRejected', { error: lastResult.error ?? '' })
              : t('settings.galleryDlLastFailed', { error: lastResult.error ?? '' })}
          </span>
          <button
            type="button"
            onClick={() => setLastResult(null)}
            className="text-xs text-red-400/70 hover:text-red-400 shrink-0"
          >
            {t('settings.galleryDlDismiss')}
          </button>
        </div>
      )}

      <div className="flex flex-wrap gap-3 mb-3">
        <button
          type="button"
          onClick={() =>
            runJob(
              () => api.galleryDl.upgrade(version.latest ?? undefined),
              t('settings.galleryDlUpgradeQueued'),
            )
          }
          disabled={upToDate || operating || !version.latest}
          className="px-4 py-2 bg-blue-900/30 border border-blue-700/50 text-blue-400 hover:bg-blue-900/50 rounded text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {operating
            ? t('common.loading')
            : version.latest && !upToDate
              ? t('settings.galleryDlUpgradeTo', { version: version.latest })
              : t('settings.galleryDlUpgrade')}
        </button>
        <button
          type="button"
          onClick={() =>
            runJob(() => api.galleryDl.rollback(), t('settings.galleryDlRollbackQueued'))
          }
          disabled={operating}
          className="px-4 py-2 bg-amber-900/30 border border-amber-700/50 text-amber-400 hover:bg-amber-900/50 rounded text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {t('settings.galleryDlRollback')}
        </button>
      </div>

      <p className="text-[10px] text-amber-400/70 italic">
        {t('settings.galleryDlRunningWarning')}
      </p>
    </div>
  )
}
