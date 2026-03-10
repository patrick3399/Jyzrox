'use client'

import { useState, useEffect, useCallback } from 'react'
import { ChevronUp, ChevronDown, Eye, EyeOff, RefreshCw, Trash2, Key } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import type { Credentials, EhAccount } from '@/lib/types'

type SectionKey = 'ehentai' | 'pixiv' | 'generic'

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

function StatusIndicator({ configured }: { configured: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1 text-xs ${configured ? 'text-green-500' : 'text-vault-text-muted'}`}
    >
      <span
        className={`w-1.5 h-1.5 rounded-full ${configured ? 'bg-green-500' : 'bg-vault-text-muted'}`}
      />
      {configured ? t('settings.configured') : t('settings.notConfigured')}
    </span>
  )
}

function SectionHeader({
  title,
  sectionKey,
  activeSection,
  onToggle,
}: {
  title: string
  sectionKey: SectionKey
  activeSection: SectionKey | null
  onToggle: (key: SectionKey) => void
}) {
  const isOpen = activeSection === sectionKey
  return (
    <button
      onClick={() => onToggle(sectionKey)}
      className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-vault-card-hover transition-colors"
    >
      <span className="font-medium text-vault-text text-sm">{title}</span>
      {isOpen ? (
        <ChevronUp size={16} className="text-vault-text-muted" />
      ) : (
        <ChevronDown size={16} className="text-vault-text-muted" />
      )}
    </button>
  )
}

export default function CredentialsPage() {
  useLocale()
  const [activeSection, setActiveSection] = useState<SectionKey | null>('ehentai')

  // Credentials state (for status indicators)
  const [credentials, setCredentials] = useState<Credentials | null>(null)
  const [credLoading, setCredLoading] = useState(true)

  // EH Cookie form
  const [ehMemberId, setEhMemberId] = useState('')
  const [ehPassHash, setEhPassHash] = useState('')
  const [ehSk, setEhSk] = useState('')
  const [ehIgneous, setEhIgneous] = useState('')
  const [ehSaving, setEhSaving] = useState(false)
  const [showPassHash, setShowPassHash] = useState(false)
  const [ehAccount, setEhAccount] = useState<EhAccount | null>(null)
  const [ehAccountLoading, setEhAccountLoading] = useState(false)

  // Pixiv login mode
  const [pixivLoginMode, setPixivLoginMode] = useState<'oauth' | 'token' | 'cookie'>('oauth')
  const [pixivToken, setPixivToken] = useState('')
  const [pixivCookie, setPixivCookie] = useState('')
  const [pixivSaving, setPixivSaving] = useState(false)
  const [pixivUsername, setPixivUsername] = useState<string | null>(null)
  const [pixivOauthUrl, setPixivOauthUrl] = useState('')
  const [pixivCodeVerifier, setPixivCodeVerifier] = useState('')
  const [pixivCallbackUrl, setPixivCallbackUrl] = useState('')

  // EH site toggle (E-Hentai vs ExHentai)
  const [useEx, setUseEx] = useState(false)
  const [useExLoading, setUseExLoading] = useState(false)

  // Generic site cookies
  const [genericSiteName, setGenericSiteName] = useState('')
  const [genericCookiesText, setGenericCookiesText] = useState('')
  const [genericSaving, setGenericSaving] = useState(false)
  const [genericClearingSource, setGenericClearingSource] = useState<string | null>(null)

  const inputClass =
    'w-full bg-vault-input border border-vault-border rounded px-3 py-2 text-vault-text placeholder-vault-text-muted focus:outline-none focus:border-vault-accent text-sm'
  const btnPrimary =
    'px-4 py-2 bg-vault-accent hover:bg-vault-accent/90 disabled:opacity-40 disabled:cursor-not-allowed rounded text-white text-sm font-medium transition-colors'
  const btnSecondary =
    'px-4 py-2 bg-vault-input border border-vault-border hover:border-vault-border-hover rounded text-vault-text-secondary text-sm transition-colors'

  const toggleSection = useCallback((key: SectionKey) => {
    setActiveSection((prev) => (prev === key ? null : key))
  }, [])

  // Load credentials on mount
  useEffect(() => {
    api.settings
      .getCredentials()
      .then(setCredentials)
      .catch((err) => toast.error(err instanceof Error ? err.message : t('common.failedToLoad')))
      .finally(() => setCredLoading(false))

    api.settings.getEhSite().then((res) => setUseEx(res.use_ex)).catch(() => {})
  }, [])

  // EH: Toggle E-Hentai vs ExHentai
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

  // EH: Save cookies
  const handleEhSave = useCallback(async () => {
    if (!ehMemberId.trim() || !ehPassHash.trim()) return
    setEhSaving(true)
    try {
      const data: { ipb_member_id: string; ipb_pass_hash: string; sk?: string; igneous?: string } =
        {
          ipb_member_id: ehMemberId.trim(),
          ipb_pass_hash: ehPassHash.trim(),
        }
      if (ehSk.trim()) data.sk = ehSk.trim()
      if (ehIgneous.trim()) data.igneous = ehIgneous.trim()
      const result = await api.settings.setEhCookies(data)
      toast.success(t('settings.ehCookiesSaved'))
      setEhAccount(result.account)
      setCredentials((prev) => (prev ? { ...prev, ehentai: { configured: true } } : prev))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.ehCookiesFailed'))
    } finally {
      setEhSaving(false)
    }
  }, [ehMemberId, ehPassHash, ehSk, ehIgneous])

  // EH: Refresh account info
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

  // EH: Clear credential
  const handleClearEh = useCallback(async () => {
    if (!confirm(t('settings.clearEhConfirm'))) return
    try {
      await api.settings.deleteCredential('ehentai')
      toast.success(t('settings.ehCookiesCleared'))
      setCredentials((prev) => (prev ? { ...prev, ehentai: { configured: false } } : prev))
      setEhAccount(null)
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : t('settings.clearFailed'))
    }
  }, [])

  // Pixiv: Save token
  const handlePixivSave = useCallback(async () => {
    if (!pixivToken.trim()) return
    setPixivSaving(true)
    try {
      const result = await api.settings.setPixivToken(pixivToken.trim())
      toast.success(`${t('settings.pixivSaved')}: ${result.username}`)
      setPixivUsername(result.username)
      setCredentials((prev) => (prev ? { ...prev, pixiv: { configured: true } } : prev))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.pixivFailed'))
    } finally {
      setPixivSaving(false)
    }
  }, [pixivToken])

  // Pixiv: Save cookie
  const handlePixivCookieSave = useCallback(async () => {
    if (!pixivCookie.trim()) return
    setPixivSaving(true)
    try {
      const result = await api.settings.setPixivCookie(pixivCookie.trim())
      toast.success(`${t('settings.pixivSaved')}: ${result.username}`)
      setPixivUsername(result.username)
      setCredentials((prev) => (prev ? { ...prev, pixiv: { configured: true } } : prev))
      setPixivCookie('')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.pixivFailed'))
    } finally {
      setPixivSaving(false)
    }
  }, [pixivCookie])

  // Pixiv: Get OAuth URL
  const handlePixivGetOauth = useCallback(async () => {
    try {
      const res = await api.settings.getPixivOAuthUrl()
      setPixivOauthUrl(res.url)
      setPixivCodeVerifier(res.code_verifier)
      window.open(res.url, '_blank')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToLoad'))
    }
  }, [])

  // Pixiv: Exchange OAuth Callback
  const handlePixivExchange = useCallback(async () => {
    if (!pixivCallbackUrl.trim() || !pixivCodeVerifier) return
    setPixivSaving(true)
    try {
      const res = await api.settings.pixivOAuthCallback(
        pixivCallbackUrl.trim(),
        pixivCodeVerifier,
      )
      toast.success(`${t('settings.pixivSaved')}: ${res.username}`)
      setPixivUsername(res.username)
      setCredentials((prev) => (prev ? { ...prev, pixiv: { configured: true } } : prev))
      setPixivCallbackUrl('')
      setPixivOauthUrl('')
      setPixivCodeVerifier('')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.pixivFailed'))
    } finally {
      setPixivSaving(false)
    }
  }, [pixivCallbackUrl, pixivCodeVerifier])

  // Pixiv: Clear credential
  const handleClearPixiv = useCallback(async () => {
    if (!confirm(t('settings.confirmClearPixiv'))) return
    try {
      await api.settings.deleteCredential('pixiv')
      toast.success(t('settings.pixivTokenCleared'))
      setCredentials((prev) => (prev ? { ...prev, pixiv: { configured: false } } : prev))
      setPixivUsername(null)
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : t('settings.clearFailed'))
    }
  }, [])

  // Generic: Save cookies
  const handleGenericSave = useCallback(async () => {
    const source = genericSiteName.trim()
    if (!source || !genericCookiesText.trim()) return
    // Parse key=value pairs
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
      setCredentials((prev) => (prev ? { ...prev, [source]: { configured: true } } : prev))
      setGenericSiteName('')
      setGenericCookiesText('')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('credentials.saveFailed'))
    } finally {
      setGenericSaving(false)
    }
  }, [genericSiteName, genericCookiesText])

  // Generic: Clear cookie for a site
  const handleGenericClear = useCallback(
    async (source: string) => {
      if (!confirm(t('credentials.clearConfirm', { source }))) return
      setGenericClearingSource(source)
      try {
        await api.settings.deleteCredential(source)
        toast.success(t('credentials.cleared', { source }))
        setCredentials((prev) => {
          if (!prev) return prev
          const next = { ...prev }
          delete next[source]
          return next
        })
      } catch (e: unknown) {
        toast.error(e instanceof Error ? e.message : t('credentials.clearFailed'))
      } finally {
        setGenericClearingSource(null)
      }
    },
    [],
  )

  // Derive generic sites: everything except ehentai and pixiv
  const genericSites = credentials
    ? Object.entries(credentials).filter(
        ([source]) => source !== 'ehentai' && source !== 'pixiv' && credentials[source].configured,
      )
    : []

  const suggestedKeys =
    genericSiteName && SITE_PRESETS[genericSiteName.toLowerCase()]
      ? SITE_PRESETS[genericSiteName.toLowerCase()]
      : null

  return (
    <div className="max-w-2xl">
        <div className="flex items-center gap-3 mb-6">
          <Key size={22} className="text-vault-accent" />
          <h1 className="text-2xl font-bold text-vault-text">{t('credentials.title')}</h1>
        </div>

        <div className="space-y-3">
          {/* ── E-Hentai ── */}
          <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
            <div className="flex items-center justify-between">
              <div className="flex-1">
                <SectionHeader
                  title={t('settings.ehentai')}
                  sectionKey="ehentai"
                  activeSection={activeSection}
                  onToggle={toggleSection}
                />
              </div>
              {!credLoading && credentials && (
                <div className="pr-5">
                  <StatusIndicator configured={credentials.ehentai?.configured ?? false} />
                </div>
              )}
            </div>

            {activeSection === 'ehentai' && (
              <div className="px-5 pb-5 border-t border-vault-border">
                {/* Cookie form */}
                <div className="mt-4 space-y-3">
                  {/* Site toggle */}
                  <div className="flex items-center justify-between mb-4">
                    <div>
                      <p className="text-sm text-vault-text">{t('credentials.ehSite')}</p>
                      <p className="text-xs text-vault-text-muted mt-0.5">{t('credentials.ehSiteDesc')}</p>
                    </div>
                    <div className="flex bg-vault-input border border-vault-border rounded overflow-hidden">
                      <button
                        onClick={() => useEx && handleToggleEx()}
                        disabled={useExLoading}
                        className={`px-3 py-1.5 text-xs transition-colors ${!useEx ? 'bg-vault-accent text-white' : 'text-vault-text-muted hover:text-vault-text'}`}
                      >
                        {t('credentials.ehSiteEh')}
                      </button>
                      <button
                        onClick={() => !useEx && handleToggleEx()}
                        disabled={useExLoading}
                        className={`px-3 py-1.5 text-xs transition-colors ${useEx ? 'bg-vault-accent text-white' : 'text-vault-text-muted hover:text-vault-text'}`}
                      >
                        {t('credentials.ehSiteEx')}
                      </button>
                    </div>
                  </div>
                  <p className="text-xs text-vault-text-muted">
                    {t('credentials.ehCookieOnlyHint')}
                  </p>
                  <div>
                    <label className="block text-xs text-vault-text-muted mb-1">
                      ipb_member_id
                    </label>
                    <input
                      type="text"
                      value={ehMemberId}
                      onChange={(e) => setEhMemberId(e.target.value)}
                      placeholder={t('settings.enterIpbMemberId')}
                      className={inputClass}
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-vault-text-muted mb-1">
                      ipb_pass_hash
                    </label>
                    <div className="relative">
                      <input
                        type={showPassHash ? 'text' : 'password'}
                        value={ehPassHash}
                        onChange={(e) => setEhPassHash(e.target.value)}
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
                      value={ehIgneous}
                      onChange={(e) => setEhIgneous(e.target.value)}
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
                      value={ehSk}
                      onChange={(e) => setEhSk(e.target.value)}
                      placeholder={t('settings.enterSk')}
                      className={inputClass}
                    />
                  </div>
                  <div className="flex gap-2">
                    <button onClick={handleEhSave} disabled={ehSaving} className={btnPrimary}>
                      {ehSaving ? t('settings.saving') : t('settings.saveCookies')}
                    </button>
                    <button
                      onClick={handleEhRefresh}
                      disabled={ehAccountLoading}
                      className={btnSecondary}
                    >
                      <RefreshCw size={14} className="inline mr-1.5" />
                      {ehAccountLoading ? t('settings.refreshing') : t('settings.refreshAccount')}
                    </button>
                  </div>
                </div>

                {/* Account Info */}
                {ehAccount && (
                  <div className="mt-4 bg-vault-input border border-vault-border rounded-lg p-3">
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

                {credentials?.ehentai?.configured && (
                  <button
                    onClick={handleClearEh}
                    className="mt-3 px-3 py-1.5 bg-red-600/20 border border-red-500/30 text-red-400 rounded text-sm hover:bg-red-600/30 transition-colors"
                  >
                    {t('settings.clearCookie')}
                  </button>
                )}
              </div>
            )}
          </div>

          {/* ── Pixiv Token ── */}
          <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
            <div className="flex items-center justify-between">
              <div className="flex-1">
                <SectionHeader
                  title={t('settings.pixivToken')}
                  sectionKey="pixiv"
                  activeSection={activeSection}
                  onToggle={toggleSection}
                />
              </div>
              {!credLoading && credentials && (
                <div className="pr-5">
                  <StatusIndicator configured={credentials.pixiv?.configured ?? false} />
                </div>
              )}
            </div>

            {activeSection === 'pixiv' && (
              <div className="px-5 pb-5 border-t border-vault-border">
                {/* Mode toggle */}
                <div className="flex mt-4 bg-vault-input border border-vault-border rounded overflow-hidden">
                  <button
                    onClick={() => setPixivLoginMode('oauth')}
                    className={`flex-1 px-3 py-2 text-sm transition-colors ${pixivLoginMode === 'oauth' ? 'bg-vault-accent text-white' : 'text-vault-text-muted hover:text-vault-text'}`}
                  >
                    Web Login
                  </button>
                  <button
                    onClick={() => setPixivLoginMode('cookie')}
                    className={`flex-1 px-3 py-2 text-sm transition-colors ${pixivLoginMode === 'cookie' ? 'bg-vault-accent text-white' : 'text-vault-text-muted hover:text-vault-text'}`}
                  >
                    Session Cookie (New)
                  </button>
                  <button
                    onClick={() => setPixivLoginMode('token')}
                    className={`flex-1 px-3 py-2 text-sm transition-colors ${pixivLoginMode === 'token' ? 'bg-vault-accent text-white' : 'text-vault-text-muted hover:text-vault-text'}`}
                  >
                    Refresh Token (Adv)
                  </button>
                </div>

                {pixivLoginMode === 'oauth' && (
                  <div className="mt-4 space-y-3">
                    <div className="bg-yellow-900/20 border border-yellow-700/30 rounded-lg p-3 text-xs text-yellow-300/90 space-y-1.5">
                      <p className="font-semibold">{t('settings.pixivOauthSteps')}</p>
                      <p>{t('settings.pixivOauthStep1')}</p>
                      <p>{t('settings.pixivOauthStep2')}</p>
                      <p>{t('settings.pixivOauthStep3')}</p>
                      <p className="text-yellow-400/70">
                        {t('settings.pixivOauthHint')}{' '}
                        <code className="bg-black/30 px-1 rounded">
                          https://app-api.pixiv.net/...?code=xxx
                        </code>
                      </p>
                      <p className="text-yellow-400/70">{t('settings.pixivOauthHint2')}</p>
                    </div>
                    <button onClick={handlePixivGetOauth} className={btnSecondary + ' w-full'}>
                      Open Pixiv Login Page
                    </button>
                    {pixivCodeVerifier && (
                      <div>
                        <p className="text-xs text-vault-text-muted mb-1">
                          {t('settings.pixivOauthStep4')}
                        </p>
                        <input
                          type="text"
                          value={pixivCallbackUrl}
                          onChange={(e) => setPixivCallbackUrl(e.target.value)}
                          placeholder={t('settings.pixivCallbackPlaceholder')}
                          className={inputClass}
                        />
                        <button
                          onClick={handlePixivExchange}
                          disabled={pixivSaving || !pixivCallbackUrl.trim()}
                          className={btnPrimary + ' mt-3'}
                        >
                          {pixivSaving ? t('settings.saving') : t('settings.verifyAndSave')}
                        </button>
                      </div>
                    )}
                  </div>
                )}

                {pixivLoginMode === 'cookie' && (
                  <div className="mt-4 space-y-3">
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
                        PHPSESSID (Session Cookie)
                      </label>
                      <input
                        type="password"
                        value={pixivCookie}
                        onChange={(e) => setPixivCookie(e.target.value)}
                        placeholder={t('settings.pixivTokenExample')}
                        className={inputClass}
                      />
                    </div>
                    <div>
                      <button
                        onClick={handlePixivCookieSave}
                        disabled={pixivSaving || !pixivCookie.trim()}
                        className={btnPrimary}
                      >
                        {pixivSaving ? t('settings.saving') : t('settings.verifyAndSave')}
                      </button>
                    </div>
                  </div>
                )}

                {pixivLoginMode === 'token' && (
                  <div className="mt-4">
                    <label className="block text-xs text-vault-text-muted mb-1">
                      {t('settings.pixivRefreshToken')}
                    </label>
                    <input
                      type="password"
                      value={pixivToken}
                      onChange={(e) => setPixivToken(e.target.value)}
                      placeholder={t('settings.enterPixivRefreshToken')}
                      className={inputClass}
                    />
                    <p className="text-xs text-vault-text-muted mt-1">{t('settings.pixivHint')}</p>
                    <div className="mt-4">
                      <button
                        onClick={handlePixivSave}
                        disabled={pixivSaving}
                        className={btnPrimary}
                      >
                        {pixivSaving ? t('settings.saving') : t('settings.saveToken')}
                      </button>
                    </div>
                  </div>
                )}

                {pixivUsername && (
                  <div className="mt-4 flex items-center gap-2 text-sm p-3 bg-vault-input border border-vault-border rounded-lg">
                    <span className="text-vault-text-muted">{t('settings.pixivAccount')}:</span>
                    <span className="text-vault-text-secondary">{pixivUsername}</span>
                  </div>
                )}

                {credentials?.pixiv?.configured && (
                  <button
                    onClick={handleClearPixiv}
                    className="mt-3 px-3 py-1.5 bg-red-600/20 border border-red-500/30 text-red-400 rounded text-sm hover:bg-red-600/30 transition-colors"
                  >
                    {t('settings.clearToken')}
                  </button>
                )}
              </div>
            )}
          </div>

          {/* ── Site Cookies (generic) ── */}
          <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
            <div className="flex items-center justify-between">
              <div className="flex-1">
                <SectionHeader
                  title={t('credentials.genericCookies')}
                  sectionKey="generic"
                  activeSection={activeSection}
                  onToggle={toggleSection}
                />
              </div>
              {genericSites.length > 0 && (
                <div className="pr-5">
                  <span className="text-xs text-vault-text-muted">
                    {genericSites.length}
                  </span>
                </div>
              )}
            </div>

            {activeSection === 'generic' && (
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
                    {/* Site name */}
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

                    {/* Suggested keys hint */}
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
                                  const lines = prev
                                    .split('\n')
                                    .filter((l) => l.trim())
                                  const alreadyHas = lines.some((l) =>
                                    l.startsWith(`${k}=`),
                                  )
                                  if (alreadyHas) return prev
                                  return prev
                                    ? `${prev}\n${k}=`
                                    : `${k}=`
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

                    {/* Cookies textarea */}
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
                        genericSaving ||
                        !genericSiteName.trim() ||
                        !genericCookiesText.trim()
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
        </div>
      </div>
  )
}
