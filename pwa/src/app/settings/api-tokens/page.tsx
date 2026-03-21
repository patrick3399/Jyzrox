'use client'

import { useState, useCallback, useEffect } from 'react'
import { useLocale } from '@/components/LocaleProvider'
import { BackButton } from '@/components/BackButton'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { inputClass, btnPrimary } from '@/components/settings/SettingsShared'
import { t } from '@/lib/i18n'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { Copy } from 'lucide-react'
import type { ApiTokenInfo } from '@/lib/types'

export default function ApiTokensSettingsPage() {
  useLocale()

  const [apiTokens, setApiTokens] = useState<ApiTokenInfo[]>([])
  const [apiTokensLoaded, setApiTokensLoaded] = useState(false)
  const [apiTokensLoading, setApiTokensLoading] = useState(false)
  const [newTokenName, setNewTokenName] = useState('')
  const [newTokenExpiry, setNewTokenExpiry] = useState<string>('')
  const [tokenCreating, setTokenCreating] = useState(false)
  const [deletingTokenId, setDeletingTokenId] = useState<string | null>(null)

  const handleLoadApiTokens = useCallback(async () => {
    setApiTokensLoading(true)
    try {
      const result = await api.tokens.list()
      setApiTokens(result.tokens)
      setApiTokensLoaded(true)
    } catch {
      toast.error(t('common.failedToLoad'))
      setApiTokensLoaded(true)
    } finally {
      setApiTokensLoading(false)
    }
  }, [])

  const handleCreateToken = useCallback(async () => {
    if (!newTokenName.trim()) return
    setTokenCreating(true)
    try {
      const expDays = newTokenExpiry ? Number(newTokenExpiry) : undefined
      const created = await api.tokens.create(newTokenName.trim(), expDays)
      setApiTokens((prev) => [created, ...prev])
      toast.success(t('settings.tokenCreated'))
      setNewTokenName('')
      setNewTokenExpiry('')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.failedCreateToken'))
    } finally {
      setTokenCreating(false)
    }
  }, [newTokenName, newTokenExpiry])

  const handleDeleteToken = useCallback(async (tokenId: string) => {
    if (!window.confirm(t('settings.confirmDeleteToken'))) return
    setDeletingTokenId(tokenId)
    try {
      await api.tokens.delete(tokenId)
      setApiTokens((prev) => prev.filter((tk) => tk.id !== tokenId))
      toast.success(t('settings.tokenRevoked'))
    } catch {
      toast.error(t('settings.failedRevokeToken'))
    } finally {
      setDeletingTokenId(null)
    }
  }, [])

  useEffect(() => {
    if (!apiTokensLoaded && !apiTokensLoading) {
      handleLoadApiTokens()
    }
  }, [apiTokensLoaded, apiTokensLoading, handleLoadApiTokens])

  return (
    <div className="max-w-2xl">
      <BackButton fallback="/settings" />
      <h1 className="text-2xl font-bold mb-6 text-vault-text">{t('settingsCategory.apiTokens')}</h1>

      <div className="space-y-6">
        {/* Create new token */}
        <div className="bg-vault-card border border-vault-border rounded-xl px-5 py-5">
          <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-3">
            {t('settings.createToken')}
          </p>
          <div className="space-y-3">
            <div>
              <label className="block text-xs text-vault-text-muted mb-1">
                {t('settings.tokenName')}
              </label>
              <input
                type="text"
                value={newTokenName}
                onChange={(e) => setNewTokenName(e.target.value)}
                placeholder={t('settings.tokenNamePlaceholder')}
                onKeyDown={(e) => e.key === 'Enter' && handleCreateToken()}
                className={inputClass}
              />
            </div>
            <div>
              <label className="block text-xs text-vault-text-muted mb-1">
                {t('settings.expiresIn')}
              </label>
              <select
                value={newTokenExpiry}
                onChange={(e) => setNewTokenExpiry(e.target.value)}
                className={inputClass}
              >
                <option value="">{t('settings.never')}</option>
                <option value="7">{t('settings.days7')}</option>
                <option value="30">{t('settings.days30')}</option>
                <option value="90">{t('settings.days90')}</option>
                <option value="365">{t('settings.year1')}</option>
              </select>
            </div>
            <button
              onClick={handleCreateToken}
              disabled={tokenCreating || !newTokenName.trim()}
              className={btnPrimary}
            >
              {tokenCreating ? t('settings.creating') : t('settings.createToken')}
            </button>
          </div>
        </div>

        {/* Token list */}
        <div className="bg-vault-card border border-vault-border rounded-xl px-5 py-5">
          <div className="flex items-center justify-between mb-3">
            <p className="text-xs text-vault-text-muted uppercase tracking-wide">
              {t('settings.activeTokens')}
            </p>
            <button
              onClick={handleLoadApiTokens}
              disabled={apiTokensLoading}
              className="text-xs text-vault-text-muted hover:text-vault-text-secondary transition-colors"
            >
              {apiTokensLoading ? t('settings.loading') : t('settings.refresh')}
            </button>
          </div>

          {apiTokensLoading && apiTokens.length === 0 ? (
            <div className="flex justify-center py-4">
              <LoadingSpinner />
            </div>
          ) : apiTokens.length === 0 ? (
            <p className="text-xs text-vault-text-muted py-3">{t('settings.noTokens')}</p>
          ) : (
            <div className="space-y-2">
              {apiTokens.map((tk) => {
                const isExpired = tk.expires_at && new Date(tk.expires_at) < new Date()
                return (
                  <div
                    key={tk.id}
                    className={`bg-vault-input border rounded-lg px-3 py-2.5 ${
                      isExpired ? 'border-red-700/50 opacity-60' : 'border-vault-border'
                    }`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <span className="text-sm text-vault-text font-medium">
                            {tk.name || t('settings.unnamed')}
                          </span>
                          {isExpired && (
                            <span className="text-[10px] bg-red-900/40 text-red-400 px-1.5 py-0.5 rounded">
                              {t('settings.tokenExpired')}
                            </span>
                          )}
                        </div>
                        {/* Token value — raw token after creation, prefix after list reload */}
                        {(tk.token || tk.token_prefix) && (
                          <div className="flex items-center gap-1.5 mt-1.5">
                            <code className="flex-1 text-xs text-vault-text-secondary bg-black/20 rounded px-2 py-1 font-mono break-all select-all">
                              {tk.token ?? `${tk.token_prefix}...`}
                            </code>
                            {tk.token && (
                              <button
                                onClick={() => {
                                  navigator.clipboard.writeText(tk.token!)
                                  toast.success(t('settings.copied'))
                                }}
                                className="px-1.5 py-1 text-vault-text-muted hover:text-vault-text transition-colors shrink-0"
                                title="Copy"
                              >
                                <Copy size={12} />
                              </button>
                            )}
                          </div>
                        )}
                        <div className="flex flex-wrap items-center gap-3 mt-1 text-xs text-vault-text-muted">
                          {tk.created_at && (
                            <span>Created {new Date(tk.created_at).toLocaleDateString()}</span>
                          )}
                          {tk.last_used_at ? (
                            <span>Last used {new Date(tk.last_used_at).toLocaleDateString()}</span>
                          ) : (
                            <span>Never used</span>
                          )}
                          {tk.expires_at && (
                            <span>
                              {isExpired ? 'Expired' : 'Expires'}{' '}
                              {new Date(tk.expires_at).toLocaleDateString()}
                            </span>
                          )}
                          {!tk.expires_at && <span>No expiration</span>}
                        </div>
                      </div>
                      <button
                        onClick={() => handleDeleteToken(tk.id)}
                        disabled={deletingTokenId === tk.id}
                        className="text-xs text-red-400/70 hover:text-red-400 transition-colors shrink-0 px-2 py-1"
                      >
                        {deletingTokenId === tk.id ? '...' : 'Revoke'}
                      </button>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        {/* RSS Feed */}
        <div className="bg-vault-card border border-vault-border rounded-xl px-5 py-5">
          <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">
            {t('rss.recentFeed')}
          </p>
          <div className="flex items-center gap-2">
            <code className="text-xs text-vault-text-secondary flex-1 truncate">
              {typeof window !== 'undefined' ? window.location.origin : ''}
              /api/rss/recent?token=YOUR_TOKEN
            </code>
            <button
              onClick={() => {
                navigator.clipboard.writeText(
                  `${window.location.origin}/api/rss/recent?token=YOUR_TOKEN`,
                )
                toast.success(t('rss.copied'))
              }}
              className="p-1 rounded text-vault-text-muted hover:text-vault-accent transition-colors shrink-0"
              title={t('rss.copyUrl')}
            >
              <Copy size={14} />
            </button>
          </div>
        </div>

        {/* API usage info */}
        <div className="bg-vault-card border border-vault-border rounded-xl px-5 py-5">
          <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">Usage</p>
          <div className="bg-vault-input border border-vault-border rounded-lg p-3">
            <p className="text-xs text-vault-text-secondary mb-2">
              Use the{' '}
              <code className="bg-black/30 px-1 py-0.5 rounded text-vault-text-muted">
                X-API-Token
              </code>{' '}
              header to authenticate external API requests.
            </p>
            <p className="text-xs text-vault-text-muted mb-1">Available endpoints:</p>
            <div className="space-y-0.5 font-mono text-[11px] text-vault-text-muted">
              <p>
                <span className="text-green-400">GET</span> /api/external/v1/status
              </p>
              <p>
                <span className="text-green-400">GET</span> /api/external/v1/galleries
              </p>
              <p>
                <span className="text-green-400">GET</span> /api/external/v1/galleries/:id
              </p>
              <p>
                <span className="text-green-400">GET</span> /api/external/v1/galleries/:id/images
              </p>
              <p>
                <span className="text-green-400">GET</span> /api/external/v1/tags
              </p>
              <p>
                <span className="text-blue-400">POST</span> /api/external/v1/download?url=...
              </p>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
