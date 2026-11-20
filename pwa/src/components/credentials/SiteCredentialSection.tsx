'use client'

import { useState, useRef } from 'react'
import { ChevronUp, ChevronDown, Trash2, Search } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { CredentialAccounts, sanitizeAccountName } from '@/components/CredentialAccounts'
import type { Credentials } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { inputClass } from '@/components/credentials/shared'

// Sources that have their own credential section; the generic site list must not repeat them.
const NON_GENERIC_SOURCES = new Set(['ehentai', 'pixiv', 'saucenao'])

// ── SiteCredentialSection ──────────────────────────────────────────────────

export function SiteCredentialSection({
  credentials,
  credLoading,
  onCredentialsChange,
  onRefresh,
  accountsRefreshKey,
}: {
  credentials: Credentials | null
  credLoading: boolean
  onCredentialsChange: (next: Credentials) => void
  onRefresh: () => void
  accountsRefreshKey: number
}) {
  const [isOpen, setIsOpen] = useState(false)

  // URL detection state
  const [urlInput, setUrlInput] = useState('')
  const [detecting, setDetecting] = useState(false)
  const [detectedName, setDetectedName] = useState<string | null>(null)

  // Form state
  const [sourceName, setSourceName] = useState('')
  const [activeTab, setActiveTab] = useState<'cookies' | 'userpass'>('cookies')
  const [cookiesText, setCookiesText] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [saving, setSaving] = useState(false)
  const [clearingSource, setClearingSource] = useState<string | null>(null)
  const [accountName, setAccountName] = useState('')
  const accountInputRef = useRef<HTMLInputElement>(null)
  const [expandedSource, setExpandedSource] = useState<string | null>(null)

  const genericSites = credentials
    ? Object.entries(credentials).filter(
        ([source]) => !NON_GENERIC_SOURCES.has(source) && credentials[source].configured,
      )
    : []

  // "Add account" on a site's panel: aim the form below at that site, so the
  // user does not have to retype which site the new account belongs to.
  const handleAddAccountTo = (source: string) => {
    setSourceName(source)
    setUrlInput('')
    setDetectedName(null)
    accountInputRef.current?.focus()
    accountInputRef.current?.scrollIntoView?.({ block: 'center', behavior: 'smooth' })
  }

  const targetSource = sourceName.trim().toLowerCase()
  const existingTarget = credentials?.[targetSource]?.configured ? credentials[targetSource] : null

  const handleDetect = async () => {
    if (!urlInput.trim()) return
    setDetecting(true)
    setDetectedName(null)
    try {
      const res = await api.settings.detectSite(urlInput.trim())
      if (res.detected && res.source) {
        setSourceName(res.source)
        setDetectedName(res.site_name || res.source)
      } else {
        toast.error(t('credentials.detectFailed'))
      }
    } catch {
      toast.error(t('credentials.detectFailed'))
    } finally {
      setDetecting(false)
    }
  }

  const handleSave = async () => {
    const source = sourceName.trim().toLowerCase()
    if (!source) return
    if (activeTab === 'cookies' && !cookiesText.trim()) return
    if (activeTab === 'userpass' && !username.trim()) return

    setSaving(true)
    try {
      if (activeTab === 'cookies') {
        await api.settings.setSiteCredential(source, {
          cookies: cookiesText.trim(),
          account: accountName || undefined,
        })
      } else {
        await api.settings.setSiteCredential(source, {
          username: username.trim(),
          password: password.trim() || undefined,
          account: accountName || undefined,
        })
      }
      toast.success(t('credentials.savedSite', { source }))
      onRefresh()
      setAccountName('')
      // Reset form
      setSourceName('')
      setCookiesText('')
      setUsername('')
      setPassword('')
      setUrlInput('')
      setDetectedName(null)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('credentials.saveFailed'))
    } finally {
      setSaving(false)
    }
  }

  const handleClear = async (source: string) => {
    if (!confirm(t('credentials.clearConfirm', { source }))) return
    setClearingSource(source)
    try {
      await api.settings.deleteCredential(source)
      toast.success(t('credentials.cleared', { source }))
      if (credentials) {
        const next = { ...credentials }
        delete next[source]
        onCredentialsChange(next)
      }
      onRefresh()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('credentials.clearFailed'))
    } finally {
      setClearingSource(null)
    }
  }

  const canSave =
    sourceName.trim() && (activeTab === 'cookies' ? cookiesText.trim() : username.trim())

  return (
    <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
      <div className="flex items-center justify-between">
        <button
          onClick={() => setIsOpen((v) => !v)}
          className="flex-1 flex items-center justify-between px-5 py-4 text-left hover:bg-vault-card-hover transition-colors"
        >
          <span className="font-medium text-vault-text text-sm">
            {t('credentials.genericCookies')}
          </span>
          {isOpen ? (
            <ChevronUp size={16} className="text-vault-text-muted" />
          ) : (
            <ChevronDown size={16} className="text-vault-text-muted" />
          )}
        </button>
        {genericSites.length > 0 && (
          <div className="pr-5 shrink-0">
            <span className="text-xs text-vault-text-muted">{genericSites.length}</span>
          </div>
        )}
      </div>

      {isOpen && (
        <div className="px-5 pb-5 border-t border-vault-border">
          <p className="text-xs text-vault-text-muted mt-4 mb-4">
            {t('credentials.genericCookiesDesc')}
          </p>

          {/* Configured sites list */}
          {genericSites.length > 0 && (
            <div className="mb-5">
              <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">
                {t('credentials.configuredSites')}
              </p>
              <div className="space-y-1.5">
                {genericSites.map(([source, status]) => {
                  const expanded = expandedSource === source
                  const count = status.accounts ?? 1
                  return (
                    // One card per site: the account panel opens inside it, so
                    // it is never a free-floating block under the list.
                    <div
                      key={source}
                      data-site={source}
                      className={`rounded-lg border overflow-hidden transition-colors ${expanded ? 'border-vault-accent/60' : 'border-vault-border'}`}
                    >
                      <div className="flex items-center justify-between bg-vault-input px-3 py-2">
                        <button
                          onClick={() => setExpandedSource(expanded ? null : source)}
                          aria-label={t('credentials.showAccounts', { source })}
                          aria-expanded={expanded}
                          className="flex-1 min-w-0 flex items-center gap-2 text-left"
                        >
                          {expanded ? (
                            <ChevronUp size={14} className="text-vault-text-muted shrink-0" />
                          ) : (
                            <ChevronDown size={14} className="text-vault-text-muted shrink-0" />
                          )}
                          <span className="w-1.5 h-1.5 rounded-full bg-green-500 shrink-0" />
                          <span className="text-sm text-vault-text font-medium truncate">
                            {source}
                          </span>
                          {status.account && (
                            <span className="text-xs text-vault-text-muted truncate">
                              {status.account}
                            </span>
                          )}
                          {count > 1 && (
                            <span className="text-xs text-vault-text-muted bg-vault-card border border-vault-border rounded px-1.5 py-0.5 shrink-0">
                              {t('credentials.accountCount', { count: String(count) })}
                            </span>
                          )}
                        </button>
                        {count <= 1 && (
                          <Button
                            variant="ghost"
                            size="sm"
                            className="text-red-400/70 hover:text-red-400"
                            onClick={() => handleClear(source)}
                            disabled={clearingSource === source}

                            aria-label={t('credentials.clearConfirm', { source })}
                          >
                            {clearingSource === source ? <span>...</span> : <Trash2 size={13} />}
                          </Button>
                        )}
                      </div>
                      {expanded && (
                        <div className="border-t border-vault-border px-3 py-3">
                          <CredentialAccounts
                            source={source}
                            refreshKey={accountsRefreshKey}
                            onChanged={onRefresh}
                            title={t('credentials.accountsOf', { source })}
                            onAddAccount={() => handleAddAccountTo(source)}
                            addAccountLabel={t('credentials.addAccountTo', { source })}
                          />
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {!credLoading && genericSites.length === 0 && (
            <p className="text-xs text-vault-text-muted mb-4">
              {t('credentials.noGenericCookies')}
            </p>
          )}

          {/* Add credentials form */}
          <div className="pt-3 border-t border-vault-border/50">
            <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-3">
              {t('credentials.addSite')}
            </p>
            <div className="space-y-3">
              {/* URL detection */}
              <div>
                <label className="block text-xs text-vault-text-muted mb-1">
                  {t('credentials.urlDetect')}
                </label>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={urlInput}
                    onChange={(e) => setUrlInput(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleDetect()}
                    placeholder={t('credentials.urlPlaceholder')}
                    className={`${inputClass} flex-1`}
                  />
                  <Button
                    variant="secondary"
                    size="md"
                    onClick={handleDetect}
                    disabled={detecting || !urlInput.trim()}
                  >
                    {detecting ? t('credentials.detecting') : <Search size={16} />}
                  </Button>
                </div>
                {detectedName && (
                  <p className="text-xs text-green-400 mt-1">
                    {t('credentials.detected', { site: detectedName })}
                  </p>
                )}
              </div>

              {/* Site name */}
              <div>
                <label className="block text-xs text-vault-text-muted mb-1">
                  {t('credentials.siteName')}
                </label>
                <input
                  type="text"
                  value={sourceName}
                  onChange={(e) => setSourceName(e.target.value)}
                  placeholder={t('credentials.siteNamePlaceholder')}
                  className={inputClass}
                />
                <p className="text-xs text-vault-text-muted mt-1">
                  {t('credentials.orTypeManually')}
                </p>
                {existingTarget && (
                  <p className="text-xs text-vault-accent mt-1">
                    {t('credentials.existingSiteHint', {
                      source: targetSource,
                      account: existingTarget.account ?? '',
                    })}
                  </p>
                )}
              </div>

              {/* Account name (optional) */}
              <div>
                <label
                  htmlFor="site-credential-account"
                  className="block text-xs text-vault-text-muted mb-1"
                >
                  {t('credentials.newAccountName')}
                </label>
                <input
                  id="site-credential-account"
                  ref={accountInputRef}
                  type="text"
                  value={accountName}
                  onChange={(e) => setAccountName(sanitizeAccountName(e.target.value))}
                  placeholder={t('credentials.newAccountPlaceholder')}
                  autoComplete="off"
                  className={inputClass}
                />
                <p className="text-xs text-vault-text-muted mt-1">
                  {t('credentials.newAccountHint')}
                </p>
              </div>

              {/* Tab switcher */}
              <div className="flex bg-vault-input border border-vault-border rounded overflow-hidden">
                <button
                  onClick={() => setActiveTab('cookies')}
                  className={`flex-1 px-3 py-2 text-sm transition-colors ${activeTab === 'cookies' ? 'bg-vault-accent text-white' : 'text-vault-text-muted hover:text-vault-text'}`}
                >
                  {t('credentials.tabCookies')}
                </button>
                <button
                  onClick={() => setActiveTab('userpass')}
                  className={`flex-1 px-3 py-2 text-sm transition-colors ${activeTab === 'userpass' ? 'bg-vault-accent text-white' : 'text-vault-text-muted hover:text-vault-text'}`}
                >
                  {t('credentials.tabUserPass')}
                </button>
              </div>

              {/* Tab content */}
              {activeTab === 'cookies' ? (
                <div>
                  <label className="block text-xs text-vault-text-muted mb-1">
                    {t('credentials.cookies')}
                  </label>
                  <textarea
                    value={cookiesText}
                    onChange={(e) => setCookiesText(e.target.value)}
                    placeholder={t('credentials.cookiesMultiFormat')}
                    rows={4}
                    className={`${inputClass} resize-none font-mono text-xs leading-relaxed`}
                  />
                </div>
              ) : (
                <div className="space-y-3">
                  <div>
                    <label className="block text-xs text-vault-text-muted mb-1">
                      {t('credentials.username')}
                    </label>
                    <input
                      type="text"
                      value={username}
                      onChange={(e) => setUsername(e.target.value)}
                      placeholder={t('credentials.usernamePlaceholder')}
                      className={inputClass}
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-vault-text-muted mb-1">
                      {t('credentials.password')}
                    </label>
                    <input
                      type="password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder={t('credentials.passwordPlaceholder')}
                      className={inputClass}
                    />
                  </div>
                </div>
              )}

              <Button
                variant="primary"
                size="md"
                onClick={handleSave}
                disabled={saving || !canSave}
              >
                {saving ? t('credentials.saving') : t('credentials.save')}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
