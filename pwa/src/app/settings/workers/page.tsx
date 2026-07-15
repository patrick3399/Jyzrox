'use client'

import { useState, useEffect, useRef } from 'react'
import { useLocale } from '@/components/LocaleProvider'
import { useAdminGuard } from '@/hooks/useAdminGuard'
import { BackButton } from '@/components/BackButton'
import { GalleryDlSection } from '@/components/settings/GalleryDlSection'
import { t } from '@/lib/i18n'
import { toast } from 'sonner'
import { api } from '@/lib/api'

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
