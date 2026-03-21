'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { useLocale } from '@/components/LocaleProvider'
import { useAdminGuard } from '@/hooks/useAdminGuard'
import { BackButton } from '@/components/BackButton'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { t } from '@/lib/i18n'
import { toast } from 'sonner'
import { api } from '@/lib/api'

function GalleryDlSection() {
  const [version, setVersion] = useState<{ current: string | null; latest: string | null } | null>(
    null,
  )
  const [operating, setOperating] = useState(false)
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

  const upToDate =
    version?.current != null && version?.latest != null && version.current === version.latest

  const runJob = async (action: () => Promise<unknown>, successMsg: string) => {
    setOperating(true)
    try {
      await action()
      toast.success(successMsg)
      timerRef.current = setTimeout(async () => {
        try {
          await fetchVersion()
        } finally {
          setOperating(false)
        }
      }, 5000)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.error'))
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

      <div className="flex flex-wrap gap-3 mb-3">
        <button
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

export default function WorkersSettingsPage() {
  useLocale()
  const authorized = useAdminGuard()

  const [recoveryStrategy, setRecoveryStrategy] = useState({
    running: 'auto_retry',
    paused: 'keep_paused',
  })
  const recoveryFetched = useRef(false)

  useEffect(() => {
    if (!recoveryFetched.current) {
      recoveryFetched.current = true
      api.settings
        .getRecoveryStrategy()
        .then(setRecoveryStrategy)
        .catch(() => {})
    }
  }, [])

  const handleRecoveryChange =
    (field: 'running' | 'paused') => async (e: React.ChangeEvent<HTMLSelectElement>) => {
      try {
        const updated = await api.settings.patchRecoveryStrategy({ [field]: e.target.value })
        setRecoveryStrategy(updated)
        toast.success(t('settings.recoveryUpdated'))
      } catch {
        toast.error(t('common.error'))
      }
    }

  if (!authorized) return null

  return (
    <div className="max-w-2xl">
      <BackButton fallback="/settings" />
      <h1 className="text-2xl font-bold mb-6 text-vault-text">{t('settingsCategory.workers')}</h1>

      {/* Worker Recovery */}
      <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden mb-6">
        <div className="px-5 py-4 border-b border-vault-border">
          <h2 className="font-medium text-vault-text text-sm">{t('settings.workerRecovery')}</h2>
        </div>
        <div className="px-5 pb-5 space-y-4">
          <p className="text-xs text-vault-text-muted mt-4">{t('settings.workerRecoveryDesc')}</p>
          <div className="flex items-center justify-between py-2">
            <div className="flex-1 min-w-0 pr-4">
              <p className="text-sm text-vault-text">{t('settings.recoveryRunning')}</p>
              <p className="text-xs text-vault-text-muted mt-0.5">
                {t('settings.recoveryRunningDesc')}
              </p>
            </div>
            <select
              value={recoveryStrategy.running}
              onChange={handleRecoveryChange('running')}
              className="px-3 py-1.5 text-sm bg-vault-input border border-vault-border rounded text-vault-text"
            >
              <option value="auto_retry">{t('settings.recoveryAutoRetry')}</option>
              <option value="mark_failed">{t('settings.recoveryMarkFailed')}</option>
            </select>
          </div>
          <div className="flex items-center justify-between py-2">
            <div className="flex-1 min-w-0 pr-4">
              <p className="text-sm text-vault-text">{t('settings.recoveryPaused')}</p>
              <p className="text-xs text-vault-text-muted mt-0.5">
                {t('settings.recoveryPausedDesc')}
              </p>
            </div>
            <select
              value={recoveryStrategy.paused}
              onChange={handleRecoveryChange('paused')}
              className="px-3 py-1.5 text-sm bg-vault-input border border-vault-border rounded text-vault-text"
            >
              <option value="keep_paused">{t('settings.recoveryKeepPaused')}</option>
              <option value="auto_retry">{t('settings.recoveryAutoRetry')}</option>
              <option value="mark_failed">{t('settings.recoveryMarkFailed')}</option>
            </select>
          </div>
        </div>
      </div>

      {/* Gallery-dl */}
      <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
        <div className="px-5 py-4 border-b border-vault-border">
          <h2 className="font-medium text-vault-text text-sm">{t('settings.galleryDl')}</h2>
        </div>
        <div className="px-5 pb-5 pt-4">
          <GalleryDlSection />
        </div>
      </div>
    </div>
  )
}
