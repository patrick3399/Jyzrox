'use client'

import { useState, useEffect } from 'react'
import { useLocale } from '@/components/LocaleProvider'
import { useAdminGuard } from '@/hooks/useAdminGuard'
import { BackButton } from '@/components/BackButton'
import { ToggleRow } from '@/components/settings/SettingsShared'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'

export default function SecuritySettingsPage() {
  useLocale()
  const authorized = useAdminGuard()

  const [features, setFeatures] = useState<Record<string, boolean>>({})
  const [featuresLoading, setFeaturesLoading] = useState(true)

  useEffect(() => {
    if (authorized) {
      api.settings
        .getFeatures()
        .then((data) => setFeatures(data as unknown as Record<string, boolean>))
        .catch(() => {})
        .finally(() => setFeaturesLoading(false))
    }
  }, [authorized])

  const handleToggle = async (key: string, value: boolean) => {
    try {
      await api.settings.setFeature(key, value)
      setFeatures((prev) => ({ ...prev, [key]: value }))
      toast.success(t('common.saved'))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToSave'))
    }
  }

  if (!authorized) return null

  return (
    <div className="max-w-2xl">
      <BackButton fallback="/settings" />
      <h1 className="text-2xl font-bold mb-6 text-vault-text">{t('settingsCategory.security')}</h1>

      <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
        <div className="px-5 pb-5 space-y-1 divide-y divide-vault-border">
          <ToggleRow
            label={t('settings.csrfProtection')}
            description={t('settings.csrfDesc')}
            checked={features.csrf_enabled ?? true}
            onChange={(v) => handleToggle('csrf_enabled', v)}
            disabled={featuresLoading}
          />
          <ToggleRow
            label={t('settings.rateLimiting')}
            description={t('settings.rateLimitDesc')}
            checked={features.rate_limit_enabled ?? true}
            onChange={(v) => handleToggle('rate_limit_enabled', v)}
            disabled={featuresLoading}
          />
        </div>
      </div>
    </div>
  )
}
