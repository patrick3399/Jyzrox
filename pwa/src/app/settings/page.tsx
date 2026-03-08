'use client'

import { useState, useEffect, useCallback } from 'react'
import { ChevronUp, ChevronDown, Eye, EyeOff, RefreshCw, Shield, Monitor } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { t } from '@/lib/i18n'
import type { SystemHealth, SystemInfo, EhAccount, Credentials, SessionInfo } from '@/lib/types'

type SectionKey = 'ehentai' | 'pixiv' | 'system' | 'account' | 'browse'

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
      {isOpen ? <ChevronUp size={16} className="text-vault-text-muted" /> : <ChevronDown size={16} className="text-vault-text-muted" />}
    </button>
  )
}

function StatusIndicator({ configured }: { configured: boolean }) {
  return (
    <span className={`inline-flex items-center gap-1 text-xs ${configured ? 'text-green-500' : 'text-vault-text-muted'}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${configured ? 'bg-green-500' : 'bg-vault-text-muted'}`} />
      {configured ? t('settings.configured') : t('settings.notConfigured')}
    </span>
  )
}

// ── Browse Settings sub-component ────────────────────────────────────

function BrowseSettings({ onForceRerender }: { onForceRerender: () => void }) {
  const historyEnabled = typeof window !== 'undefined' && localStorage.getItem('eh_search_history_enabled') !== 'false'
  const loadMode = typeof window !== 'undefined' ? (localStorage.getItem('browse_load_mode') || 'pagination') : 'pagination'
  const perPage = typeof window !== 'undefined' ? (localStorage.getItem('browse_per_page') || '25') : '25'

  return (
    <div className="px-5 pb-5 border-t border-vault-border">
      {/* Search History toggle */}
      <div className="mt-4 flex items-center justify-between">
        <div>
          <p className="text-sm text-vault-text">{t('settings.searchHistory')}</p>
          <p className="text-xs text-vault-text-muted mt-0.5">{t('settings.searchHistoryDesc')}</p>
        </div>
        <button
          onClick={() => {
            const next = localStorage.getItem('eh_search_history_enabled') === 'false'
            localStorage.setItem('eh_search_history_enabled', next ? 'true' : 'false')
            if (!next) localStorage.removeItem('eh_search_history')
            onForceRerender()
          }}
          className={`relative w-11 h-6 rounded-full transition-colors ${historyEnabled ? 'bg-vault-accent' : 'bg-vault-border'}`}
        >
          <span className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform ${historyEnabled ? 'translate-x-5' : ''}`} />
        </button>
      </div>

      {/* Load mode: Pagination vs Infinite Scroll */}
      <div className="mt-5 flex items-center justify-between">
        <div>
          <p className="text-sm text-vault-text">{t('settings.loadMode')}</p>
          <p className="text-xs text-vault-text-muted mt-0.5">{t('settings.loadModeDesc')}</p>
        </div>
        <div className="flex bg-vault-input border border-vault-border rounded overflow-hidden">
          <button
            onClick={() => { localStorage.setItem('browse_load_mode', 'pagination'); onForceRerender() }}
            className={`px-3 py-1.5 text-xs transition-colors ${loadMode === 'pagination' ? 'bg-vault-accent text-white' : 'text-vault-text-muted hover:text-vault-text'}`}
          >
            {t('settings.pagination')}
          </button>
          <button
            onClick={() => { localStorage.setItem('browse_load_mode', 'scroll'); onForceRerender() }}
            className={`px-3 py-1.5 text-xs transition-colors ${loadMode === 'scroll' ? 'bg-vault-accent text-white' : 'text-vault-text-muted hover:text-vault-text'}`}
          >
            {t('settings.infiniteScroll')}
          </button>
        </div>
      </div>

      {/* Per page (library) */}
      <div className="mt-5 flex items-center justify-between">
        <div>
          <p className="text-sm text-vault-text">{t('settings.perPage')}</p>
          <p className="text-xs text-vault-text-muted mt-0.5">{t('settings.perPageDesc')}</p>
        </div>
        <select
          value={perPage}
          onChange={(e) => { localStorage.setItem('browse_per_page', e.target.value); onForceRerender() }}
          className="bg-vault-input border border-vault-border rounded px-3 py-1.5 text-sm text-vault-text focus:outline-none"
        >
          <option value="25">25</option>
          <option value="50">50</option>
          <option value="100">100</option>
        </select>
      </div>
    </div>
  )
}

export default function SettingsPage() {
  const { logout } = useAuth()
  const [activeSection, setActiveSection] = useState<SectionKey | null>('ehentai')

  // Credentials state
  const [credentials, setCredentials] = useState<Credentials | null>(null)
  const [credLoading, setCredLoading] = useState(true)

  // EH login mode
  const [ehLoginMode, setEhLoginMode] = useState<'password' | 'cookie'>('password')

  // EH password login
  const [ehUsername, setEhUsername] = useState('')
  const [ehPassword, setEhPassword] = useState('')
  const [ehLoginSaving, setEhLoginSaving] = useState(false)

  // EH Cookie form
  const [ehMemberId, setEhMemberId] = useState('')
  const [ehPassHash, setEhPassHash] = useState('')
  const [ehSk, setEhSk] = useState('')
  const [ehSaving, setEhSaving] = useState(false)
  const [showPassHash, setShowPassHash] = useState(false)
  const [ehAccount, setEhAccount] = useState<EhAccount | null>(null)
  const [ehAccountLoading, setEhAccountLoading] = useState(false)

  // Pixiv Token form
  const [pixivToken, setPixivToken] = useState('')
  const [pixivSaving, setPixivSaving] = useState(false)
  const [pixivUsername, setPixivUsername] = useState<string | null>(null)

  // System info
  const [health, setHealth] = useState<SystemHealth | null>(null)
  const [systemInfo, setSystemInfo] = useState<SystemInfo | null>(null)
  const [systemLoading, setSystemLoading] = useState(false)

  // Rate limiting
  const [rateLimitEnabled, setRateLimitEnabled] = useState<boolean | null>(null)
  const [rateLimitToggling, setRateLimitToggling] = useState(false)

  // Profile
  const [profileUsername, setProfileUsername] = useState('')
  const [profileEmail, setProfileEmail] = useState('')
  const [profileEmailDraft, setProfileEmailDraft] = useState('')
  const [profileLoaded, setProfileLoaded] = useState(false)
  const [emailSaving, setEmailSaving] = useState(false)

  // Avatar
  const [avatarStyle, setAvatarStyle] = useState<'gravatar' | 'manual'>('gravatar')
  const [avatarUrl, setAvatarUrl] = useState('')
  const [avatarUploading, setAvatarUploading] = useState(false)

  // Change password
  const [currentPw, setCurrentPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [pwSaving, setPwSaving] = useState(false)

  // Sessions
  const [sessions, setSessions] = useState<SessionInfo[]>([])
  const [sessionsLoading, setSessionsLoading] = useState(false)
  const [revokingToken, setRevokingToken] = useState<string | null>(null)

  // Load credentials on mount
  useEffect(() => {
    api.settings.getCredentials()
      .then(setCredentials)
      .catch((err) => toast.error(err instanceof Error ? err.message : t('common.failedToLoad')))
      .finally(() => setCredLoading(false))
  }, [])

  const toggleSection = useCallback((key: SectionKey) => {
    setActiveSection((prev) => (prev === key ? null : key))
  }, [])

  // EH: Login with username/password
  const handleEhLogin = useCallback(async () => {
    if (!ehUsername.trim() || !ehPassword.trim()) return
    setEhLoginSaving(true)
    try {
      const result = await api.settings.ehLogin(ehUsername.trim(), ehPassword.trim())
      toast.success(t('settings.ehLoginSuccess'))
      setEhAccount(result.account)
      setCredentials((prev) => prev ? { ...prev, ehentai: { configured: true } } : prev)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.ehLoginFailed'))
    } finally {
      setEhLoginSaving(false)
    }
  }, [ehUsername, ehPassword])

  // EH: Save cookies
  const handleEhSave = useCallback(async () => {
    if (!ehMemberId.trim() || !ehPassHash.trim() || !ehSk.trim()) return
    setEhSaving(true)
    try {
      const result = await api.settings.setEhCookies({
        ipb_member_id: ehMemberId.trim(),
        ipb_pass_hash: ehPassHash.trim(),
        sk: ehSk.trim(),
      })
      toast.success(t('settings.ehCookiesSaved'))
      setEhAccount(result.account)
      setCredentials((prev) => prev ? { ...prev, ehentai: { configured: true } } : prev)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.ehCookiesFailed'))
    } finally {
      setEhSaving(false)
    }
  }, [ehMemberId, ehPassHash, ehSk])

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

  // Pixiv: Save token
  const handlePixivSave = useCallback(async () => {
    if (!pixivToken.trim()) return
    setPixivSaving(true)
    try {
      const result = await api.settings.setPixivToken(pixivToken.trim())
      toast.success(`${t('settings.pixivSaved')}: ${result.username}`)
      setPixivUsername(result.username)
      setCredentials((prev) => prev ? { ...prev, pixiv: { configured: true } } : prev)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.pixivFailed'))
    } finally {
      setPixivSaving(false)
    }
  }, [pixivToken])

  // System: Load health + info
  const handleLoadSystem = useCallback(async () => {
    setSystemLoading(true)
    try {
      const [h, i, rl] = await Promise.all([api.system.health(), api.system.info(), api.settings.getRateLimit()])
      setHealth(h)
      setSystemInfo(i)
      setRateLimitEnabled(rl.enabled)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.systemLoadFailed'))
    } finally {
      setSystemLoading(false)
    }
  }, [])

  const handleToggleRateLimit = useCallback(async () => {
    if (rateLimitEnabled === null) return
    setRateLimitToggling(true)
    try {
      const result = await api.settings.setRateLimit(!rateLimitEnabled)
      setRateLimitEnabled(result.enabled)
    } catch {
      toast.error(t('common.failedToLoad'))
    } finally {
      setRateLimitToggling(false)
    }
  }, [rateLimitEnabled])

  const handleLoadProfile = useCallback(async () => {
    try {
      const p = await api.auth.getProfile()
      setProfileUsername(p.username)
      setProfileEmail(p.email ?? '')
      setProfileEmailDraft(p.email ?? '')
      setAvatarStyle(p.avatar_style as 'gravatar' | 'manual')
      setAvatarUrl(p.avatar_url)
      setProfileLoaded(true)
    } catch {
      toast.error(t('common.failedToLoad'))
    }
  }, [])

  const handleSaveEmail = useCallback(async () => {
    setEmailSaving(true)
    try {
      await api.auth.updateProfile({ email: profileEmailDraft.trim() || null })
      setProfileEmail(profileEmailDraft.trim())
      toast.success(t('settings.emailSaved'))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.emailFailed'))
    } finally {
      setEmailSaving(false)
    }
  }, [profileEmailDraft])

  const handleAvatarUpload = useCallback(async (file: File) => {
    setAvatarUploading(true)
    try {
      const result = await api.auth.uploadAvatar(file)
      setAvatarStyle('manual')
      setAvatarUrl(`${result.avatar_url}?t=${Date.now()}`)
      toast.success(t('settings.avatarUploaded'))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.avatarUploadFailed'))
    } finally {
      setAvatarUploading(false)
    }
  }, [])

  const handleAvatarRemove = useCallback(async () => {
    try {
      const result = await api.auth.deleteAvatar()
      setAvatarStyle('gravatar')
      setAvatarUrl(result.avatar_url)
      toast.success(t('settings.avatarRemoved'))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.avatarUploadFailed'))
    }
  }, [])

  const handleAvatarStyleChange = useCallback(async (style: 'gravatar' | 'manual') => {
    if (style === avatarStyle) return
    if (style === 'gravatar') {
      await handleAvatarRemove()
    } else {
      setAvatarStyle('manual')
    }
  }, [avatarStyle, handleAvatarRemove])

  const handleChangePassword = useCallback(async () => {
    if (newPw !== confirmPw) {
      toast.error(t('settings.passwordMismatch'))
      return
    }
    if (newPw.length < 8) {
      toast.error(t('settings.passwordTooShort'))
      return
    }
    setPwSaving(true)
    try {
      await api.auth.changePassword(currentPw, newPw)
      toast.success(t('settings.passwordChanged'))
      setCurrentPw('')
      setNewPw('')
      setConfirmPw('')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.passwordChangeFailed'))
    } finally {
      setPwSaving(false)
    }
  }, [currentPw, newPw, confirmPw])

  const handleLoadSessions = useCallback(async () => {
    setSessionsLoading(true)
    try {
      const result = await api.auth.getSessions()
      setSessions(result.sessions)
    } catch {
      toast.error(t('common.failedToLoad'))
    } finally {
      setSessionsLoading(false)
    }
  }, [])

  const handleRevokeSession = useCallback(async (tokenPrefix: string) => {
    setRevokingToken(tokenPrefix)
    try {
      await api.auth.revokeSession(tokenPrefix)
      setSessions((prev) => prev.filter((s) => s.token_prefix !== tokenPrefix))
      toast.success(t('settings.sessionRevoked'))
    } catch {
      toast.error(t('common.failedToLoad'))
    } finally {
      setRevokingToken(null)
    }
  }, [])

  useEffect(() => {
    if (activeSection === 'system' && !health && !systemLoading) {
      handleLoadSystem()
    }
    if (activeSection === 'account') {
      if (!profileLoaded) handleLoadProfile()
      if (sessions.length === 0 && !sessionsLoading) handleLoadSessions()
    }
  }, [activeSection, health, systemLoading, handleLoadSystem, profileLoaded, handleLoadProfile, sessions.length, sessionsLoading, handleLoadSessions])

  const serviceStatusClass = (status: string) =>
    status === 'ok' || status === 'healthy'
      ? 'text-green-400'
      : 'text-red-400'

  const inputClass = 'w-full bg-vault-input border border-vault-border rounded px-3 py-2 text-vault-text placeholder-vault-text-muted focus:outline-none focus:border-vault-accent text-sm'
  const btnPrimary = 'px-4 py-2 bg-vault-accent hover:bg-vault-accent/90 disabled:opacity-40 disabled:cursor-not-allowed rounded text-white text-sm font-medium transition-colors'
  const btnSecondary = 'px-4 py-2 bg-vault-input border border-vault-border hover:border-vault-border-hover rounded text-vault-text-secondary text-sm transition-colors'

  return (
    <div className="min-h-screen bg-vault-bg text-vault-text">
      <div className="max-w-2xl mx-auto px-4 py-6">
        <h1 className="text-2xl font-bold mb-6 text-vault-text">{t('settings.title')}</h1>

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
                  <StatusIndicator configured={credentials.ehentai.configured} />
                </div>
              )}
            </div>

            {activeSection === 'ehentai' && (
              <div className="px-5 pb-5 border-t border-vault-border">
                {/* Mode toggle */}
                <div className="flex mt-4 bg-vault-input border border-vault-border rounded overflow-hidden">
                  <button
                    onClick={() => setEhLoginMode('password')}
                    className={`flex-1 px-3 py-2 text-sm transition-colors ${ehLoginMode === 'password' ? 'bg-vault-accent text-white' : 'text-vault-text-muted hover:text-vault-text'}`}
                  >
                    {t('settings.usernamePassword')}
                  </button>
                  <button
                    onClick={() => setEhLoginMode('cookie')}
                    className={`flex-1 px-3 py-2 text-sm transition-colors ${ehLoginMode === 'cookie' ? 'bg-vault-accent text-white' : 'text-vault-text-muted hover:text-vault-text'}`}
                  >
                    {t('settings.cookieAdvanced')}
                  </button>
                </div>

                {/* Password login */}
                {ehLoginMode === 'password' && (
                  <div className="mt-4 space-y-3">
                    <div>
                      <label className="block text-xs text-vault-text-muted mb-1">{t('settings.username')}</label>
                      <input
                        type="text"
                        value={ehUsername}
                        onChange={(e) => setEhUsername(e.target.value)}
                        placeholder="E-Hentai username"
                        autoComplete="username"
                        className={inputClass}
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-vault-text-muted mb-1">{t('settings.password')}</label>
                      <input
                        type="password"
                        value={ehPassword}
                        onChange={(e) => setEhPassword(e.target.value)}
                        placeholder="E-Hentai password"
                        autoComplete="current-password"
                        onKeyDown={(e) => e.key === 'Enter' && handleEhLogin()}
                        className={inputClass}
                      />
                    </div>
                    <div className="flex gap-2">
                      <button onClick={handleEhLogin} disabled={ehLoginSaving} className={btnPrimary}>
                        {ehLoginSaving ? t('settings.loggingIn') : t('settings.logIn')}
                      </button>
                      <button onClick={handleEhRefresh} disabled={ehAccountLoading} className={btnSecondary}>
                        {ehAccountLoading ? t('settings.refreshing') : t('settings.refreshAccount')}
                      </button>
                    </div>
                  </div>
                )}

                {/* Cookie login */}
                {ehLoginMode === 'cookie' && (
                  <div className="mt-4 space-y-3">
                    <div>
                      <label className="block text-xs text-vault-text-muted mb-1">ipb_member_id</label>
                      <input
                        type="text"
                        value={ehMemberId}
                        onChange={(e) => setEhMemberId(e.target.value)}
                        placeholder="Enter ipb_member_id"
                        className={inputClass}
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-vault-text-muted mb-1">ipb_pass_hash</label>
                      <div className="relative">
                        <input
                          type={showPassHash ? 'text' : 'password'}
                          value={ehPassHash}
                          onChange={(e) => setEhPassHash(e.target.value)}
                          placeholder="Enter ipb_pass_hash"
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
                      <label className="block text-xs text-vault-text-muted mb-1">sk</label>
                      <input
                        type="text"
                        value={ehSk}
                        onChange={(e) => setEhSk(e.target.value)}
                        placeholder="Enter sk"
                        className={inputClass}
                      />
                    </div>
                    <div className="flex gap-2">
                      <button onClick={handleEhSave} disabled={ehSaving} className={btnPrimary}>
                        {ehSaving ? t('settings.saving') : t('settings.saveCookies')}
                      </button>
                      <button onClick={handleEhRefresh} disabled={ehAccountLoading} className={btnSecondary}>
                        {ehAccountLoading ? t('settings.refreshing') : t('settings.refreshAccount')}
                      </button>
                    </div>
                  </div>
                )}

                {/* Account Info */}
                {ehAccount && (
                  <div className="mt-4 bg-vault-input border border-vault-border rounded-lg p-3">
                    <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">{t('settings.accountStatus')}</p>
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
                          <span className="text-vault-text-secondary">{ehAccount.credits.toLocaleString()}</span>
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
                  <StatusIndicator configured={credentials.pixiv.configured} />
                </div>
              )}
            </div>

            {activeSection === 'pixiv' && (
              <div className="px-5 pb-5 border-t border-vault-border">
                <div className="mt-4">
                  <label className="block text-xs text-vault-text-muted mb-1">{t('settings.pixivRefreshToken')}</label>
                  <input
                    type="password"
                    value={pixivToken}
                    onChange={(e) => setPixivToken(e.target.value)}
                    placeholder="Enter Pixiv refresh token"
                    className={inputClass}
                  />
                  <p className="text-xs text-vault-text-muted mt-1">
                    {t('settings.pixivHint')}
                  </p>
                </div>

                {pixivUsername && (
                  <div className="mt-3 flex items-center gap-2 text-sm">
                    <span className="text-vault-text-muted">{t('settings.pixivAccount')}:</span>
                    <span className="text-vault-text-secondary">{pixivUsername}</span>
                  </div>
                )}

                <div className="mt-4">
                  <button onClick={handlePixivSave} disabled={pixivSaving} className={btnPrimary}>
                    {pixivSaving ? t('settings.saving') : t('settings.saveToken')}
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* ── System Info ── */}
          <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
            <SectionHeader
              title={t('settings.system')}
              sectionKey="system"
              activeSection={activeSection}
              onToggle={toggleSection}
            />

            {activeSection === 'system' && (
              <div className="px-5 pb-5 border-t border-vault-border">
                {systemLoading && (
                  <div className="flex justify-center py-8">
                    <LoadingSpinner />
                  </div>
                )}
                {!systemLoading && health && systemInfo && (
                  <div className="mt-4 space-y-4">
                    {/* Health */}
                    <div>
                      <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">{t('settings.serviceHealth')}</p>
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

                    {/* Info */}
                    <div>
                      <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">{t('settings.configuration')}</p>
                      <div className="bg-vault-input border border-vault-border rounded-lg divide-y divide-vault-border">
                        {[
                          { label: t('settings.version'), value: systemInfo.version },
                          { label: t('settings.ehMaxConcurrency'), value: String(systemInfo.eh_max_concurrency) },
                          {
                            label: t('settings.aiTagging'),
                            value: systemInfo.tag_model_enabled ? t('settings.enabled') : t('settings.disabled'),
                            valueClass: systemInfo.tag_model_enabled ? 'text-green-400' : 'text-vault-text-muted',
                          },
                        ].map(({ label, value, valueClass }) => (
                          <div key={label} className="flex justify-between items-center px-3 py-2">
                            <span className="text-sm text-vault-text-muted">{label}</span>
                            <span className={`text-sm font-medium ${valueClass ?? 'text-vault-text-secondary'}`}>{value}</span>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Rate Limiting */}
                    <div>
                      <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">{t('settings.security')}</p>
                      <div className="bg-vault-input border border-vault-border rounded-lg px-3 py-2">
                        <div className="flex items-center justify-between">
                          <div>
                            <p className="text-sm text-vault-text">{t('settings.rateLimiting')}</p>
                            <p className="text-xs text-vault-text-muted mt-0.5">{t('settings.rateLimitDesc')}</p>
                          </div>
                          <button
                            onClick={handleToggleRateLimit}
                            disabled={rateLimitToggling || rateLimitEnabled === null}
                            className={`relative w-11 h-6 rounded-full transition-colors ${rateLimitEnabled ? 'bg-vault-accent' : 'bg-vault-border'}`}
                          >
                            <span className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform ${rateLimitEnabled ? 'translate-x-5' : ''}`} />
                          </button>
                        </div>
                      </div>
                    </div>

                    <button
                      onClick={handleLoadSystem}
                      className="text-xs text-vault-text-muted hover:text-vault-text-secondary transition-colors"
                    >
                      {t('settings.refresh')}
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* ── Browse Settings ── */}
          <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
            <SectionHeader
              title={t('settings.browse')}
              sectionKey="browse"
              activeSection={activeSection}
              onToggle={toggleSection}
            />
            {activeSection === 'browse' && (
              <BrowseSettings onForceRerender={() => {
                setActiveSection(null)
                setTimeout(() => setActiveSection('browse'), 0)
              }} />
            )}
          </div>

          {/* ── Account / Logout ── */}
          <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
            <SectionHeader
              title={t('settings.account')}
              sectionKey="account"
              activeSection={activeSection}
              onToggle={toggleSection}
            />
            {activeSection === 'account' && (
              <div className="px-5 pb-5 border-t border-vault-border">
                {/* Avatar */}
                {profileLoaded && (
                  <div className="mt-4">
                    <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-3">{t('settings.avatar')}</p>
                    <div className="flex items-start gap-4">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img
                        src={avatarUrl}
                        alt=""
                        className="w-16 h-16 rounded-full object-cover bg-vault-input shrink-0 border border-vault-border"
                      />
                      <div className="flex-1 space-y-3">
                        {/* Style toggle */}
                        <div className="flex bg-vault-input border border-vault-border rounded overflow-hidden">
                          <button
                            onClick={() => handleAvatarStyleChange('gravatar')}
                            className={`flex-1 px-3 py-1.5 text-xs transition-colors ${avatarStyle === 'gravatar' ? 'bg-vault-accent text-white' : 'text-vault-text-muted hover:text-vault-text'}`}
                          >
                            {t('settings.avatarGravatar')}
                          </button>
                          <button
                            onClick={() => handleAvatarStyleChange('manual')}
                            className={`flex-1 px-3 py-1.5 text-xs transition-colors ${avatarStyle === 'manual' ? 'bg-vault-accent text-white' : 'text-vault-text-muted hover:text-vault-text'}`}
                          >
                            {t('settings.avatarCustom')}
                          </button>
                        </div>

                        {avatarStyle === 'gravatar' ? (
                          <p className="text-xs text-vault-text-muted">{t('settings.avatarGravatarDesc')}</p>
                        ) : (
                          <div className="space-y-2">
                            <div className="flex gap-2">
                              <label className={`${btnSecondary} cursor-pointer inline-flex items-center`}>
                                {avatarUploading ? t('settings.avatarUploading') : t('settings.avatarUpload')}
                                <input
                                  type="file"
                                  accept="image/*"
                                  className="hidden"
                                  disabled={avatarUploading}
                                  onChange={(e) => {
                                    const f = e.target.files?.[0]
                                    if (f) handleAvatarUpload(f)
                                    e.target.value = ''
                                  }}
                                />
                              </label>
                              <button onClick={handleAvatarRemove} className={btnSecondary}>
                                {t('settings.avatarRemove')}
                              </button>
                            </div>
                            <p className="text-xs text-vault-text-muted">{t('settings.avatarMaxSize')}</p>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}

                {/* Profile */}
                {profileLoaded && (
                  <div className="mt-4">
                    <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">{t('settings.profile')}</p>
                    <div className="space-y-3">
                      <div>
                        <label className="block text-xs text-vault-text-muted mb-1">{t('settings.username')}</label>
                        <input
                          type="text"
                          value={profileUsername}
                          disabled
                          className={`${inputClass} opacity-60 cursor-not-allowed`}
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-vault-text-muted mb-1">{t('settings.email')}</label>
                        <div className="flex gap-2">
                          <input
                            type="email"
                            value={profileEmailDraft}
                            onChange={(e) => setProfileEmailDraft(e.target.value)}
                            placeholder={t('settings.emailPlaceholder')}
                            className={`${inputClass} flex-1`}
                          />
                          <button
                            onClick={handleSaveEmail}
                            disabled={emailSaving || profileEmailDraft === profileEmail}
                            className={btnPrimary}
                          >
                            {emailSaving ? t('settings.saving') : t('settings.save')}
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                )}

                {/* Change Password */}
                <div className="mt-5 pt-4 border-t border-vault-border">
                  <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">{t('settings.changePassword')}</p>
                  <div className="space-y-3">
                    <div>
                      <label className="block text-xs text-vault-text-muted mb-1">{t('settings.currentPassword')}</label>
                      <input
                        type="password"
                        value={currentPw}
                        onChange={(e) => setCurrentPw(e.target.value)}
                        autoComplete="current-password"
                        className={inputClass}
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-vault-text-muted mb-1">{t('settings.newPassword')}</label>
                      <input
                        type="password"
                        value={newPw}
                        onChange={(e) => setNewPw(e.target.value)}
                        autoComplete="new-password"
                        className={inputClass}
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-vault-text-muted mb-1">{t('settings.confirmNewPassword')}</label>
                      <input
                        type="password"
                        value={confirmPw}
                        onChange={(e) => setConfirmPw(e.target.value)}
                        autoComplete="new-password"
                        onKeyDown={(e) => e.key === 'Enter' && handleChangePassword()}
                        className={inputClass}
                      />
                    </div>
                    <button
                      onClick={handleChangePassword}
                      disabled={pwSaving || !currentPw || !newPw || !confirmPw}
                      className={btnPrimary}
                    >
                      {pwSaving ? t('settings.saving') : t('settings.update')}
                    </button>
                  </div>
                </div>

                {/* Active Sessions */}
                <div className="mt-5 pt-4 border-t border-vault-border">
                  <div className="flex items-center justify-between mb-2">
                    <p className="text-xs text-vault-text-muted uppercase tracking-wide">{t('settings.activeSessions')}</p>
                    <button
                      onClick={handleLoadSessions}
                      disabled={sessionsLoading}
                      className="text-xs text-vault-text-muted hover:text-vault-text-secondary transition-colors"
                    >
                      {sessionsLoading ? t('settings.loading') : t('settings.refresh')}
                    </button>
                  </div>

                  {sessionsLoading && sessions.length === 0 ? (
                    <div className="flex justify-center py-4">
                      <LoadingSpinner />
                    </div>
                  ) : (
                    <div className="space-y-2">
                      {sessions.map((s) => (
                        <div
                          key={s.token_prefix}
                          className={`bg-vault-input border rounded-lg px-3 py-2.5 ${
                            s.is_current ? 'border-vault-accent/50' : 'border-vault-border'
                          }`}
                        >
                          <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2">
                                <span className="text-sm text-vault-text font-mono">{s.token_prefix}...</span>
                                {s.is_current && (
                                  <span className="text-[10px] bg-vault-accent/30 text-vault-accent px-1.5 py-0.5 rounded">
                                    {t('settings.current')}
                                  </span>
                                )}
                              </div>
                              <p className="text-xs text-vault-text-muted mt-1 truncate" title={s.user_agent}>
                                {s.user_agent || t('settings.unknownDevice')}
                              </p>
                              <div className="flex items-center gap-3 mt-1">
                                <span className="text-xs text-vault-text-muted">{s.ip}</span>
                                {s.created_at && (
                                  <span className="text-xs text-vault-text-muted">
                                    {new Date(s.created_at).toLocaleDateString()}
                                  </span>
                                )}
                                <span className="text-xs text-vault-text-muted">
                                  {t('settings.expiresIn')} {Math.ceil(s.ttl / 86400)}{t('settings.days')}
                                </span>
                              </div>
                            </div>
                            {!s.is_current && (
                              <button
                                onClick={() => handleRevokeSession(s.token_prefix)}
                                disabled={revokingToken === s.token_prefix}
                                className="text-xs text-red-400/70 hover:text-red-400 transition-colors shrink-0 px-2 py-1"
                              >
                                {revokingToken === s.token_prefix ? '...' : t('settings.revoke')}
                              </button>
                            )}
                          </div>
                        </div>
                      ))}
                      {sessions.length === 0 && !sessionsLoading && (
                        <p className="text-xs text-vault-text-muted py-2">{t('settings.noSessions')}</p>
                      )}
                    </div>
                  )}
                </div>

                <div className="mt-5 pt-4 border-t border-vault-border">
                  <button
                    onClick={logout}
                    className="px-4 py-2 bg-red-900/40 border border-red-700/50 hover:bg-red-900/60 text-red-400 rounded text-sm font-medium transition-colors"
                  >
                    {t('settings.logOut')}
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
