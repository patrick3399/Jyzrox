'use client'

import { useState, useEffect, useCallback } from 'react'
import { api } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { AlertBanner } from '@/components/AlertBanner'
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
      className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-[#161616] transition-colors"
    >
      <span className="font-medium text-white text-sm">{title}</span>
      <span className="text-gray-500 text-sm">{isOpen ? '▲' : '▼'}</span>
    </button>
  )
}

function StatusIndicator({ configured }: { configured: boolean }) {
  return (
    <span className={`inline-flex items-center gap-1 text-xs ${configured ? 'text-green-400' : 'text-gray-600'}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${configured ? 'bg-green-400' : 'bg-gray-600'}`} />
      {configured ? 'Configured' : 'Not configured'}
    </span>
  )
}

// ── Browse Settings sub-component ────────────────────────────────────

function BrowseSettings({ onForceRerender }: { onForceRerender: () => void }) {
  const historyEnabled = typeof window !== 'undefined' && localStorage.getItem('eh_search_history_enabled') !== 'false'
  const loadMode = typeof window !== 'undefined' ? (localStorage.getItem('browse_load_mode') || 'pagination') : 'pagination'
  const perPage = typeof window !== 'undefined' ? (localStorage.getItem('browse_per_page') || '25') : '25'

  return (
    <div className="px-5 pb-5 border-t border-[#1e1e1e]">
      {/* Search History toggle */}
      <div className="mt-4 flex items-center justify-between">
        <div>
          <p className="text-sm text-white">Search History</p>
          <p className="text-xs text-gray-600 mt-0.5">Save recent searches (last 10)</p>
        </div>
        <button
          onClick={() => {
            const next = localStorage.getItem('eh_search_history_enabled') === 'false'
            localStorage.setItem('eh_search_history_enabled', next ? 'true' : 'false')
            if (!next) localStorage.removeItem('eh_search_history')
            onForceRerender()
          }}
          className={`relative w-11 h-6 rounded-full transition-colors ${historyEnabled ? 'bg-blue-600' : 'bg-[#333]'}`}
        >
          <span className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform ${historyEnabled ? 'translate-x-5' : ''}`} />
        </button>
      </div>

      {/* Load mode: Pagination vs Infinite Scroll */}
      <div className="mt-5 flex items-center justify-between">
        <div>
          <p className="text-sm text-white">Load Mode</p>
          <p className="text-xs text-gray-600 mt-0.5">Pagination or infinite scroll</p>
        </div>
        <div className="flex bg-[#1a1a1a] border border-[#2a2a2a] rounded overflow-hidden">
          <button
            onClick={() => { localStorage.setItem('browse_load_mode', 'pagination'); onForceRerender() }}
            className={`px-3 py-1.5 text-xs transition-colors ${loadMode === 'pagination' ? 'bg-blue-600 text-white' : 'text-gray-500 hover:text-gray-300'}`}
          >
            Pagination
          </button>
          <button
            onClick={() => { localStorage.setItem('browse_load_mode', 'scroll'); onForceRerender() }}
            className={`px-3 py-1.5 text-xs transition-colors ${loadMode === 'scroll' ? 'bg-blue-600 text-white' : 'text-gray-500 hover:text-gray-300'}`}
          >
            Infinite Scroll
          </button>
        </div>
      </div>

      {/* Per page (library) */}
      <div className="mt-5 flex items-center justify-between">
        <div>
          <p className="text-sm text-white">Per Page</p>
          <p className="text-xs text-gray-600 mt-0.5">Number of items per page</p>
        </div>
        <select
          value={perPage}
          onChange={(e) => { localStorage.setItem('browse_per_page', e.target.value); onForceRerender() }}
          className="bg-[#1a1a1a] border border-[#2a2a2a] rounded px-3 py-1.5 text-sm text-white focus:outline-none"
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
  const [ehSuccess, setEhSuccess] = useState<string | null>(null)
  const [ehError, setEhError] = useState<string | null>(null)
  const [ehAccount, setEhAccount] = useState<EhAccount | null>(null)
  const [ehAccountLoading, setEhAccountLoading] = useState(false)

  // Pixiv Token form
  const [pixivToken, setPixivToken] = useState('')
  const [pixivSaving, setPixivSaving] = useState(false)
  const [pixivSuccess, setPixivSuccess] = useState<string | null>(null)
  const [pixivError, setPixivError] = useState<string | null>(null)
  const [pixivUsername, setPixivUsername] = useState<string | null>(null)

  // System info
  const [health, setHealth] = useState<SystemHealth | null>(null)
  const [systemInfo, setSystemInfo] = useState<SystemInfo | null>(null)
  const [systemLoading, setSystemLoading] = useState(false)
  const [systemError, setSystemError] = useState<string | null>(null)

  // Rate limiting
  const [rateLimitEnabled, setRateLimitEnabled] = useState<boolean | null>(null)
  const [rateLimitToggling, setRateLimitToggling] = useState(false)

  // Sessions
  const [sessions, setSessions] = useState<SessionInfo[]>([])
  const [sessionsLoading, setSessionsLoading] = useState(false)
  const [revokingToken, setRevokingToken] = useState<string | null>(null)

  // Load credentials on mount
  useEffect(() => {
    api.settings.getCredentials()
      .then(setCredentials)
      .catch(() => {})
      .finally(() => setCredLoading(false))
  }, [])

  const toggleSection = useCallback((key: SectionKey) => {
    setActiveSection((prev) => (prev === key ? null : key))
  }, [])

  // EH: Login with username/password
  const handleEhLogin = useCallback(async () => {
    if (!ehUsername.trim() || !ehPassword.trim()) return
    setEhLoginSaving(true)
    setEhError(null)
    setEhSuccess(null)
    try {
      const result = await api.settings.ehLogin(ehUsername.trim(), ehPassword.trim())
      setEhSuccess('E-Hentai login successful')
      setEhAccount(result.account)
      setCredentials((prev) => prev ? { ...prev, ehentai: { configured: true } } : prev)
    } catch (err) {
      setEhError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setEhLoginSaving(false)
    }
  }, [ehUsername, ehPassword])

  // EH: Save cookies
  const handleEhSave = useCallback(async () => {
    if (!ehMemberId.trim() || !ehPassHash.trim() || !ehSk.trim()) return
    setEhSaving(true)
    setEhError(null)
    setEhSuccess(null)
    try {
      const result = await api.settings.setEhCookies({
        ipb_member_id: ehMemberId.trim(),
        ipb_pass_hash: ehPassHash.trim(),
        sk: ehSk.trim(),
      })
      setEhSuccess('E-Hentai credentials saved successfully')
      setEhAccount(result.account)
      setCredentials((prev) => prev ? { ...prev, ehentai: { configured: true } } : prev)
    } catch (err) {
      setEhError(err instanceof Error ? err.message : 'Failed to save credentials')
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
      setEhError(err instanceof Error ? err.message : 'Failed to fetch account info')
    } finally {
      setEhAccountLoading(false)
    }
  }, [])

  // Pixiv: Save token
  const handlePixivSave = useCallback(async () => {
    if (!pixivToken.trim()) return
    setPixivSaving(true)
    setPixivError(null)
    setPixivSuccess(null)
    try {
      const result = await api.settings.setPixivToken(pixivToken.trim())
      setPixivSuccess(`Pixiv credentials saved. Account: ${result.username}`)
      setPixivUsername(result.username)
      setCredentials((prev) => prev ? { ...prev, pixiv: { configured: true } } : prev)
    } catch (err) {
      setPixivError(err instanceof Error ? err.message : 'Failed to save Pixiv token')
    } finally {
      setPixivSaving(false)
    }
  }, [pixivToken])

  // System: Load health + info
  const handleLoadSystem = useCallback(async () => {
    setSystemLoading(true)
    setSystemError(null)
    try {
      const [h, i, rl] = await Promise.all([api.system.health(), api.system.info(), api.settings.getRateLimit()])
      setHealth(h)
      setSystemInfo(i)
      setRateLimitEnabled(rl.enabled)
    } catch (err) {
      setSystemError(err instanceof Error ? err.message : 'Failed to load system info')
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
      // revert on failure
    } finally {
      setRateLimitToggling(false)
    }
  }, [rateLimitEnabled])

  const handleLoadSessions = useCallback(async () => {
    setSessionsLoading(true)
    try {
      const result = await api.auth.getSessions()
      setSessions(result.sessions)
    } catch {
      // ignore
    } finally {
      setSessionsLoading(false)
    }
  }, [])

  const handleRevokeSession = useCallback(async (tokenPrefix: string) => {
    setRevokingToken(tokenPrefix)
    try {
      await api.auth.revokeSession(tokenPrefix)
      setSessions((prev) => prev.filter((s) => s.token_prefix !== tokenPrefix))
    } catch {
      // ignore
    } finally {
      setRevokingToken(null)
    }
  }, [])

  useEffect(() => {
    if (activeSection === 'system' && !health && !systemLoading) {
      handleLoadSystem()
    }
    if (activeSection === 'account' && sessions.length === 0 && !sessionsLoading) {
      handleLoadSessions()
    }
  }, [activeSection, health, systemLoading, handleLoadSystem, sessions.length, sessionsLoading, handleLoadSessions])

  const serviceStatusClass = (status: string) =>
    status === 'ok' || status === 'healthy'
      ? 'text-green-400'
      : 'text-red-400'

  return (
    <div className="min-h-screen bg-[#0a0a0a] text-white">
      <div className="max-w-2xl mx-auto px-4 py-6">
        <h1 className="text-2xl font-bold mb-6 text-white">Settings</h1>

        <div className="space-y-3">
          {/* ── E-Hentai ── */}
          <div className="bg-[#111111] border border-[#2a2a2a] rounded-xl overflow-hidden">
            <div className="flex items-center justify-between">
              <div className="flex-1">
                <SectionHeader
                  title="E-Hentai"
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
              <div className="px-5 pb-5 border-t border-[#1e1e1e]">
                {ehSuccess && (
                  <div className="mt-4">
                    <AlertBanner alerts={[ehSuccess]} onDismiss={() => setEhSuccess(null)} />
                  </div>
                )}
                {ehError && (
                  <div className="mt-4">
                    <AlertBanner alerts={[ehError]} onDismiss={() => setEhError(null)} />
                  </div>
                )}

                {/* Mode toggle */}
                <div className="flex mt-4 bg-[#1a1a1a] border border-[#2a2a2a] rounded overflow-hidden">
                  <button
                    onClick={() => setEhLoginMode('password')}
                    className={`flex-1 px-3 py-2 text-sm transition-colors ${ehLoginMode === 'password' ? 'bg-blue-600 text-white' : 'text-gray-500 hover:text-gray-300'}`}
                  >
                    Username / Password
                  </button>
                  <button
                    onClick={() => setEhLoginMode('cookie')}
                    className={`flex-1 px-3 py-2 text-sm transition-colors ${ehLoginMode === 'cookie' ? 'bg-blue-600 text-white' : 'text-gray-500 hover:text-gray-300'}`}
                  >
                    Cookie (Advanced)
                  </button>
                </div>

                {/* Password login */}
                {ehLoginMode === 'password' && (
                  <div className="mt-4 space-y-3">
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">Username</label>
                      <input
                        type="text"
                        value={ehUsername}
                        onChange={(e) => setEhUsername(e.target.value)}
                        placeholder="E-Hentai username"
                        autoComplete="username"
                        className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded px-3 py-2 text-white placeholder-gray-600 focus:outline-none focus:border-[#444] text-sm"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">Password</label>
                      <input
                        type="password"
                        value={ehPassword}
                        onChange={(e) => setEhPassword(e.target.value)}
                        placeholder="E-Hentai password"
                        autoComplete="current-password"
                        onKeyDown={(e) => e.key === 'Enter' && handleEhLogin()}
                        className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded px-3 py-2 text-white placeholder-gray-600 focus:outline-none focus:border-[#444] text-sm"
                      />
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={handleEhLogin}
                        disabled={ehLoginSaving}
                        className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-900 disabled:text-blue-600 rounded text-white text-sm font-medium transition-colors"
                      >
                        {ehLoginSaving ? 'Logging in...' : 'Log In'}
                      </button>
                      <button
                        onClick={handleEhRefresh}
                        disabled={ehAccountLoading}
                        className="px-4 py-2 bg-[#1a1a1a] border border-[#2a2a2a] hover:border-[#444] rounded text-gray-400 text-sm transition-colors"
                      >
                        {ehAccountLoading ? 'Refreshing...' : 'Refresh Account'}
                      </button>
                    </div>
                  </div>
                )}

                {/* Cookie login */}
                {ehLoginMode === 'cookie' && (
                  <div className="mt-4 space-y-3">
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">ipb_member_id</label>
                      <input
                        type="text"
                        value={ehMemberId}
                        onChange={(e) => setEhMemberId(e.target.value)}
                        placeholder="Enter ipb_member_id"
                        className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded px-3 py-2 text-white placeholder-gray-600 focus:outline-none focus:border-[#444] text-sm"
                      />
                    </div>
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">ipb_pass_hash</label>
                      <div className="relative">
                        <input
                          type={showPassHash ? 'text' : 'password'}
                          value={ehPassHash}
                          onChange={(e) => setEhPassHash(e.target.value)}
                          placeholder="Enter ipb_pass_hash"
                          className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded px-3 py-2 pr-10 text-white placeholder-gray-600 focus:outline-none focus:border-[#444] text-sm"
                        />
                        <button
                          type="button"
                          onClick={() => setShowPassHash((v) => !v)}
                          className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-300 text-sm transition-colors px-1"
                        >
                          {showPassHash ? 'Hide' : 'Show'}
                        </button>
                      </div>
                    </div>
                    <div>
                      <label className="block text-xs text-gray-500 mb-1">sk</label>
                      <input
                        type="text"
                        value={ehSk}
                        onChange={(e) => setEhSk(e.target.value)}
                        placeholder="Enter sk"
                        className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded px-3 py-2 text-white placeholder-gray-600 focus:outline-none focus:border-[#444] text-sm"
                      />
                    </div>
                    <div className="flex gap-2">
                      <button
                        onClick={handleEhSave}
                        disabled={ehSaving}
                        className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-900 disabled:text-blue-600 rounded text-white text-sm font-medium transition-colors"
                      >
                        {ehSaving ? 'Saving...' : 'Save Cookies'}
                      </button>
                      <button
                        onClick={handleEhRefresh}
                        disabled={ehAccountLoading}
                        className="px-4 py-2 bg-[#1a1a1a] border border-[#2a2a2a] hover:border-[#444] rounded text-gray-400 text-sm transition-colors"
                      >
                        {ehAccountLoading ? 'Refreshing...' : 'Refresh Account'}
                      </button>
                    </div>
                  </div>
                )}

                {/* Account Info */}
                {ehAccount && (
                  <div className="mt-4 bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg p-3">
                    <p className="text-xs text-gray-500 uppercase tracking-wide mb-2">Account Status</p>
                    <div className="space-y-1">
                      <div className="flex justify-between text-sm">
                        <span className="text-gray-500">Valid</span>
                        <span className={ehAccount.valid ? 'text-green-400' : 'text-red-400'}>
                          {ehAccount.valid ? 'Yes' : 'No'}
                        </span>
                      </div>
                      {ehAccount.credits !== undefined && (
                        <div className="flex justify-between text-sm">
                          <span className="text-gray-500">Credits</span>
                          <span className="text-gray-200">{ehAccount.credits.toLocaleString()}</span>
                        </div>
                      )}
                      {ehAccount.hath_perks !== undefined && (
                        <div className="flex justify-between text-sm">
                          <span className="text-gray-500">H@H Perks</span>
                          <span className="text-gray-200">{ehAccount.hath_perks}</span>
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
          <div className="bg-[#111111] border border-[#2a2a2a] rounded-xl overflow-hidden">
            <div className="flex items-center justify-between">
              <div className="flex-1">
                <SectionHeader
                  title="Pixiv Token"
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
              <div className="px-5 pb-5 border-t border-[#1e1e1e]">
                {pixivSuccess && (
                  <div className="mt-4">
                    <AlertBanner alerts={[pixivSuccess]} onDismiss={() => setPixivSuccess(null)} />
                  </div>
                )}
                {pixivError && (
                  <div className="mt-4">
                    <AlertBanner alerts={[pixivError]} onDismiss={() => setPixivError(null)} />
                  </div>
                )}

                <div className="mt-4">
                  <label className="block text-xs text-gray-500 mb-1">refresh_token</label>
                  <input
                    type="password"
                    value={pixivToken}
                    onChange={(e) => setPixivToken(e.target.value)}
                    placeholder="Enter Pixiv refresh token"
                    className="w-full bg-[#1a1a1a] border border-[#2a2a2a] rounded px-3 py-2 text-white placeholder-gray-600 focus:outline-none focus:border-[#444] text-sm"
                  />
                  <p className="text-xs text-gray-600 mt-1">
                    Obtain via <code className="text-gray-500">pixivpy</code> or the Pixiv OAuth flow.
                  </p>
                </div>

                {pixivUsername && (
                  <div className="mt-3 flex items-center gap-2 text-sm">
                    <span className="text-gray-500">Account:</span>
                    <span className="text-gray-200">{pixivUsername}</span>
                  </div>
                )}

                <div className="mt-4">
                  <button
                    onClick={handlePixivSave}
                    disabled={pixivSaving}
                    className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-900 disabled:text-blue-600 rounded text-white text-sm font-medium transition-colors"
                  >
                    {pixivSaving ? 'Saving...' : 'Save Token'}
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* ── System Info ── */}
          <div className="bg-[#111111] border border-[#2a2a2a] rounded-xl overflow-hidden">
            <SectionHeader
              title="System"
              sectionKey="system"
              activeSection={activeSection}
              onToggle={toggleSection}
            />

            {activeSection === 'system' && (
              <div className="px-5 pb-5 border-t border-[#1e1e1e]">
                {systemLoading && (
                  <div className="flex justify-center py-8">
                    <LoadingSpinner />
                  </div>
                )}
                {systemError && (
                  <div className="mt-4 text-red-400 text-sm">{systemError}</div>
                )}
                {!systemLoading && health && systemInfo && (
                  <div className="mt-4 space-y-4">
                    {/* Health */}
                    <div>
                      <p className="text-xs text-gray-500 uppercase tracking-wide mb-2">Service Health</p>
                      <div className="bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg divide-y divide-[#1e1e1e]">
                        {[
                          { label: 'Overall', value: health.status },
                          { label: 'PostgreSQL', value: health.services.postgres },
                          { label: 'Redis', value: health.services.redis },
                        ].map(({ label, value }) => (
                          <div key={label} className="flex justify-between items-center px-3 py-2">
                            <span className="text-sm text-gray-500">{label}</span>
                            <span className={`text-sm font-medium ${serviceStatusClass(value)}`}>
                              {value}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Info */}
                    <div>
                      <p className="text-xs text-gray-500 uppercase tracking-wide mb-2">Configuration</p>
                      <div className="bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg divide-y divide-[#1e1e1e]">
                        {[
                          { label: 'Version', value: systemInfo.version },
                          { label: 'EH Max Concurrency', value: String(systemInfo.eh_max_concurrency) },
                          {
                            label: 'AI Tagging',
                            value: systemInfo.tag_model_enabled ? 'Enabled' : 'Disabled',
                            valueClass: systemInfo.tag_model_enabled ? 'text-green-400' : 'text-gray-500',
                          },
                        ].map(({ label, value, valueClass }) => (
                          <div key={label} className="flex justify-between items-center px-3 py-2">
                            <span className="text-sm text-gray-500">{label}</span>
                            <span className={`text-sm font-medium ${valueClass ?? 'text-gray-200'}`}>{value}</span>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* Rate Limiting */}
                    <div>
                      <p className="text-xs text-gray-500 uppercase tracking-wide mb-2">Security</p>
                      <div className="bg-[#1a1a1a] border border-[#2a2a2a] rounded-lg px-3 py-2">
                        <div className="flex items-center justify-between">
                          <div>
                            <p className="text-sm text-white">Rate Limiting</p>
                            <p className="text-xs text-gray-600 mt-0.5">Protect login and API endpoints</p>
                          </div>
                          <button
                            onClick={handleToggleRateLimit}
                            disabled={rateLimitToggling || rateLimitEnabled === null}
                            className={`relative w-11 h-6 rounded-full transition-colors ${rateLimitEnabled ? 'bg-blue-600' : 'bg-[#333]'}`}
                          >
                            <span className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform ${rateLimitEnabled ? 'translate-x-5' : ''}`} />
                          </button>
                        </div>
                      </div>
                    </div>

                    <button
                      onClick={handleLoadSystem}
                      className="text-xs text-gray-600 hover:text-gray-400 transition-colors"
                    >
                      Refresh
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* ── Browse Settings ── */}
          <div className="bg-[#111111] border border-[#2a2a2a] rounded-xl overflow-hidden">
            <SectionHeader
              title="Browse"
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
          <div className="bg-[#111111] border border-[#2a2a2a] rounded-xl overflow-hidden">
            <SectionHeader
              title="Account"
              sectionKey="account"
              activeSection={activeSection}
              onToggle={toggleSection}
            />
            {activeSection === 'account' && (
              <div className="px-5 pb-5 border-t border-[#1e1e1e]">
                {/* Active Sessions */}
                <div className="mt-4">
                  <div className="flex items-center justify-between mb-2">
                    <p className="text-xs text-gray-500 uppercase tracking-wide">Active Sessions</p>
                    <button
                      onClick={handleLoadSessions}
                      disabled={sessionsLoading}
                      className="text-xs text-gray-600 hover:text-gray-400 transition-colors"
                    >
                      {sessionsLoading ? 'Loading...' : 'Refresh'}
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
                          className={`bg-[#1a1a1a] border rounded-lg px-3 py-2.5 ${
                            s.is_current ? 'border-blue-600/50' : 'border-[#2a2a2a]'
                          }`}
                        >
                          <div className="flex items-start justify-between gap-2">
                            <div className="min-w-0 flex-1">
                              <div className="flex items-center gap-2">
                                <span className="text-sm text-white font-mono">{s.token_prefix}...</span>
                                {s.is_current && (
                                  <span className="text-[10px] bg-blue-600/30 text-blue-400 px-1.5 py-0.5 rounded">
                                    Current
                                  </span>
                                )}
                              </div>
                              <p className="text-xs text-gray-600 mt-1 truncate" title={s.user_agent}>
                                {s.user_agent || 'Unknown device'}
                              </p>
                              <div className="flex items-center gap-3 mt-1">
                                <span className="text-xs text-gray-600">{s.ip}</span>
                                {s.created_at && (
                                  <span className="text-xs text-gray-600">
                                    {new Date(s.created_at).toLocaleDateString()}
                                  </span>
                                )}
                                <span className="text-xs text-gray-600">
                                  Expires in {Math.ceil(s.ttl / 86400)}d
                                </span>
                              </div>
                            </div>
                            {!s.is_current && (
                              <button
                                onClick={() => handleRevokeSession(s.token_prefix)}
                                disabled={revokingToken === s.token_prefix}
                                className="text-xs text-red-400/70 hover:text-red-400 transition-colors shrink-0 px-2 py-1"
                              >
                                {revokingToken === s.token_prefix ? '...' : 'Revoke'}
                              </button>
                            )}
                          </div>
                        </div>
                      ))}
                      {sessions.length === 0 && !sessionsLoading && (
                        <p className="text-xs text-gray-600 py-2">No active sessions found.</p>
                      )}
                    </div>
                  )}
                </div>

                <div className="mt-5 pt-4 border-t border-[#1e1e1e]">
                  <button
                    onClick={logout}
                    className="px-4 py-2 bg-red-900/40 border border-red-700/50 hover:bg-red-900/60 text-red-400 rounded text-sm font-medium transition-colors"
                  >
                    Log Out
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
