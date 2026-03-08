'use client'

import { useState, useEffect, useCallback } from 'react'
import { ChevronUp, ChevronDown, Eye, EyeOff, RefreshCw, Shield, Monitor } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { t } from '@/lib/i18n'
import { Copy, Key, BookOpen } from 'lucide-react'
import { loadReaderSettings, saveReaderSettings } from '@/components/Reader/hooks'
import type { ViewMode, ScaleMode, ReadingDirection } from '@/components/Reader/types'
import type {
  SystemHealth,
  SystemInfo,
  EhAccount,
  Credentials,
  SessionInfo,
  ApiTokenInfo,
} from '@/lib/types'

type SectionKey = 'ehentai' | 'pixiv' | 'system' | 'account' | 'browse' | 'apiTokens' | 'reader'

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

// ── Browse Settings sub-component ────────────────────────────────────

function BrowseSettings({ onForceRerender }: { onForceRerender: () => void }) {
  const historyEnabled =
    typeof window !== 'undefined' && localStorage.getItem('eh_search_history_enabled') !== 'false'
  const loadMode =
    typeof window !== 'undefined'
      ? localStorage.getItem('browse_load_mode') || 'pagination'
      : 'pagination'
  const perPage =
    typeof window !== 'undefined' ? localStorage.getItem('browse_per_page') || '25' : '25'

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
          <span
            className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform ${historyEnabled ? 'translate-x-5' : ''}`}
          />
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
            onClick={() => {
              localStorage.setItem('browse_load_mode', 'pagination')
              onForceRerender()
            }}
            className={`px-3 py-1.5 text-xs transition-colors ${loadMode === 'pagination' ? 'bg-vault-accent text-white' : 'text-vault-text-muted hover:text-vault-text'}`}
          >
            {t('settings.pagination')}
          </button>
          <button
            onClick={() => {
              localStorage.setItem('browse_load_mode', 'scroll')
              onForceRerender()
            }}
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
          onChange={(e) => {
            localStorage.setItem('browse_per_page', e.target.value)
            onForceRerender()
          }}
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

// ── Reader Settings helpers ───────────────────────────────────────────

function ReaderToggle({ value, onToggle }: { value: boolean; onToggle: () => void }) {
  return (
    <button
      onClick={onToggle}
      className={`relative w-11 h-6 rounded-full transition-colors shrink-0 ${value ? 'bg-vault-accent' : 'bg-vault-border'}`}
    >
      <span
        className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform ${value ? 'translate-x-5' : ''}`}
      />
    </button>
  )
}

function ReaderSettingRow({
  label,
  desc,
  children,
}: {
  label: string
  desc?: string
  children: React.ReactNode
}) {
  return (
    <div className="flex items-center justify-between py-1">
      <div>
        <p className="text-sm text-vault-text">{label}</p>
        {desc && <p className="text-xs text-vault-text-muted mt-0.5">{desc}</p>}
      </div>
      {children}
    </div>
  )
}

// ── Reader Settings sub-component ────────────────────────────────────

