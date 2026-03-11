'use client'

import { useState, useEffect, useCallback } from 'react'
import { ChevronUp, ChevronDown, Eye, EyeOff, RefreshCw, Trash2, Key, ExternalLink } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import type { Credentials, EhAccount, PluginInfo, CredentialFlow } from '@/lib/types'

// Common site presets with suggested cookie keys
const SITE_PRESETS: Record<string, string[]> = {
  twitter: ['auth_token', 'ct0'],
  instagram: ['sessionid', 'csrftoken'],
  danbooru: ['_danbooru2_session'],
  kemono: ['session'],
  gelbooru: ['user_id', 'pass_hash'],
  sankaku: ['login', 'pass_hash'],
}

const PRESET_SITE_NAMES = Object.keys(SITE_PRESETS)

// ── Shared style constants ─────────────────────────────────────────────────

const inputClass =
  'w-full bg-vault-input border border-vault-border rounded px-3 py-2 text-vault-text placeholder-vault-text-muted focus:outline-none focus:border-vault-accent text-sm'
const btnPrimary =
  'px-4 py-2 bg-vault-accent hover:bg-vault-accent/90 disabled:opacity-40 disabled:cursor-not-allowed rounded text-white text-sm font-medium transition-colors'
const btnSecondary =
  'px-4 py-2 bg-vault-input border border-vault-border hover:border-vault-border-hover rounded text-vault-text-secondary text-sm transition-colors'

// ── StatusBadge ────────────────────────────────────────────────────────────

