'use client'

import { useState, useEffect } from 'react'
import { Puzzle, Check, X, Download, Sparkles, Cpu } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import type { PluginInfo } from '@/lib/types'
import type { PluginServiceHealth } from '@/lib/types'

export default function PluginsPage() {
  useLocale()
  const [plugins, setPlugins] = useState<PluginInfo[]>([])
  const [loading, setLoading] = useState(true)
  const [health, setHealth] = useState<Record<string, PluginServiceHealth>>({})

  useEffect(() => {
    api.plugins
      .list()
      .then((res) => setPlugins(res.plugins))
      .catch(() => toast.error(t('plugins.loadFailed')))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    api.plugins
      .health()
      .then((result) => setHealth(result.services))
      .catch(() => {})
  }, [])

  return (
    <div className="max-w-3xl">
      <div className="flex items-center gap-3 mb-6">
        <Puzzle size={22} className="text-vault-accent" />
        <h1 className="text-2xl font-bold">{t('plugins.title')}</h1>
      </div>

      {loading ? (
        <p className="text-vault-text-muted">{t('common.loading')}</p>
      ) : plugins.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <Puzzle size={40} className="text-vault-text-muted mb-4" />
          <p className="text-vault-text font-medium">{t('plugins.empty')}</p>
          <p className="text-vault-text-muted text-sm mt-1">{t('plugins.emptyHint')}</p>
        </div>
      ) : (
        <div className="space-y-3">
          {plugins.map((plugin) => (
            <div
              key={plugin.source_id}
              className="bg-vault-card border border-vault-border rounded-xl p-5"
            >
              <div className="flex items-start justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-vault-text">{plugin.name}</h2>
                  <p className="text-xs text-vault-text-muted mt-0.5">
                    {plugin.source_id} &middot; {t('plugins.version', { version: plugin.version })}
                  </p>
                </div>
                <span
                  className={`text-xs px-2 py-1 rounded-full ${plugin.enabled ? 'bg-green-500/20 text-green-400' : 'bg-vault-input text-vault-text-muted'}`}
                >
                  {plugin.enabled ? t('plugins.enabled') : t('plugins.disabled')}
                </span>
              </div>

              {/* URL patterns */}
              {plugin.url_patterns.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {plugin.url_patterns.map((p) => (
                    <span
                      key={p}
                      className="text-xs bg-vault-input border border-vault-border rounded px-2 py-0.5 text-vault-text-secondary font-mono"
                    >
                      {p}
                    </span>
                  ))}
                </div>
              )}

              {/* Capabilities */}
              <div className="mt-3 flex flex-wrap gap-3 text-xs text-vault-text-muted">
                <span className="flex items-center gap-1">
                  <Download size={12} />
                  {plugin.has_browse ? t('plugins.hasBrowse') : t('plugins.noBrowse')}
                </span>
                {plugin.source_id === 'gallery_dl' && (
                  <span className="flex items-center gap-1 text-vault-accent">
                    {t('plugins.fallback')}
                  </span>
                )}
                {plugin.has_process && (
                  <span className="flex items-center gap-1 text-vault-accent">
                    <Sparkles size={12} />
                    {t('plugins.hasProcess')}
                  </span>
                )}
              </div>

              {plugin.has_process && health[plugin.source_id] && (
                <div className="mt-3 rounded-lg border border-vault-border bg-vault-input p-3 text-xs">
                  <div className="flex items-center gap-2">
                    <span
                      className={`h-2 w-2 rounded-full ${health[plugin.source_id].online ? 'bg-green-400' : 'bg-red-400'}`}
                    />
                    <span className="font-medium text-vault-text">
                      {health[plugin.source_id].online
                        ? t('plugins.serviceOnline')
                        : t('plugins.serviceOffline')}
                    </span>
                  </div>
                  {health[plugin.source_id].gpu_name && (
                    <p className="mt-2 flex items-center gap-1 text-vault-text-muted">
                      <Cpu size={12} />
                      {health[plugin.source_id].gpu_name}
                      {health[plugin.source_id].vram_total_mb
                        ? ` · ${health[plugin.source_id].vram_total_mb} MB VRAM`
                        : ''}
                    </p>
                  )}
                  {!health[plugin.source_id].online && health[plugin.source_id].error && (
                    <p className="mt-2 break-words text-red-400">{health[plugin.source_id].error}</p>
                  )}
                </div>
              )}

              {/* Credential status */}
              {plugin.credential_schema.length > 0 && (
                <div className="mt-3 flex items-center gap-2 text-xs">
                  {plugin.credential_configured ? (
                    <span className="flex items-center gap-1 text-green-400">
                      <Check size={12} />
                      {t('plugins.credentialsConfigured')}
                    </span>
                  ) : (
                    <span className="flex items-center gap-1 text-vault-text-muted">
                      <X size={12} />
                      {t('plugins.credentialsNotConfigured')}
                    </span>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
