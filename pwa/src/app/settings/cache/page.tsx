'use client'

import { useState, useCallback, useEffect } from 'react'
import { useLocale } from '@/components/LocaleProvider'
import { BackButton } from '@/components/BackButton'
import { t } from '@/lib/i18n'
import { toast } from 'sonner'
import {
  loadSWCacheConfig,
  saveSWCacheConfig,
  type SWCacheConfig,
  DEFAULT_SW_CACHE_CONFIG,
} from '@/lib/swCacheConfig'

export default function CacheSettingsPage() {
  useLocale()
  const [swCacheConfig, setSwCacheConfig] = useState<SWCacheConfig>(DEFAULT_SW_CACHE_CONFIG)

  useEffect(() => {
    setSwCacheConfig(loadSWCacheConfig())
  }, [])

  const handleSWCacheChange = useCallback((key: keyof SWCacheConfig, value: number) => {
    setSwCacheConfig((prev) => ({ ...prev, [key]: value }))
  }, [])

  const handleSWCacheBlur = useCallback(() => {
    setSwCacheConfig((prev) => {
      saveSWCacheConfig(prev)
      return prev
    })
    toast.success(t('common.saved'))
  }, [])

  const handleClearBrowserCache = useCallback(async () => {
    if (!window.confirm(t('settings.clearBrowserCacheConfirm'))) return
    const names = await caches.keys()
    await Promise.all(names.map((name) => caches.delete(name)))
    toast.success(t('settings.browserCacheCleared'))
    window.location.reload()
  }, [])

  return (
    <div className="max-w-2xl">
      <BackButton fallback="/settings" />
      <h1 className="text-2xl font-bold mb-6 text-vault-text">{t('settingsCategory.cache')}</h1>

      <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
        <div className="px-5 pb-5 pt-5">
          <p className="text-xs text-vault-text-muted mb-4">{t('settings.browserCacheDesc')}</p>

          <div className="space-y-4">
            {/* Media Cache TTL */}
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-vault-text">{t('settings.mediaCacheTTL')}</p>
                <p className="text-xs text-vault-text-muted mt-0.5">
                  {t('settings.mediaCacheTTLDesc')}
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <input
                  type="number"
                  min={0}
                  step={1}
                  value={swCacheConfig.mediaCacheTTLHours}
                  onChange={(e) =>
                    handleSWCacheChange('mediaCacheTTLHours', Number(e.target.value))
                  }
                  onBlur={handleSWCacheBlur}
                  className="w-20 bg-vault-input border border-vault-border rounded px-2 py-1.5 text-sm text-vault-text focus:outline-none focus:border-vault-accent text-right"
                />
                <span className="text-xs text-vault-text-muted w-8">{t('settings.hours')}</span>
              </div>
            </div>

            {/* Media Cache Size */}
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-vault-text">{t('settings.mediaCacheSizeLimit')}</p>
                <p className="text-xs text-vault-text-muted mt-0.5">
                  {t('settings.mediaCacheSizeLimitDesc')}
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <input
                  type="number"
                  min={0}
                  step={256}
                  value={swCacheConfig.mediaCacheSizeMB}
                  onChange={(e) => handleSWCacheChange('mediaCacheSizeMB', Number(e.target.value))}
                  onBlur={handleSWCacheBlur}
                  className="w-20 bg-vault-input border border-vault-border rounded px-2 py-1.5 text-sm text-vault-text focus:outline-none focus:border-vault-accent text-right"
                />
                <span className="text-xs text-vault-text-muted w-8">{t('settings.mb')}</span>
              </div>
            </div>

            {/* Page Cache TTL */}
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-vault-text">{t('settings.pageCacheTTL')}</p>
                <p className="text-xs text-vault-text-muted mt-0.5">
                  {t('settings.pageCacheTTLDesc')}
                </p>
              </div>
              <div className="flex items-center gap-2 shrink-0">
                <input
                  type="number"
                  min={0}
                  step={1}
                  value={swCacheConfig.pageCacheTTLHours}
                  onChange={(e) => handleSWCacheChange('pageCacheTTLHours', Number(e.target.value))}
                  onBlur={handleSWCacheBlur}
                  className="w-20 bg-vault-input border border-vault-border rounded px-2 py-1.5 text-sm text-vault-text focus:outline-none focus:border-vault-accent text-right"
                />
                <span className="text-xs text-vault-text-muted w-8">{t('settings.hours')}</span>
              </div>
            </div>

            {/* Clear browser cache */}
            <div className="pt-3 border-t border-vault-border/50">
              <button
                onClick={handleClearBrowserCache}
                className="px-4 py-2 bg-red-600/20 border border-red-500/30 text-red-400 hover:bg-red-600/30 rounded text-sm font-medium transition-colors"
              >
                {t('settings.clearBrowserCache')}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
