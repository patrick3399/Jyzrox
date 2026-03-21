'use client'

import { useState, useCallback, useEffect } from 'react'
import { useLocale } from '@/components/LocaleProvider'
import { BackButton } from '@/components/BackButton'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { inputClass, btnPrimary, btnSecondary } from '@/components/settings/SettingsShared'
import { t } from '@/lib/i18n'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import type { SessionInfo } from '@/lib/types'

export default function AccountSettingsPage() {
  useLocale()

  const { logout } = useAuth()

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
    if (!window.confirm(t('settings.confirmRevokeSession'))) return
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
    handleLoadProfile()
    handleLoadSessions()
  }, [handleLoadProfile, handleLoadSessions])

  return (
    <div className="max-w-2xl">
      <BackButton fallback="/settings" />
      <h1 className="text-2xl font-bold mb-6 text-vault-text">{t('settingsCategory.account')}</h1>

      <div className="space-y-6">
        {/* Avatar */}
        {profileLoaded && (
          <div className="bg-vault-card border border-vault-border rounded-xl px-5 py-5">
            <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-3">
              {t('settings.avatar')}
            </p>
            <div className="flex items-start gap-4">
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
                      <label className={`${btnSecondary} cursor-pointer inline-flex items-center`}>
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
                    <p className="text-xs text-vault-text-muted">{t('settings.avatarMaxSize')}</p>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* Profile */}
        {profileLoaded && (
          <div className="bg-vault-card border border-vault-border rounded-xl px-5 py-5">
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

        {!profileLoaded && (
          <div className="flex justify-center py-8">
            <LoadingSpinner />
          </div>
        )}

        {/* Change Password */}
        <div className="bg-vault-card border border-vault-border rounded-xl px-5 py-5">
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
        <div className="bg-vault-card border border-vault-border rounded-xl px-5 py-5">
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
                <p className="text-xs text-vault-text-muted py-2">{t('settings.noSessions')}</p>
              )}
            </div>
          )}
        </div>

        {/* Logout */}
        <div className="pb-4">
          <button
            onClick={logout}
            className="px-4 py-2 bg-red-900/40 border border-red-700/50 hover:bg-red-900/60 text-red-400 rounded text-sm font-medium transition-colors"
          >
            {t('settings.logOut')}
          </button>
        </div>
      </div>
    </div>
  )
}