function StatusBadge({ configured }: { configured: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1 text-xs ${configured ? 'text-green-500' : 'text-vault-text-muted'}`}
    >
      <span
        className={`w-1.5 h-1.5 rounded-full ${configured ? 'bg-green-500' : 'bg-vault-text-muted'}`}
      />
      {configured ? t('credentials.configured') : t('credentials.notConfigured')}
    </span>
  )
}

// ── EhExtras: site toggle + account info ──────────────────────────────────

function EhExtras({
  ehAccount,
  ehAccountLoading,
  onRefresh,
  useEx,
  useExLoading,
  onToggleEx,
}: {
  ehAccount: EhAccount | null
  ehAccountLoading: boolean
  onRefresh: () => void
  useEx: boolean
  useExLoading: boolean
  onToggleEx: () => void
}) {
  return (
    <>
      {/* Site toggle */}
      <div className="flex items-center justify-between mb-4 mt-4">
        <div>
          <p className="text-sm text-vault-text">{t('credentials.ehSite')}</p>
          <p className="text-xs text-vault-text-muted mt-0.5">{t('credentials.ehSiteDesc')}</p>
        </div>
        <div className="flex bg-vault-input border border-vault-border rounded overflow-hidden">
          <button
            onClick={() => useEx && onToggleEx()}
            disabled={useExLoading}
            className={`px-3 py-1.5 text-xs transition-colors ${!useEx ? 'bg-vault-accent text-white' : 'text-vault-text-muted hover:text-vault-text'}`}
          >
            {t('credentials.ehSiteEh')}
          </button>
          <button
            onClick={() => !useEx && onToggleEx()}
            disabled={useExLoading}
            className={`px-3 py-1.5 text-xs transition-colors ${useEx ? 'bg-vault-accent text-white' : 'text-vault-text-muted hover:text-vault-text'}`}
          >
            {t('credentials.ehSiteEx')}
          </button>
        </div>
      </div>

      {/* Refresh account button */}
      <div className="mb-3">
        <button
          onClick={onRefresh}
          disabled={ehAccountLoading}
          className={btnSecondary}
        >
          <RefreshCw size={14} className="inline mr-1.5" />
          {ehAccountLoading ? t('settings.refreshing') : t('settings.refreshAccount')}
        </button>
      </div>

      {/* Account info */}
      {ehAccount && (
        <div className="mt-2 bg-vault-input border border-vault-border rounded-lg p-3">
          <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">
            {t('settings.accountStatus')}
          </p>
          <div className="space-y-1">
            <div className="flex justify-between text-sm">
              <span className="text-vault-text-muted">{t('settings.valid')}</span>
              <span className={ehAccount.valid ? 'text-green-400' : 'text-red-400'}>
                {ehAccount.valid ? t('settings.yes') : t('settings.no')}
              </span>
            </div>
            {ehAccount.credits !== undefined && (
              <div className="flex justify-between text-sm">
                <span className="text-vault-text-muted">{t('settings.credits')}</span>
                <span className="text-vault-text-secondary">
                  {ehAccount.credits.toLocaleString()}
                </span>
              </div>
            )}
            {ehAccount.hath_perks !== undefined && (
              <div className="flex justify-between text-sm">
                <span className="text-vault-text-muted">{t('settings.hathPerks')}</span>
                <span className="text-vault-text-secondary">{ehAccount.hath_perks}</span>
              </div>
            )}
            {ehAccount.error && (
              <p className="text-xs text-red-400 mt-1">{ehAccount.error}</p>
            )}
          </div>
        </div>
      )}
    </>
  )
}

// ── EhFieldsFlow ──────────────────────────────────────────────────────────

function EhFieldsFlow({
  onSaved,
}: {
  onSaved: (account: EhAccount) => void
}) {
  const [memberId, setMemberId] = useState('')
  const [passHash, setPassHash] = useState('')
  const [sk, setSk] = useState('')
  const [igneous, setIgneous] = useState('')
  const [saving, setSaving] = useState(false)
  const [showPassHash, setShowPassHash] = useState(false)

  const handleSave = async () => {
    if (!memberId.trim() || !passHash.trim()) return
    setSaving(true)
    try {
      const data: { ipb_member_id: string; ipb_pass_hash: string; sk?: string; igneous?: string } =
        { ipb_member_id: memberId.trim(), ipb_pass_hash: passHash.trim() }
      if (sk.trim()) data.sk = sk.trim()
      if (igneous.trim()) data.igneous = igneous.trim()
      const result = await api.settings.setEhCookies(data)
      toast.success(t('settings.ehCookiesSaved'))
      onSaved(result.account)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.ehCookiesFailed'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-vault-text-muted">{t('credentials.ehCookieOnlyHint')}</p>
      <div>
        <label className="block text-xs text-vault-text-muted mb-1">ipb_member_id</label>
        <input
          type="text"
          value={memberId}
          onChange={(e) => setMemberId(e.target.value)}
          placeholder={t('settings.enterIpbMemberId')}
          className={inputClass}
        />
      </div>
      <div>
        <label className="block text-xs text-vault-text-muted mb-1">ipb_pass_hash</label>
        <div className="relative">
          <input
            type={showPassHash ? 'text' : 'password'}
            value={passHash}
            onChange={(e) => setPassHash(e.target.value)}
            placeholder={t('settings.enterIpbPassHash')}
            className={`${inputClass} pr-10`}
          />
          <button
            type="button"
            onClick={() => setShowPassHash((v) => !v)}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-vault-text-muted hover:text-vault-text transition-colors px-1"
          >
            {showPassHash ? <EyeOff size={14} /> : <Eye size={14} />}
          </button>
        </div>
      </div>
      <div>
        <label className="block text-xs text-vault-text-muted mb-1">
          {t('settings.ehIgneousLabel')}
        </label>
        <input
          type="text"
          value={igneous}
          onChange={(e) => setIgneous(e.target.value)}
          placeholder={t('settings.enterIgneous')}
          className={inputClass}
        />
      </div>
      <div>
        <label className="block text-xs text-vault-text-muted mb-1">
          {t('settings.ehSkLabel')}
        </label>
        <input
          type="text"
          value={sk}
          onChange={(e) => setSk(e.target.value)}
          placeholder={t('settings.enterSk')}
          className={inputClass}
        />
      </div>
      <button onClick={handleSave} disabled={saving || !memberId.trim() || !passHash.trim()} className={btnPrimary}>
        {saving ? t('settings.saving') : t('settings.saveCookies')}
      </button>
    </div>
  )
}

// ── PixivOAuthFlow ────────────────────────────────────────────────────────

function PixivOAuthFlow({ onSaved }: { onSaved: (username: string) => void }) {
  const [oauthUrl, setOauthUrl] = useState('')
  const [codeVerifier, setCodeVerifier] = useState('')
  const [callbackUrl, setCallbackUrl] = useState('')
  const [saving, setSaving] = useState(false)

  const handleGetUrl = async () => {
    try {
      const res = await api.settings.getPixivOAuthUrl()
      setOauthUrl(res.url)
      setCodeVerifier(res.code_verifier)
      window.open(res.url, '_blank')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToLoad'))
    }
  }

  const handleExchange = async () => {
    if (!callbackUrl.trim() || !codeVerifier) return
    setSaving(true)
    try {
      const res = await api.settings.pixivOAuthCallback(callbackUrl.trim(), codeVerifier)
      toast.success(`${t('settings.pixivSaved')}: ${res.username}`)
      onSaved(res.username)
      setCallbackUrl('')
      setOauthUrl('')
      setCodeVerifier('')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.pixivFailed'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-3 mt-2">
      <div className="bg-yellow-900/20 border border-yellow-700/30 rounded-lg p-3 text-xs text-yellow-300/90 space-y-1.5">
        <p className="font-semibold">{t('settings.pixivOauthSteps')}</p>
        <p>{t('settings.pixivOauthStep1')}</p>
        <p>{t('settings.pixivOauthStep2')}</p>
        <p>{t('settings.pixivOauthStep3')}</p>
        <p className="text-yellow-400/70">
          {t('settings.pixivOauthHint')}{' '}
          <code className="bg-black/30 px-1 rounded">https://app-api.pixiv.net/...?code=xxx</code>
        </p>
        <p className="text-yellow-400/70">{t('settings.pixivOauthHint2')}</p>
      </div>
      <button onClick={handleGetUrl} className={`${btnSecondary} w-full flex items-center justify-center gap-2`}>
        <ExternalLink size={14} />
        {t('credentials.oauthGetUrl')}
      </button>
      {codeVerifier && (
        <div>
          <p className="text-xs text-vault-text-muted mb-1">{t('settings.pixivOauthStep4')}</p>
          <input
            type="text"
            value={callbackUrl}
            onChange={(e) => setCallbackUrl(e.target.value)}
            placeholder={t('credentials.oauthPasteCallback')}
            className={inputClass}
          />
          <button
            onClick={handleExchange}
            disabled={saving || !callbackUrl.trim()}
            className={`${btnPrimary} mt-3`}
          >
            {saving ? t('settings.saving') : t('credentials.oauthExchange')}
          </button>
        </div>
      )}
    </div>
  )
}

// ── PixivTokenFlow ────────────────────────────────────────────────────────

function PixivTokenFlow({ onSaved }: { onSaved: (username: string) => void }) {
  const [token, setToken] = useState('')
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    if (!token.trim()) return
    setSaving(true)
    try {
      const result = await api.settings.setPixivToken(token.trim())
      toast.success(`${t('settings.pixivSaved')}: ${result.username}`)
      onSaved(result.username)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.pixivFailed'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-3 mt-2">
      <div>
        <label className="block text-xs text-vault-text-muted mb-1">
          {t('settings.pixivRefreshToken')}
        </label>
        <input
          type="password"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          placeholder={t('settings.enterPixivRefreshToken')}
          className={inputClass}
        />
        <p className="text-xs text-vault-text-muted mt-1">{t('settings.pixivHint')}</p>
      </div>
      <button onClick={handleSave} disabled={saving || !token.trim()} className={btnPrimary}>
        {saving ? t('settings.saving') : t('settings.saveToken')}
      </button>
    </div>
  )
}

// ── PixivCookieFlow ───────────────────────────────────────────────────────

function PixivCookieFlow({ onSaved }: { onSaved: (username: string) => void }) {
  const [cookie, setCookie] = useState('')
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    if (!cookie.trim()) return
    setSaving(true)
    try {
      const result = await api.settings.setPixivCookie(cookie.trim())
      toast.success(`${t('settings.pixivSaved')}: ${result.username}`)
      onSaved(result.username)
      setCookie('')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.pixivFailed'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-3 mt-2">
      <div className="bg-blue-900/20 border border-blue-700/30 rounded-lg p-3 text-xs text-blue-300/90 space-y-1.5">
        <p className="font-semibold">{t('settings.pixivCookieTitle')}</p>
        <p>{t('settings.pixivCookieDesc')}</p>
        <ul className="list-disc list-inside mt-1 ml-1">
          <li>{t('settings.pixivCookieStep1')}</li>
          <li>{t('settings.pixivCookieStep2')}</li>
          <li>
            {t('settings.pixivCookieStep3')}{' '}
            <code className="bg-black/30 px-1 rounded">PHPSESSID</code>
          </li>
          <li>{t('settings.pixivCookieStep4')}</li>
        </ul>
      </div>
      <div>
        <label className="block text-xs text-vault-text-muted mb-1">
          {t('credentials.sessionCookie')} (PHPSESSID)
        </label>
        <input
          type="password"
          value={cookie}
          onChange={(e) => setCookie(e.target.value)}
          placeholder={t('settings.pixivTokenExample')}
          className={inputClass}
        />
      </div>
      <button onClick={handleSave} disabled={saving || !cookie.trim()} className={btnPrimary}>
        {saving ? t('settings.saving') : t('credentials.oauthExchange')}
      </button>
    </div>
  )
}

// ── FlowLabel: human-readable flow type label ────────────────────────────

function flowLabel(flow: CredentialFlow): string {
  if (flow.flow_type === 'oauth') return t('credentials.flowOAuth')
  if (flow.flow_type === 'login') return t('credentials.flowLogin')
  return t('credentials.flowFields')
}

// ── PluginCredentialSection ───────────────────────────────────────────────

function PluginCredentialSection({
  plugin,
  isOpen,
  onToggle,
  configured,
  onDeleted,
}: {
  plugin: PluginInfo
  isOpen: boolean
  onToggle: () => void
  configured: boolean
  onDeleted: () => void
}) {
  const flows = plugin.credential_flows ?? []
  const [activeFlow, setActiveFlow] = useState(0)
  const [pixivUsername, setPixivUsername] = useState<string | null>(null)
  const [ehAccount, setEhAccount] = useState<EhAccount | null>(null)
  const [ehAccountLoading, setEhAccountLoading] = useState(false)
  const [useEx, setUseEx] = useState(false)
  const [useExLoading, setUseExLoading] = useState(false)
  const [deleting, setDeleting] = useState(false)

  const isEh = plugin.source_id === 'ehentai'
  const isPixiv = plugin.source_id === 'pixiv'

  useEffect(() => {
    if (isEh && isOpen) {
      api.settings.getEhSite().then((res) => setUseEx(res.use_ex)).catch(() => {})
    }
  }, [isEh, isOpen])

  const handleToggleEx = useCallback(async () => {
    setUseExLoading(true)
    try {
      const res = await api.settings.setEhSite(!useEx)
      setUseEx(res.use_ex)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToLoad'))
    } finally {
      setUseExLoading(false)
    }
  }, [useEx])

  const handleEhRefresh = useCallback(async () => {
    setEhAccountLoading(true)
    try {
      const account = await api.settings.getEhAccount()
      setEhAccount(account)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.ehRefreshFailed'))
    } finally {
      setEhAccountLoading(false)
    }
  }, [])

  const handleDelete = useCallback(async () => {
    if (!confirm(t('credentials.deleteConfirm', { source: plugin.name }))) return
    setDeleting(true)
    try {
      await api.settings.deleteCredential(plugin.source_id)
      toast.success(t('credentials.deleted', { source: plugin.name }))
      onDeleted()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('credentials.clearFailed'))
    } finally {
      setDeleting(false)
    }
  }, [plugin, onDeleted])

  const currentFlow = flows[activeFlow] ?? null

  return (
    <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between">
        <button
          onClick={onToggle}
          className="flex-1 flex items-center justify-between px-5 py-4 text-left hover:bg-vault-card-hover transition-colors"
        >
          <span className="font-medium text-vault-text text-sm">{plugin.name}</span>
          {isOpen ? (
            <ChevronUp size={16} className="text-vault-text-muted" />
          ) : (
            <ChevronDown size={16} className="text-vault-text-muted" />
          )}
        </button>
        <div className="pr-5 shrink-0">
          <StatusBadge configured={configured} />
        </div>
      </div>

      {/* Body */}
      {isOpen && (
        <div className="px-5 pb-5 border-t border-vault-border">
          {/* EH extras: site toggle + account refresh */}
          {isEh && (
            <EhExtras
              ehAccount={ehAccount}
              ehAccountLoading={ehAccountLoading}
              onRefresh={handleEhRefresh}
              useEx={useEx}
              useExLoading={useExLoading}
              onToggleEx={handleToggleEx}
            />
          )}

          {/* Flow tabs (only if multiple flows) */}
          {flows.length > 1 && (
            <div className="flex mt-4 bg-vault-input border border-vault-border rounded overflow-hidden">
              {flows.map((flow, idx) => (
                <button
                  key={idx}
                  onClick={() => setActiveFlow(idx)}
                  className={`flex-1 px-3 py-2 text-sm transition-colors ${activeFlow === idx ? 'bg-vault-accent text-white' : 'text-vault-text-muted hover:text-vault-text'}`}
                >
                  {flowLabel(flow)}
                </button>
              ))}
            </div>
          )}

          {/* Flow content */}
          {currentFlow && (
            <div className={flows.length > 1 ? 'mt-4' : 'mt-4'}>
              {/* EH-specific flows */}
              {isEh && currentFlow.flow_type === 'fields' && (
                <EhFieldsFlow
                  onSaved={(account) => {
                    setEhAccount(account)
                    onDeleted() // re-check configured status via parent refresh
                  }}
                />
              )}

              {/* Pixiv-specific flows */}
              {isPixiv && currentFlow.flow_type === 'oauth' && (
                <PixivOAuthFlow
                  onSaved={(username) => {
                    setPixivUsername(username)
                    onDeleted()
                  }}
                />
              )}
              {isPixiv && currentFlow.flow_type === 'fields' && (
                <PixivTokenFlow
                  onSaved={(username) => {
                    setPixivUsername(username)
                    onDeleted()
                  }}
                />
              )}
              {isPixiv && currentFlow.flow_type === 'login' && (
                <PixivCookieFlow
                  onSaved={(username) => {
                    setPixivUsername(username)
                    onDeleted()
                  }}
                />
              )}
            </div>
          )}

          {/* Pixiv username display */}
          {isPixiv && pixivUsername && (
            <div className="mt-4 flex items-center gap-2 text-sm p-3 bg-vault-input border border-vault-border rounded-lg">
              <span className="text-vault-text-muted">{t('settings.pixivAccount')}:</span>
              <span className="text-vault-text-secondary">{pixivUsername}</span>
            </div>
          )}

          {/* Delete button */}
          {configured && (
            <button
              onClick={handleDelete}
              disabled={deleting}
              className="mt-4 px-3 py-1.5 bg-red-600/20 border border-red-500/30 text-red-400 rounded text-sm hover:bg-red-600/30 transition-colors disabled:opacity-40 flex items-center gap-1.5"
            >
              <Trash2 size={13} />
              {deleting ? t('credentials.saving') : isEh ? t('settings.clearCookie') : isPixiv ? t('settings.clearToken') : t('credentials.clearFailed')}
            </button>
          )}
        </div>
      )}
    </div>
  )
}

// ── GenericCookieSection ───────────────────────────────────────────────────

function GenericCookieSection({
  credentials,
  credLoading,
  onCredentialsChange,
}: {
  credentials: Credentials | null
  credLoading: boolean
  onCredentialsChange: (next: Credentials) => void
}) {
  const [isOpen, setIsOpen] = useState(false)
  const [genericSiteName, setGenericSiteName] = useState('')
  const [genericCookiesText, setGenericCookiesText] = useState('')
  const [genericSaving, setGenericSaving] = useState(false)
  const [genericClearingSource, setGenericClearingSource] = useState<string | null>(null)

  const genericSites = credentials
    ? Object.entries(credentials).filter(
        ([source]) => source !== 'ehentai' && source !== 'pixiv' && credentials[source].configured,
      )
    : []

  const suggestedKeys =
    genericSiteName && SITE_PRESETS[genericSiteName.toLowerCase()]
      ? SITE_PRESETS[genericSiteName.toLowerCase()]
      : null

  const handleGenericSave = async () => {
    const source = genericSiteName.trim()
    if (!source || !genericCookiesText.trim()) return
    const cookies: Record<string, string> = {}
    for (const line of genericCookiesText.split('\n')) {
      const trimmed = line.trim()
      if (!trimmed) continue
      const eqIdx = trimmed.indexOf('=')
      if (eqIdx <= 0) continue
      const k = trimmed.slice(0, eqIdx).trim()
      const v = trimmed.slice(eqIdx + 1).trim()
      if (k) cookies[k] = v
    }
    if (Object.keys(cookies).length === 0) {
      toast.error(t('credentials.saveFailed'))
      return
    }
    setGenericSaving(true)
    try {
      await api.settings.setGenericCookie(source, cookies)
      toast.success(t('credentials.saved', { source }))
      if (credentials) {
        onCredentialsChange({ ...credentials, [source]: { configured: true } })
      }
      setGenericSiteName('')
      setGenericCookiesText('')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('credentials.saveFailed'))
    } finally {
      setGenericSaving(false)
    }
  }

  const handleGenericClear = async (source: string) => {
    if (!confirm(t('credentials.clearConfirm', { source }))) return
    setGenericClearingSource(source)
    try {
      await api.settings.deleteCredential(source)
      toast.success(t('credentials.cleared', { source }))
      if (credentials) {
        const next = { ...credentials }
        delete next[source]
        onCredentialsChange(next)
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('credentials.clearFailed'))
    } finally {
      setGenericClearingSource(null)
    }
  }

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
                {genericSites.map(([source]) => (
                  <div
                    key={source}
                    className="flex items-center justify-between bg-vault-input border border-vault-border rounded-lg px-3 py-2"
                  >
                    <div className="flex items-center gap-2">
                      <span className="w-1.5 h-1.5 rounded-full bg-green-500 shrink-0" />
                      <span className="text-sm text-vault-text font-medium">{source}</span>
                    </div>
                    <button
                      onClick={() => handleGenericClear(source)}
                      disabled={genericClearingSource === source}
                      className="text-xs text-red-400/70 hover:text-red-400 transition-colors flex items-center gap-1 px-2 py-1 disabled:opacity-40"
                      aria-label={t('credentials.clearConfirm', { source })}
                    >
                      {genericClearingSource === source ? (
                        <span>...</span>
                      ) : (
                        <Trash2 size={13} />
                      )}
                    </button>
                  </div>
                ))}
              </div>
            </div>
          )}

          {!credLoading && genericSites.length === 0 && (
            <p className="text-xs text-vault-text-muted mb-4">
              {t('credentials.noGenericCookies')}
            </p>
          )}

          {/* Add site form */}
          <div className="pt-3 border-t border-vault-border/50">
            <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-3">
              {t('credentials.addSite')}
            </p>
            <div className="space-y-3">
              <div>
                <label className="block text-xs text-vault-text-muted mb-1">
                  {t('credentials.siteName')}
                </label>
                <input
                  type="text"
                  list="site-presets"
                  value={genericSiteName}
                  onChange={(e) => setGenericSiteName(e.target.value)}
                  placeholder={t('credentials.siteNamePlaceholder')}
                  className={inputClass}
                />
                <datalist id="site-presets">
                  {PRESET_SITE_NAMES.map((name) => (
                    <option key={name} value={name} />
                  ))}
                </datalist>
              </div>

              {suggestedKeys && (
                <div className="bg-vault-input border border-vault-border rounded-lg px-3 py-2">
                  <p className="text-xs text-vault-text-muted mb-1">
                    {t('credentials.suggestedKeys')}:
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {suggestedKeys.map((k) => (
                      <button
                        key={k}
                        type="button"
                        onClick={() => {
                          setGenericCookiesText((prev) => {
                            const lines = prev.split('\n').filter((l) => l.trim())
                            const alreadyHas = lines.some((l) => l.startsWith(`${k}=`))
                            if (alreadyHas) return prev
                            return prev ? `${prev}\n${k}=` : `${k}=`
                          })
                        }}
                        className="text-xs bg-vault-card border border-vault-border rounded px-2 py-0.5 text-vault-text-secondary hover:text-vault-accent hover:border-vault-accent/50 transition-colors font-mono"
                      >
                        {k}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <div>
                <label className="block text-xs text-vault-text-muted mb-1">
                  {t('credentials.cookies')}
                </label>
                <textarea
                  value={genericCookiesText}
                  onChange={(e) => setGenericCookiesText(e.target.value)}
                  placeholder={t('credentials.cookiesPlaceholder')}
                  rows={4}
                  className={`${inputClass} resize-none font-mono text-xs leading-relaxed`}
                />
                <p className="text-xs text-vault-text-muted mt-1">
                  {t('credentials.cookiesHint')}
                </p>
              </div>

              <button
                onClick={handleGenericSave}
                disabled={
                  genericSaving || !genericSiteName.trim() || !genericCookiesText.trim()
                }
                className={btnPrimary}
              >
                {genericSaving ? t('credentials.saving') : t('credentials.save')}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────

export default function CredentialsPage() {
  useLocale()

  const [plugins, setPlugins] = useState<PluginInfo[]>([])
  const [pluginsLoading, setPluginsLoading] = useState(true)
  const [credentials, setCredentials] = useState<Credentials | null>(null)
  const [credLoading, setCredLoading] = useState(true)

  // Track which plugin section is expanded (by source_id)
  const [openSection, setOpenSection] = useState<string | null>('ehentai')

  useEffect(() => {
    api.plugins
      .list()
      .then((res) => {
        // Only show plugins that have credential flows defined
        const withFlows = res.plugins.filter(
          (p) => Array.isArray(p.credential_flows) && p.credential_flows.length > 0,
        )
        setPlugins(withFlows)
      })
      .catch((err) => toast.error(err instanceof Error ? err.message : t('common.failedToLoad')))
      .finally(() => setPluginsLoading(false))

    api.settings
      .getCredentials()
      .then(setCredentials)
      .catch((err) => toast.error(err instanceof Error ? err.message : t('common.failedToLoad')))
      .finally(() => setCredLoading(false))
  }, [])

  // Refresh credentials after a save/delete action
  const refreshCredentials = useCallback(() => {
    api.settings.getCredentials().then(setCredentials).catch(() => {})
  }, [])

  const toggleSection = useCallback((sourceId: string) => {
    setOpenSection((prev) => (prev === sourceId ? null : sourceId))
  }, [])

  // Exclude gallery_dl from the plugin list (rendered as generic cookie section)
  const pluginSections = plugins.filter((p) => p.source_id !== 'gallery_dl')

  return (
    <div className="max-w-2xl">
      <div className="flex items-center gap-3 mb-6">
        <Key size={22} className="text-vault-accent" />
        <h1 className="text-2xl font-bold text-vault-text">{t('credentials.title')}</h1>
      </div>

      {pluginsLoading ? (
        <div className="text-sm text-vault-text-muted">{t('common.loading')}</div>
      ) : (
        <div className="space-y-3">
          {/* Plugin-driven sections */}
          {pluginSections.map((plugin) => (
            <PluginCredentialSection
              key={plugin.source_id}
              plugin={plugin}
              isOpen={openSection === plugin.source_id}
              onToggle={() => toggleSection(plugin.source_id)}
              configured={credentials?.[plugin.source_id]?.configured ?? false}
              onDeleted={refreshCredentials}
            />
          ))}

          {/* Generic cookie section (gallery-dl sites + others) */}
          <GenericCookieSection
            credentials={credentials}
            credLoading={credLoading}
            onCredentialsChange={setCredentials}
          />
        </div>
      )}
    </div>
  )
}
