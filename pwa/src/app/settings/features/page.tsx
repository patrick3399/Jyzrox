'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { useLocale } from '@/components/LocaleProvider'
import { useAdminGuard } from '@/hooks/useAdminGuard'
import { BackButton } from '@/components/BackButton'
import { ToggleRow } from '@/components/settings/SettingsShared'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'

export default function FeaturesSettingsPage() {
  useLocale()
  const authorized = useAdminGuard()

  const [features, setFeatures] = useState<Record<string, boolean>>({})
  const [featuresLoading, setFeaturesLoading] = useState(true)
  const [trashRetentionDays, setTrashRetentionDays] = useState(30)
  const trashRetentionDebounce = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  useEffect(() => {
    if (authorized) {
      api.settings
        .getFeatures()
        .then((data) => {
          setFeatures(data as unknown as Record<string, boolean>)
          setTrashRetentionDays(
            (data as unknown as Record<string, number>).trash_retention_days ?? 30,
          )
        })
        .catch(() => {})
        .finally(() => setFeaturesLoading(false))
    }
  }, [authorized])

  const handleToggle = useCallback(async (feature: string, enabled: boolean) => {
    try {
      await api.settings.setFeature(feature, enabled)
      setFeatures((prev) => ({ ...prev, [feature]: enabled }))
      toast.success(t('common.saved'))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToSave'))
    }
  }, [])

  const handleTrashToggle = useCallback(
    async (enabled: boolean) => {
      if (!enabled) {
        if (!confirm(t('settings.trashDisableConfirm'))) return
      }
      await handleToggle('trash_enabled', enabled)
    },
    [handleToggle],
  )

  const handleTrashRetentionChange = useCallback((v: number) => {
    setTrashRetentionDays(v)
    clearTimeout(trashRetentionDebounce.current)
    trashRetentionDebounce.current = setTimeout(async () => {
      try {
        await api.settings.setFeatureValue('trash_retention_days', Math.max(1, Math.min(365, v)))
        toast.success(t('common.saved'))
      } catch {
        toast.error(t('common.failedToSave'))
      }
    }, 500)
  }, [])

  if (!authorized) return null

  return (
    <div className="max-w-2xl">
      <BackButton fallback="/settings" />
      <h1 className="text-2xl font-bold mb-6 text-vault-text">{t('settingsCategory.features')}</h1>

      <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
        <div className="px-5 pb-5">
          {/* Service Toggles */}
          <div className="space-y-1 divide-y divide-vault-border">
            <ToggleRow
              label={t('settings.opdsServer')}
              description={t('settings.opdsDesc')}
              checked={features.opds_enabled ?? true}
              onChange={(v) => handleToggle('opds_enabled', v)}
              disabled={featuresLoading}
            />
            <ToggleRow
              label={t('settings.externalApi')}
              description={t('settings.externalApiDesc')}
              checked={features.external_api_enabled ?? true}
              onChange={(v) => handleToggle('external_api_enabled', v)}
              disabled={featuresLoading}
            />
            <ToggleRow
              label={t('settings.aiTagging')}
              description={t('settings.aiTaggingToggleDesc')}
              checked={features.ai_tagging_enabled ?? false}
              onChange={(v) => handleToggle('ai_tagging_enabled', v)}
              disabled={featuresLoading}
            />
            <ToggleRow
              label={t('settings.tagTranslation')}
              description={t('settings.tagTranslationDesc')}
              checked={features.tag_translation_enabled ?? true}
              onChange={(v) => handleToggle('tag_translation_enabled', v)}
              disabled={featuresLoading}
            />
          </div>

          {/* Trash */}
          <h3 className="text-xs text-vault-text-muted uppercase tracking-wide mt-5 mb-2">
            {t('settings.trashSection')}
          </h3>
          <div className="space-y-1 divide-y divide-vault-border">
            <ToggleRow
              label={t('settings.trashEnabled')}
              description={t('settings.trashEnabledDesc')}
              checked={features.trash_enabled ?? true}
              onChange={handleTrashToggle}
              disabled={featuresLoading}
            />
            {(features.trash_enabled ?? true) && (
              <div className="flex items-center justify-between py-2">
                <div>
                  <p className="text-sm text-vault-text">{t('settings.trashRetentionDays')}</p>
                  <p className="text-xs text-vault-text-muted">
                    {t('settings.trashRetentionDaysDesc')}
                  </p>
                </div>
                <input
                  type="number"
                  min={1}
                  max={365}
                  value={trashRetentionDays}
                  onChange={(e) => handleTrashRetentionChange(Number(e.target.value))}
                  className="w-20 text-right rounded-lg border border-vault-border bg-vault-input px-2 py-1.5 text-sm text-vault-text"
                />
              </div>
            )}
          </div>

          {/* Download Sources */}
          <h3 className="text-xs text-vault-text-muted uppercase tracking-wide mt-5 mb-2">
            {t('settings.downloadSources')}
          </h3>
          <div className="space-y-1 divide-y divide-vault-border">
            <ToggleRow
              label={t('settings.downloadEh')}
              description={t('settings.downloadEhDesc')}
              checked={features.download_eh_enabled ?? true}
              onChange={(v) => handleToggle('download_eh_enabled', v)}
              disabled={featuresLoading}
            />
            <ToggleRow
              label={t('settings.downloadPixiv')}
              description={t('settings.downloadPixivDesc')}
              checked={features.download_pixiv_enabled ?? true}
              onChange={(v) => handleToggle('download_pixiv_enabled', v)}
              disabled={featuresLoading}
            />
            <ToggleRow
              label={t('settings.downloadGalleryDl')}
              description={t('settings.downloadGalleryDlDesc')}
              checked={features.download_gallery_dl_enabled ?? true}
              onChange={(v) => handleToggle('download_gallery_dl_enabled', v)}
              disabled={featuresLoading}
            />
          </div>
        </div>
      </div>
    </div>
  )
}
