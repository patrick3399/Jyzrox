'use client'

import { useState, useEffect, useRef } from 'react'
import { useLocale } from '@/components/LocaleProvider'
import { useAdminGuard } from '@/hooks/useAdminGuard'
import { BackButton } from '@/components/BackButton'
import { t } from '@/lib/i18n'
import { toast } from 'sonner'
import { api } from '@/lib/api'

export default function LoggingSettingsPage() {
  useLocale()
  const authorized = useAdminGuard()

  const [logLevels, setLogLevels] = useState<Record<string, string>>({})
  const logLevelsFetched = useRef(false)

  useEffect(() => {
    if (!logLevelsFetched.current) {
      logLevelsFetched.current = true
      api.logs
        .getLevels()
        .then((d) => setLogLevels(d.levels))
        .catch(() => {})
    }
  }, [])

  if (!authorized) return null

  return (
    <div className="max-w-2xl">
      <BackButton fallback="/settings" />
      <h1 className="text-2xl font-bold mb-6 text-vault-text">{t('settingsCategory.logging')}</h1>

      <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
        <div className="px-5 pb-5 space-y-4">
          <p className="text-xs text-vault-text-muted mt-4">{t('settings.logLevelDesc')}</p>
          {[
            { key: 'api', label: t('settings.logLevelApi') },
            { key: 'worker', label: t('settings.logLevelWorker') },
          ].map(({ key, label }) => (
            <div key={key} className="flex items-center justify-between py-2">
              <span className="text-sm text-vault-text">{label}</span>
              <select
                value={logLevels[key] ?? 'INFO'}
                onChange={async (e) => {
                  const level = e.target.value
                  try {
                    await api.logs.setLevel(key, level)
                    setLogLevels((prev) => ({ ...prev, [key]: level }))
                    toast.success(t('settings.logLevelUpdated'))
                  } catch {
                    toast.error(t('common.error'))
                  }
                }}
                className="px-3 py-1.5 text-sm bg-vault-input border border-vault-border rounded text-vault-text"
              >
                {['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'].map((lvl) => (
                  <option key={lvl} value={lvl}>
                    {lvl}
                  </option>
                ))}
              </select>
            </div>
          ))}
          <p className="text-[10px] text-vault-text-muted italic">
            {t('settings.logLevelNginxHint')}
          </p>
        </div>
      </div>
    </div>
  )
}