function ReaderSettingsSection({ onForceRerender }: { onForceRerender: () => void }) {
  const s = loadReaderSettings()

  const selectClass =
    'bg-vault-input border border-vault-border rounded px-3 py-2 text-vault-text focus:outline-none focus:border-vault-accent text-sm'

  return (
    <div className="px-5 pb-5 border-t border-vault-border space-y-4 mt-4">
      {/* Auto Advance */}
      <div>
        <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">
          {t('reader.autoAdvance')}
        </p>
        <div className="bg-vault-input border border-vault-border rounded-lg px-3 py-3 space-y-3">
          <ReaderSettingRow label={t('reader.autoAdvance')} desc={t('reader.autoAdvanceDesc')}>
            <ReaderToggle
              value={s.autoAdvanceEnabled}
              onToggle={() => {
                saveReaderSettings({ autoAdvanceEnabled: !s.autoAdvanceEnabled })
                onForceRerender()
              }}
            />
          </ReaderSettingRow>
          {s.autoAdvanceEnabled && (
            <ReaderSettingRow label={t('reader.autoAdvanceInterval')}>
              <div className="flex items-center gap-2">
                <input
                  type="range"
                  min={2}
                  max={30}
                  step={1}
                  value={s.autoAdvanceSeconds}
                  onChange={(e) => {
                    saveReaderSettings({ autoAdvanceSeconds: Number(e.target.value) })
                    onForceRerender()
                  }}
                  className="w-28 accent-vault-accent"
                />
                <span className="text-xs tabular-nums text-vault-text-secondary w-8 text-right">
                  {s.autoAdvanceSeconds}s
                </span>
              </div>
            </ReaderSettingRow>
          )}
        </div>
      </div>

      {/* Status Bar */}
      <div>
        <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">
          {t('reader.statusBar')}
        </p>
        <div className="bg-vault-input border border-vault-border rounded-lg px-3 py-3 space-y-3">
          <ReaderSettingRow label={t('reader.statusBar')} desc={t('reader.statusBarDesc')}>
            <ReaderToggle
              value={s.statusBarEnabled}
              onToggle={() => {
                saveReaderSettings({ statusBarEnabled: !s.statusBarEnabled })
                onForceRerender()
              }}
            />
          </ReaderSettingRow>
          {s.statusBarEnabled && (
            <>
              <ReaderSettingRow label={t('reader.statusBarClock')}>
                <ReaderToggle
                  value={s.statusBarShowClock}
                  onToggle={() => {
                    saveReaderSettings({ statusBarShowClock: !s.statusBarShowClock })
                    onForceRerender()
                  }}
                />
              </ReaderSettingRow>
              <ReaderSettingRow label={t('reader.statusBarProgress')}>
                <ReaderToggle
                  value={s.statusBarShowProgress}
                  onToggle={() => {
                    saveReaderSettings({ statusBarShowProgress: !s.statusBarShowProgress })
                    onForceRerender()
                  }}
                />
              </ReaderSettingRow>
              <ReaderSettingRow label={t('reader.statusBarPageCount')}>
                <ReaderToggle
                  value={s.statusBarShowPageCount}
                  onToggle={() => {
                    saveReaderSettings({ statusBarShowPageCount: !s.statusBarShowPageCount })
                    onForceRerender()
                  }}
                />
              </ReaderSettingRow>
            </>
          )}
        </div>
      </div>

      {/* Defaults */}
      <div>
        <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">Defaults</p>
        <div className="bg-vault-input border border-vault-border rounded-lg px-3 py-3 space-y-3">
          <ReaderSettingRow label={t('reader.defaultViewMode')}>
            <select
              value={s.defaultViewMode}
              onChange={(e) => {
                saveReaderSettings({ defaultViewMode: e.target.value as ViewMode })
                onForceRerender()
              }}
              className={selectClass}
            >
              <option value="single">{t('reader.viewModeSingle')}</option>
              <option value="webtoon">{t('reader.viewModeWebtoon')}</option>
              <option value="double">{t('reader.viewModeDouble')}</option>
            </select>
          </ReaderSettingRow>
          <ReaderSettingRow label={t('reader.defaultDirection')}>
            <select
              value={s.defaultReadingDirection}
              onChange={(e) => {
                saveReaderSettings({ defaultReadingDirection: e.target.value as ReadingDirection })
                onForceRerender()
              }}
              className={selectClass}
            >
              <option value="ltr">{t('reader.dirLtr')}</option>
              <option value="rtl">{t('reader.dirRtl')}</option>
              <option value="vertical">{t('reader.dirVertical')}</option>
            </select>
          </ReaderSettingRow>
          <ReaderSettingRow label={t('reader.defaultScaleMode')}>
            <select
              value={s.defaultScaleMode}
              onChange={(e) => {
                saveReaderSettings({ defaultScaleMode: e.target.value as ScaleMode })
                onForceRerender()
              }}
              className={selectClass}
            >
              <option value="fit-both">{t('reader.scaleFitBoth')}</option>
              <option value="fit-width">{t('reader.scaleFitWidth')}</option>
              <option value="fit-height">{t('reader.scaleFitHeight')}</option>
              <option value="original">{t('reader.scaleOriginal')}</option>
            </select>
          </ReaderSettingRow>
        </div>
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
  const [ehIgneous, setEhIgneous] = useState('')
  const [ehSaving, setEhSaving] = useState(false)
  const [showPassHash, setShowPassHash] = useState(false)
  const [ehAccount, setEhAccount] = useState<EhAccount | null>(null)
  const [ehAccountLoading, setEhAccountLoading] = useState(false)

  // Pixiv Token form
  const [pixivLoginMode, setPixivLoginMode] = useState<'oauth' | 'token'>('oauth')
  const [pixivToken, setPixivToken] = useState('')
  const [pixivSaving, setPixivSaving] = useState(false)
  const [pixivUsername, setPixivUsername] = useState<string | null>(null)
  const [pixivOauthUrl, setPixivOauthUrl] = useState('')
  const [pixivCodeVerifier, setPixivCodeVerifier] = useState('')
  const [pixivCallbackUrl, setPixivCallbackUrl] = useState('')

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

  // API Tokens
  const [apiTokens, setApiTokens] = useState<ApiTokenInfo[]>([])
  const [apiTokensLoaded, setApiTokensLoaded] = useState(false)
  const [apiTokensLoading, setApiTokensLoading] = useState(false)
  const [newTokenName, setNewTokenName] = useState('')
  const [newTokenExpiry, setNewTokenExpiry] = useState<string>('')
  const [tokenCreating, setTokenCreating] = useState(false)
  const [deletingTokenId, setDeletingTokenId] = useState<string | null>(null)

  // Load credentials on mount
  useEffect(() => {
    api.settings
      .getCredentials()
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
      setCredentials((prev) => (prev ? { ...prev, ehentai: { configured: true } } : prev))
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
      const data: { ipb_member_id: string; ipb_pass_hash: string; sk: string; igneous?: string } = {
        ipb_member_id: ehMemberId.trim(),
        ipb_pass_hash: ehPassHash.trim(),
        sk: ehSk.trim(),
      }
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
      const res = await api.settings.pixivOAuthCallback(pixivCallbackUrl.trim(), pixivCodeVerifier)
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

  // EH: Clear credential
  const handleClearEh = async () => {
    if (!confirm('確定要清除 E-Hentai Cookie？')) return
    try {
      await api.settings.deleteCredential('ehentai')
      toast.success('E-Hentai Cookie 已清除')
      setCredentials((prev) => (prev ? { ...prev, ehentai: { configured: false } } : prev))
      setEhAccount(null)
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '清除失敗')
    }
  }

  // Pixiv: Clear credential
  const handleClearPixiv = async () => {
    if (!confirm('確定要清除 Pixiv Token？')) return
    try {
      await api.settings.deleteCredential('pixiv')
      toast.success('Pixiv Token 已清除')
      setCredentials((prev) => (prev ? { ...prev, pixiv: { configured: false } } : prev))
      setPixivUsername(null)
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : '清除失敗')
    }
  }

  // System: Load health + info
  const handleLoadSystem = useCallback(async () => {
    setSystemLoading(true)
    try {
      const [h, i, rl] = await Promise.all([
        api.system.health(),
        api.system.info(),
        api.settings.getRateLimit(),
      ])
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

  const handleAvatarStyleChange = useCallback(
    async (style: 'gravatar' | 'manual') => {
      if (style === avatarStyle) return
      if (style === 'gravatar') {
        await handleAvatarRemove()
      } else {
        setAvatarStyle('manual')
      }
    },
    [avatarStyle, handleAvatarRemove],
  )

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
    if (!window.confirm('Are you sure you want to revoke this session?')) return
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

  // API Tokens: Load
  const handleLoadApiTokens = useCallback(async () => {
    setApiTokensLoading(true)
    try {
      const result = await api.tokens.list()
      setApiTokens(result.tokens)
      setApiTokensLoaded(true)
    } catch {
      toast.error(t('common.failedToLoad'))
      setApiTokensLoaded(true) // prevent retry loop on error
    } finally {
      setApiTokensLoading(false)
    }
  }, [])

  // API Tokens: Create
  const handleCreateToken = useCallback(async () => {
    if (!newTokenName.trim()) return
    setTokenCreating(true)
    try {
      const expDays = newTokenExpiry ? Number(newTokenExpiry) : undefined
      await api.tokens.create(newTokenName.trim(), expDays)
      toast.success('Token created')
      setNewTokenName('')
      setNewTokenExpiry('')
      handleLoadApiTokens()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to create token')
    } finally {
      setTokenCreating(false)
    }
  }, [newTokenName, newTokenExpiry, handleLoadApiTokens])

  // API Tokens: Delete
  const handleDeleteToken = useCallback(async (tokenId: string) => {
    if (!window.confirm('Are you sure you want to delete this API token?')) return
    setDeletingTokenId(tokenId)
    try {
      await api.tokens.delete(tokenId)
      setApiTokens((prev) => prev.filter((t) => t.id !== tokenId))
      toast.success('Token revoked')
    } catch {
      toast.error('Failed to revoke token')
    } finally {
      setDeletingTokenId(null)
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
    if (activeSection === 'apiTokens' && !apiTokensLoaded && !apiTokensLoading) {
      handleLoadApiTokens()
    }
  }, [
    activeSection,
    health,
    systemLoading,
    handleLoadSystem,
    profileLoaded,
    handleLoadProfile,
    sessions.length,
    sessionsLoading,
    handleLoadSessions,
    apiTokensLoaded,
    apiTokensLoading,
    handleLoadApiTokens,
  ])

  const serviceStatusClass = (status: string) =>
    status === 'ok' || status === 'healthy' ? 'text-green-400' : 'text-red-400'

  const inputClass =
    'w-full bg-vault-input border border-vault-border rounded px-3 py-2 text-vault-text placeholder-vault-text-muted focus:outline-none focus:border-vault-accent text-sm'
  const btnPrimary =
    'px-4 py-2 bg-vault-accent hover:bg-vault-accent/90 disabled:opacity-40 disabled:cursor-not-allowed rounded text-white text-sm font-medium transition-colors'
  const btnSecondary =
    'px-4 py-2 bg-vault-input border border-vault-border hover:border-vault-border-hover rounded text-vault-text-secondary text-sm transition-colors'

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
                      <label className="block text-xs text-vault-text-muted mb-1">
                        {t('settings.username')}
                      </label>
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
                      <label className="block text-xs text-vault-text-muted mb-1">
                        {t('settings.password')}
                      </label>
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
                      <button
                        onClick={handleEhLogin}
                        disabled={ehLoginSaving}
                        className={btnPrimary}
                      >
                        {ehLoginSaving ? t('settings.loggingIn') : t('settings.logIn')}
                      </button>
                      <button
                        onClick={handleEhRefresh}
                        disabled={ehAccountLoading}
                        className={btnSecondary}
                      >
                        {ehAccountLoading ? t('settings.refreshing') : t('settings.refreshAccount')}
                      </button>
                    </div>
                  </div>
                )}

                {/* Cookie login */}
                {ehLoginMode === 'cookie' && (
                  <div className="mt-4 space-y-3">
                    <div>
                      <label className="block text-xs text-vault-text-muted mb-1">
                        ipb_member_id
                      </label>
                      <input
                        type="text"
                        value={ehMemberId}
                        onChange={(e) => setEhMemberId(e.target.value)}
                        placeholder="Enter ipb_member_id"
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
                    <div>
                      <label className="block text-xs text-vault-text-muted mb-1">
                        igneous{' '}
                        <span className="text-vault-text-muted">(optional, for ExHentai)</span>
                      </label>
                      <input
                        type="text"
                        value={ehIgneous}
                        onChange={(e) => setEhIgneous(e.target.value)}
                        placeholder="Enter igneous (enables ExHentai)"
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
                        {ehAccountLoading ? t('settings.refreshing') : t('settings.refreshAccount')}
                      </button>
                    </div>
                  </div>
                )}

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
                    清除 Cookie
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
                  <StatusIndicator configured={credentials.pixiv.configured} />
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
                    Web Login (Recommended)
                  </button>
                  <button
                    onClick={() => setPixivLoginMode('token')}
                    className={`flex-1 px-3 py-2 text-sm transition-colors ${pixivLoginMode === 'token' ? 'bg-vault-accent text-white' : 'text-vault-text-muted hover:text-vault-text'}`}
                  >
                    Refresh Token (Advanced)
                  </button>
                </div>

                {pixivLoginMode === 'oauth' && (
                  <div className="mt-4 space-y-3">
                    <div className="bg-yellow-900/20 border border-yellow-700/30 rounded-lg p-3 text-xs text-yellow-300/90 space-y-1.5">
                      <p className="font-semibold">操作步驟：</p>
                      <p>1. 點擊下方按鈕，會開啟 Pixiv 登入頁面</p>
                      <p>2. 正常登入你的 Pixiv 帳號</p>
                      <p>3. 登入成功後，頁面會跳轉。<strong>在跳轉的瞬間，快速複製網址列中的 URL</strong></p>
                      <p className="text-yellow-400/70">提示：URL 格式為 <code className="bg-black/30 px-1 rounded">https://app-api.pixiv.net/...?code=xxx</code></p>
                      <p className="text-yellow-400/70">如果來不及複製，可以按 F12 開啟開發者工具 → Network 分頁，找到 callback 請求複製 URL</p>
                    </div>
                    <button
                      onClick={handlePixivGetOauth}
                      className={btnSecondary + ' w-full'}
                    >
                      Open Pixiv Login Page
                    </button>
                    {pixivCodeVerifier && (
                      <div>
                        <p className="text-xs text-vault-text-muted mb-1">
                          4. 將複製的 URL 或 <code>code=</code> 後面的值貼到這裡：
                        </p>
                        <input
                          type="text"
                          value={pixivCallbackUrl}
                          onChange={(e) => setPixivCallbackUrl(e.target.value)}
                          placeholder="https://app-api.pixiv.net/...?code=... 或直接貼 code 值"
                          className={inputClass}
                        />
                        <button
                          onClick={handlePixivExchange}
                          disabled={pixivSaving || !pixivCallbackUrl.trim()}
                          className={btnPrimary + ' mt-3'}
                        >
                          {pixivSaving ? t('settings.saving') : 'Verify & Save Token'}
                        </button>
                      </div>
                    )}
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
                      placeholder="Enter Pixiv refresh token"
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
                    清除 Token
                  </button>
                )}
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

                    {/* Info */}
                    <div>
                      <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">
                        {t('settings.configuration')}
                      </p>
                      <div className="bg-vault-input border border-vault-border rounded-lg divide-y divide-vault-border">
                        {[
                          { label: t('settings.version'), value: systemInfo.version },
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

                    {/* Rate Limiting */}
                    <div>
                      <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">
                        {t('settings.security')}
                      </p>
                      <div className="bg-vault-input border border-vault-border rounded-lg px-3 py-2">
                        <div className="flex items-center justify-between">
                          <div>
                            <p className="text-sm text-vault-text">{t('settings.rateLimiting')}</p>
                            <p className="text-xs text-vault-text-muted mt-0.5">
                              {t('settings.rateLimitDesc')}
                            </p>
                          </div>
                          <button
                            onClick={handleToggleRateLimit}
                            disabled={rateLimitToggling || rateLimitEnabled === null}
                            className={`relative w-11 h-6 rounded-full transition-colors ${rateLimitEnabled ? 'bg-vault-accent' : 'bg-vault-border'}`}
                          >
                            <span
                              className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform ${rateLimitEnabled ? 'translate-x-5' : ''}`}
                            />
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
              <BrowseSettings
                onForceRerender={() => {
                  setActiveSection(null)
                  setTimeout(() => setActiveSection('browse'), 0)
                }}
              />
            )}
          </div>

          {/* ── Reader Settings ── */}
          <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
            <div className="flex items-center justify-between">
              <div className="flex-1">
                <SectionHeader
                  title={t('settings.reader')}
                  sectionKey="reader"
                  activeSection={activeSection}
                  onToggle={toggleSection}
                />
              </div>
              <div className="pr-5">
                <BookOpen size={14} className="text-vault-text-muted" />
              </div>
            </div>
            {activeSection === 'reader' && (
              <ReaderSettingsSection
                onForceRerender={() => {
                  setActiveSection(null)
                  setTimeout(() => setActiveSection('reader'), 0)
                }}
              />
            )}
          </div>

          {/* ── API Tokens ── */}
          <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
            <div className="flex items-center justify-between">
              <div className="flex-1">
                <SectionHeader
                  title="API Tokens"
                  sectionKey="apiTokens"
                  activeSection={activeSection}
                  onToggle={toggleSection}
                />
              </div>
              <div className="pr-5">
                <span className="inline-flex items-center gap-1 text-xs text-vault-text-muted">
                  <Key size={12} />
                  {apiTokens.length > 0
                    ? `${apiTokens.length} token${apiTokens.length > 1 ? 's' : ''}`
                    : ''}
                </span>
              </div>
            </div>

            {activeSection === 'apiTokens' && (
              <div className="px-5 pb-5 border-t border-vault-border">
                {/* Create new token */}
                <div className="mt-4">
                  <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">
                    Create new token
                  </p>
                  <div className="space-y-3">
                    <div>
                      <label className="block text-xs text-vault-text-muted mb-1">Name</label>
                      <input
                        type="text"
                        value={newTokenName}
                        onChange={(e) => setNewTokenName(e.target.value)}
                        placeholder="e.g. Homepage widget, CI/CD"
                        onKeyDown={(e) => e.key === 'Enter' && handleCreateToken()}
                        className={inputClass}
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-vault-text-muted mb-1">
                        Expires in (days)
                      </label>
                      <select
                        value={newTokenExpiry}
                        onChange={(e) => setNewTokenExpiry(e.target.value)}
                        className={inputClass}
                      >
                        <option value="">Never</option>
                        <option value="7">7 days</option>
                        <option value="30">30 days</option>
                        <option value="90">90 days</option>
                        <option value="365">1 year</option>
                      </select>
                    </div>
                    <button
                      onClick={handleCreateToken}
                      disabled={tokenCreating || !newTokenName.trim()}
                      className={btnPrimary}
                    >
                      {tokenCreating ? 'Creating...' : 'Create Token'}
                    </button>
                  </div>
                </div>

                {/* Token list */}
                <div className="mt-5 pt-4 border-t border-vault-border">
                  <div className="flex items-center justify-between mb-2">
                    <p className="text-xs text-vault-text-muted uppercase tracking-wide">
                      Active tokens
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
                    <p className="text-xs text-vault-text-muted py-3">No API tokens created yet.</p>
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
                                    {tk.name || 'Unnamed'}
                                  </span>
                                  {isExpired && (
                                    <span className="text-[10px] bg-red-900/40 text-red-400 px-1.5 py-0.5 rounded">
                                      Expired
                                    </span>
                                  )}
                                </div>
                                {/* Token value — always visible */}
                                {tk.token && (
                                  <div className="flex items-center gap-1.5 mt-1.5">
                                    <code className="flex-1 text-xs text-vault-text-secondary bg-black/20 rounded px-2 py-1 font-mono break-all select-all">
                                      {tk.token}
                                    </code>
                                    <button
                                      onClick={() => {
                                        navigator.clipboard.writeText(tk.token)
                                        toast.success('Copied')
                                      }}
                                      className="px-1.5 py-1 text-vault-text-muted hover:text-vault-text transition-colors shrink-0"
                                      title="Copy"
                                    >
                                      <Copy size={12} />
                                    </button>
                                  </div>
                                )}
                                <div className="flex flex-wrap items-center gap-3 mt-1 text-xs text-vault-text-muted">
                                  {tk.created_at && (
                                    <span>
                                      Created {new Date(tk.created_at).toLocaleDateString()}
                                    </span>
                                  )}
                                  {tk.last_used_at ? (
                                    <span>
                                      Last used {new Date(tk.last_used_at).toLocaleDateString()}
                                    </span>
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

                {/* API usage info */}
                <div className="mt-5 pt-4 border-t border-vault-border">
                  <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">
                    Usage
                  </p>
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
                        <span className="text-green-400">GET</span>{' '}
                        /api/external/v1/galleries/:id/images
                      </p>
                      <p>
                        <span className="text-green-400">GET</span> /api/external/v1/tags
                      </p>
                      <p>
                        <span className="text-blue-400">POST</span>{' '}
                        /api/external/v1/download?url=...
                      </p>
                    </div>
                  </div>
                </div>
              </div>
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
                    <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-3">
                      {t('settings.avatar')}
                    </p>
                    <div className="flex items-start gap-4">
                      {}
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
                          <p className="text-xs text-vault-text-muted">
                            {t('settings.avatarGravatarDesc')}
                          </p>
                        ) : (
                          <div className="space-y-2">
                            <div className="flex gap-2">
                              <label
                                className={`${btnSecondary} cursor-pointer inline-flex items-center`}
                              >
                                {avatarUploading
                                  ? t('settings.avatarUploading')
                                  : t('settings.avatarUpload')}
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
                            <p className="text-xs text-vault-text-muted">
                              {t('settings.avatarMaxSize')}
                            </p>
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                )}

                {/* Profile */}
                {profileLoaded && (
                  <div className="mt-4">
                    <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">
                      {t('settings.profile')}
                    </p>
                    <div className="space-y-3">
                      <div>
                        <label className="block text-xs text-vault-text-muted mb-1">
                          {t('settings.username')}
                        </label>
                        <input
                          type="text"
                          value={profileUsername}
                          disabled
                          className={`${inputClass} opacity-60 cursor-not-allowed`}
                        />
                      </div>
                      <div>
                        <label className="block text-xs text-vault-text-muted mb-1">
                          {t('settings.email')}
                        </label>
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
                  <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">
                    {t('settings.changePassword')}
                  </p>
                  <div className="space-y-3">
                    <div>
                      <label className="block text-xs text-vault-text-muted mb-1">
                        {t('settings.currentPassword')}
                      </label>
                      <input
                        type="password"
                        value={currentPw}
                        onChange={(e) => setCurrentPw(e.target.value)}
                        autoComplete="current-password"
                        className={inputClass}
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-vault-text-muted mb-1">
                        {t('settings.newPassword')}
                      </label>
                      <input
                        type="password"
                        value={newPw}
                        onChange={(e) => setNewPw(e.target.value)}
                        autoComplete="new-password"
                        className={inputClass}
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-vault-text-muted mb-1">
                        {t('settings.confirmNewPassword')}
                      </label>
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
                    <p className="text-xs text-vault-text-muted uppercase tracking-wide">
                      {t('settings.activeSessions')}
                    </p>
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
                                <span className="text-sm text-vault-text font-mono">
                                  {s.token_prefix}...
                                </span>
                                {s.is_current && (
                                  <span className="text-[10px] bg-vault-accent/30 text-vault-accent px-1.5 py-0.5 rounded">
                                    {t('settings.current')}
                                  </span>
                                )}
                              </div>
                              <p
                                className="text-xs text-vault-text-muted mt-1 truncate"
                                title={s.user_agent}
                              >
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
                                  {t('settings.expiresIn')} {Math.ceil(s.ttl / 86400)}
                                  {t('settings.days')}
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
                        <p className="text-xs text-vault-text-muted py-2">
                          {t('settings.noSessions')}
                        </p>
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
