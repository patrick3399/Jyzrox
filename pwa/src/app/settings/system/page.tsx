'use client'

import { useState, useEffect, useCallback } from 'react'
import { useLocale } from '@/components/LocaleProvider'
import { useAdminGuard } from '@/hooks/useAdminGuard'
import { BackButton } from '@/components/BackButton'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { toast } from 'sonner'
import { api, type ReconcileStatus } from '@/lib/api'
import { t, formatBytes } from '@/lib/i18n'
import type { SystemHealth, SystemInfo, CacheStats, StorageInfo } from '@/lib/types'

const VERSION_LABELS: Record<string, string> = {
  jyzrox: 'Jyzrox',
  python: 'Python',
  fastapi: 'FastAPI',
  gallery_dl: 'gallery-dl',
  nextjs: 'Next.js',
  postgresql: 'PostgreSQL',
  redis: 'Redis',
  onnxruntime: 'ONNX Runtime',
}

function versionLabel(key: string): string {
  return VERSION_LABELS[key] ?? key
}

function serviceStatusClass(status: string): string {
  return status === 'ok' || status === 'healthy' ? 'text-green-400' : 'text-red-400'
}

export default function SystemSettingsPage() {
  useLocale()
  const authorized = useAdminGuard()

  const [health, setHealth] = useState<SystemHealth | null>(null)
  const [systemInfo, setSystemInfo] = useState<SystemInfo | null>(null)
  const [systemLoading, setSystemLoading] = useState(false)
  const [systemLoaded, setSystemLoaded] = useState(false)
  const [cacheStats, setCacheStats] = useState<CacheStats | null>(null)
  const [cacheLoading, setCacheLoading] = useState(false)
  const [cacheClearingAll, setCacheClearingAll] = useState(false)
  const [cacheClearingCategory, setCacheClearingCategory] = useState<string | null>(null)
  const [storageInfo, setStorageInfo] = useState<StorageInfo | null>(null)
  const [reconcileStatus, setReconcileStatus] = useState<ReconcileStatus | null>(null)
  const [reconcileRunning, setReconcileRunning] = useState(false)

  const loadSystem = useCallback(async () => {
    setSystemLoading(true)
    try {
      const [h, i, cs, st, rc] = await Promise.all([
        api.system.health(),
        api.system.info(),
        api.system.getCache(),
        api.system.getStorage().catch(() => null),
        api.system.getReconcileStatus().catch(() => null),
      ])
      setHealth(h)
      setSystemInfo(i)
      setCacheStats(cs)
      setStorageInfo(st)
      setReconcileStatus(rc)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.systemLoadFailed'))
    } finally {
      setSystemLoading(false)
      setSystemLoaded(true)
    }
  }, [])

  useEffect(() => {
    if (authorized) {
      loadSystem()
    }
  }, [authorized, loadSystem])

  const handleRefreshCache = useCallback(async () => {
    setCacheLoading(true)
    try {
      const cs = await api.system.getCache()
      setCacheStats(cs)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToLoad'))
    } finally {
      setCacheLoading(false)
    }
  }, [])

  const handleClearAllCache = useCallback(async () => {
    if (!window.confirm(t('settings.clearCacheConfirm'))) return
    setCacheClearingAll(true)
    try {
      const result = await api.system.clearCache()
      toast.success(t('settings.clearCacheSuccess', { count: result.deleted_keys }))
      await handleRefreshCache()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.clearCacheFailed'))
    } finally {
      setCacheClearingAll(false)
    }
  }, [handleRefreshCache])

  const handleClearCacheCategory = useCallback(
    async (category: string) => {
      if (!window.confirm(t('settings.confirmClearCache', { category }))) return
      setCacheClearingCategory(category)
      try {
        const result = await api.system.clearCacheCategory(category)
        toast.success(t('settings.clearCacheSuccess', { count: result.deleted_keys }))
        await handleRefreshCache()
      } catch (err) {
        toast.error(err instanceof Error ? err.message : t('settings.clearCacheFailed'))
      } finally {
        setCacheClearingCategory(null)
      }
    },
    [handleRefreshCache],
  )

  const handleReconcile = useCallback(async () => {
    if (!confirm(t('settings.reconcileConfirm'))) return
    setReconcileRunning(true)
    try {
      await api.system.startReconcile()
      toast.success(t('settings.reconcileStarted'))
    } catch {
      toast.error(t('settings.reconcileFailed'))
    } finally {
      setReconcileRunning(false)
    }
  }, [])

  if (!authorized) return null

  return (
    <div className="max-w-2xl">
      <BackButton fallback="/settings" />
      <h1 className="text-2xl font-bold mb-6 text-vault-text">{t('settingsCategory.system')}</h1>

      <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
        <div className="px-5 pb-5">
          {systemLoading && (
            <div className="flex justify-center py-8">
              <LoadingSpinner />
            </div>
          )}

          {!systemLoading && !systemLoaded && (
            <div className="flex justify-center py-8">
              <LoadingSpinner />
            </div>
          )}

          {!systemLoading && health && systemInfo && (
            <div className="mt-4 space-y-4">
              {/* Health */}
              <div>
                <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">
                  {t('settings.serviceHealth')}
                </p>
                <div className="bg-vault-input border border-vault-border rounded-lg divide-y divide-vault-border">
                  {[
                    { label: t('settings.overall'), value: health.status },
                    { label: 'PostgreSQL', value: health.services.postgres },
                    { label: 'Redis', value: health.services.redis },
                  ].map(({ label, value }) => (
                    <div key={label} className="flex justify-between items-center px-3 py-2">
                      <span className="text-sm text-vault-text-muted">{label}</span>
                      <span className={`text-sm font-medium ${serviceStatusClass(value)}`}>
                        {value}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Versions */}
              {systemInfo.versions && (
                <div>
                  <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">
                    {t('settings.versions')}
                  </p>
                  <div className="bg-vault-input border border-vault-border rounded-lg divide-y divide-vault-border">
                    {Object.entries({
                      jyzrox: systemInfo.versions.jyzrox,
                      python: systemInfo.versions.python,
                      fastapi: systemInfo.versions.fastapi,
                      nextjs: process.env.NEXT_PUBLIC_NEXTJS_VERSION ?? null,
                      gallery_dl: systemInfo.versions.gallery_dl,
                      postgresql: systemInfo.versions.postgresql,
                      redis: systemInfo.versions.redis,
                      onnxruntime: systemInfo.versions.onnxruntime,
                    })
                      .filter(([, v]) => v !== null)
                      .map(([key, value]) => (
                        <div key={key} className="flex justify-between items-center px-3 py-2">
                          <span className="text-sm text-vault-text-muted">{versionLabel(key)}</span>
                          <span className="text-sm font-mono text-vault-text-secondary">
                            {value}
                          </span>
                        </div>
                      ))}
                  </div>
                </div>
              )}

              {/* Configuration */}
              <div>
                <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">
                  {t('settings.configuration')}
                </p>
                <div className="bg-vault-input border border-vault-border rounded-lg divide-y divide-vault-border">
                  {[
                    {
                      label: t('settings.ehMaxConcurrency'),
                      value: String(systemInfo.eh_max_concurrency),
                    },
                    {
                      label: t('settings.aiTagging'),
                      value: systemInfo.tag_model_enabled
                        ? t('settings.enabled')
                        : t('settings.disabled'),
                      valueClass: systemInfo.tag_model_enabled
                        ? 'text-green-400'
                        : 'text-vault-text-muted',
                    },
                  ].map(({ label, value, valueClass }) => (
                    <div key={label} className="flex justify-between items-center px-3 py-2">
                      <span className="text-sm text-vault-text-muted">{label}</span>
                      <span
                        className={`text-sm font-medium ${valueClass ?? 'text-vault-text-secondary'}`}
                      >
                        {value}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              {/* Storage */}
              {storageInfo && storageInfo.mounts.length > 0 && (
                <div>
                  <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">
                    {t('settings.storage')}
                  </p>
                  <div className="bg-vault-input border border-vault-border rounded-lg divide-y divide-vault-border">
                    {storageInfo.mounts.map((mount) => {
                      const barColor =
                        mount.percent > 90
                          ? 'bg-red-500'
                          : mount.percent > 70
                            ? 'bg-yellow-500'
                            : 'bg-green-500'
                      return (
                        <div key={mount.path} className="px-3 py-2.5">
                          <div className="flex justify-between items-center mb-1.5">
                            <span className="text-sm text-vault-text">{mount.label}</span>
                            <span className="text-xs text-vault-text-muted font-mono">
                              {formatBytes(mount.used)} / {formatBytes(mount.total)}
                            </span>
                          </div>
                          <div className="w-full h-2 bg-vault-bg rounded-full overflow-hidden">
                            <div
                              className={`h-full rounded-full transition-all ${barColor}`}
                              style={{ width: `${Math.min(mount.percent, 100)}%` }}
                            />
                          </div>
                          <div className="flex justify-between mt-1">
                            <span className="text-xs text-vault-text-muted">
                              {mount.percent}% {t('settings.storageUsed').toLowerCase()}
                            </span>
                            <span className="text-xs text-vault-text-muted">
                              {formatBytes(mount.free)} {t('settings.storageFree').toLowerCase()}
                            </span>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* Cache Management */}
              <div>
                <div className="flex items-center justify-between mb-2">
                  <p className="text-xs text-vault-text-muted uppercase tracking-wide">
                    {t('settings.cache')}
                  </p>
                  <button
                    onClick={handleRefreshCache}
                    disabled={cacheLoading}
                    className="text-xs text-vault-text-muted hover:text-vault-text-secondary transition-colors"
                  >
                    {cacheLoading ? t('settings.loading') : t('settings.cacheRefresh')}
                  </button>
                </div>
                {cacheStats && (
                  <div className="space-y-2">
                    <div className="bg-vault-input border border-vault-border rounded-lg divide-y divide-vault-border">
                      <div className="flex justify-between items-center px-3 py-2">
                        <span className="text-sm text-vault-text-muted">
                          {t('settings.cacheMemory')}
                        </span>
                        <span className="text-sm font-medium text-vault-text-secondary">
                          {cacheStats.total_memory}
                        </span>
                      </div>
                      <div className="flex justify-between items-center px-3 py-2">
                        <span className="text-sm text-vault-text-muted">
                          {t('settings.cacheKeys')}
                        </span>
                        <span className="text-sm font-medium text-vault-text-secondary">
                          {cacheStats.total_keys}
                        </span>
                      </div>
                    </div>

                    {/* Breakdown by category */}
                    {Object.keys(cacheStats.breakdown).length > 0 && (
                      <div className="bg-vault-input border border-vault-border rounded-lg divide-y divide-vault-border">
                        {Object.entries(cacheStats.breakdown).map(([cat, count]) => {
                          const catLabels: Record<string, string> = {
                            eh_search: t('settings.cacheEhSearch'),
                            eh_gallery: t('settings.cacheEhGallery'),
                            eh_image: t('settings.cacheEhImage'),
                            thumbs: t('settings.cacheThumbs'),
                          }
                          return (
                            <div
                              key={cat}
                              className="flex items-center justify-between px-3 py-2 gap-2"
                            >
                              <span className="text-sm text-vault-text-muted flex-1">
                                {catLabels[cat] ?? cat}
                              </span>
                              <span className="text-sm text-vault-text-secondary tabular-nums">
                                {count}
                              </span>
                              <button
                                onClick={() => handleClearCacheCategory(cat)}
                                disabled={cacheClearingCategory === cat || cacheClearingAll}
                                className="text-xs text-red-400/70 hover:text-red-400 transition-colors px-2 py-0.5 disabled:opacity-40"
                              >
                                {cacheClearingCategory === cat
                                  ? '...'
                                  : t('settings.clearCategory')}
                              </button>
                            </div>
                          )
                        })}
                      </div>
                    )}

                    <button
                      onClick={handleClearAllCache}
                      disabled={cacheClearingAll || cacheClearingCategory !== null}
                      className="mt-1 px-3 py-1.5 bg-red-600/20 border border-red-500/30 text-red-400 rounded text-sm hover:bg-red-600/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      {cacheClearingAll ? t('settings.clearing') : t('settings.clearCache')}
                    </button>
                  </div>
                )}
              </div>

              {/* Data Reconciliation */}
              <div className="pt-4 border-t border-vault-border">
                <h3 className="text-sm font-medium text-vault-text mb-2">
                  {t('settings.reconciliation')}
                </h3>
                {reconcileStatus &&
                  reconcileStatus.status !== 'never_run' &&
                  'completed_at' in reconcileStatus && (
                    <div className="text-xs text-vault-text-muted space-y-1 mb-3">
                      <p>
                        {t('settings.reconcileLastRun', {
                          time: new Date(reconcileStatus.completed_at).toLocaleString(),
                        })}
                      </p>
                      <div className="flex gap-4">
                        <span>
                          {t('settings.reconcileRemovedImages')}: {reconcileStatus.removed_images}
                        </span>
                        <span>
                          {t('settings.reconcileRemovedGalleries')}:{' '}
                          {reconcileStatus.removed_galleries}
                        </span>
                        <span>
                          {t('settings.reconcileOrphanBlobs')}:{' '}
                          {reconcileStatus.orphan_blobs_cleaned}
                        </span>
                      </div>
                    </div>
                  )}
                {reconcileStatus?.status === 'never_run' && (
                  <p className="text-xs text-vault-text-muted mb-3">
                    {t('settings.reconcileNeverRun')}
                  </p>
                )}
                <button
                  onClick={handleReconcile}
                  disabled={reconcileRunning}
                  className="px-3 py-1.5 bg-vault-accent/20 border border-vault-accent/30 text-vault-accent rounded text-sm hover:bg-vault-accent/30 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  {reconcileRunning ? t('settings.reconcileRunning') : t('settings.reconcileRun')}
                </button>
              </div>

              <button
                onClick={loadSystem}
                className="text-xs text-vault-text-muted hover:text-vault-text-secondary transition-colors"
              >
                {t('settings.refresh')}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
