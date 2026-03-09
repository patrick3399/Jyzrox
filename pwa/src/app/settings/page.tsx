'use client'

import { useState, useEffect, useCallback } from 'react'
import { useLocale } from '@/components/LocaleProvider'
import { SUPPORTED_LOCALES, type Locale } from '@/lib/i18n'
import { ChevronUp, ChevronDown, Eye, EyeOff, RefreshCw, Shield, Monitor, CalendarClock, Square } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { t } from '@/lib/i18n'
import { Copy, Key, BookOpen, X, Plus, Tag, ScanLine } from 'lucide-react'
import { useRescanLibrary, useRescanStatus, useScanSettings, useUpdateScanSettings, useCancelRescan } from '@/hooks/useImport'
import { loadReaderSettings, saveReaderSettings } from '@/components/Reader/hooks'
import type { ViewMode, ScaleMode, ReadingDirection } from '@/components/Reader/types'
import type {
  SystemHealth,
  SystemInfo,
  EhAccount,
  Credentials,
  SessionInfo,
  ApiTokenInfo,
  BlockedTag,
  CacheStats,
} from '@/lib/types'

type SectionKey =
  | 'ehentai'
  | 'pixiv'
  | 'system'
  | 'account'
  | 'browse'
  | 'apiTokens'
  | 'reader'
  | 'blockedTags'
  | 'aiTagging'
  | 'schedule'

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

// ── AI Tagging sub-component ──────────────────────────────────────────

function AiTaggingSection() {
  const [isRetagging, setIsRetagging] = useState(false)

  const handleRetagAll = async () => {
    if (!window.confirm(t('settings.retagAllConfirm'))) return
    setIsRetagging(true)
    try {
      const result = await api.tags.retagAll()
      toast.success(t('settings.retagAllQueued', { total: result.total }))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.retagAllFailed'))
    } finally {
      setIsRetagging(false)
    }
  }

  return (
    <div className="px-5 pb-5 border-t border-vault-border">
      <p className="text-xs text-vault-text-muted mt-4 mb-4">
        {t('settings.aiTaggingDesc')}
      </p>
      <button
        onClick={handleRetagAll}
        disabled={isRetagging}
        className="px-4 py-2 bg-purple-900/30 border border-purple-700/50 text-purple-400 hover:bg-purple-900/50 rounded text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {isRetagging ? t('settings.retagging') : t('settings.retagAll')}
      </button>
    </div>
  )
}

// ── Scan Schedule sub-component ──────────────────────────────────────

function ScanScheduleSection() {
  const { data: scanSettings, mutate: mutateScan } = useScanSettings()
  const { trigger: updateSettings } = useUpdateScanSettings()
  const { trigger: rescan, isMutating: rescanning } = useRescanLibrary()
  const { data: rescanStatus } = useRescanStatus()
  const { trigger: cancelRescan, isMutating: cancelling } = useCancelRescan()

  const handleToggle = async () => {
    if (!scanSettings) return
    try {
      await updateSettings({ enabled: !scanSettings.enabled })
      mutateScan()
    } catch {
      toast.error(t('common.failedToLoad'))
    }
  }

  const handleIntervalChange = async (hours: number) => {
    try {
      await updateSettings({ interval_hours: hours })
      mutateScan()
    } catch {
      toast.error(t('common.failedToLoad'))
    }
  }

  const handleRescan = async () => {
    try {
      await rescan()
      toast.success(t('settings.media.rescan'))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToLoad'))
    }
  }

  const isRunning = rescanStatus?.running ?? false
  const processed = rescanStatus?.processed
  const total = rescanStatus?.total

  const intervalOptions = [6, 8, 12, 24, 48, 72, 168]

  return (
    <div className="px-5 pb-5 border-t border-vault-border">
      <p className="text-xs text-vault-text-muted mt-4 mb-4">
        {t('settings.schedule.desc')}
      </p>

      {/* Enable/disable toggle */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <p className="text-sm text-vault-text">{t('settings.schedule.auto')}</p>
          <p className="text-xs text-vault-text-muted mt-0.5">{t('settings.schedule.autoDesc')}</p>
        </div>
        <button
          onClick={handleToggle}
          className={`relative w-11 h-6 rounded-full transition-colors ${
            scanSettings?.enabled ? 'bg-vault-accent' : 'bg-vault-border'
          }`}
        >
          <span
            className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform shadow ${
              scanSettings?.enabled ? 'translate-x-5' : ''
            }`}
          />
        </button>
      </div>

      {/* Interval selector */}
      <div className="mb-4">
        <p className="text-sm text-vault-text mb-2">{t('settings.schedule.interval')}</p>
        <div className="flex flex-wrap gap-1.5">
          {intervalOptions.map((h) => (
            <button
              key={h}
              onClick={() => handleIntervalChange(h)}
              disabled={!scanSettings?.enabled}
              className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${
                scanSettings?.interval_hours === h
                  ? 'bg-vault-accent text-white'
                  : 'bg-vault-input border border-vault-border text-vault-text-muted hover:text-vault-text hover:border-vault-accent/50 disabled:opacity-40 disabled:cursor-not-allowed'
              }`}
            >
              {h < 24 ? t('settings.schedule.hours', { count: h }) : t('settings.schedule.days', { count: h / 24 })}
            </button>
          ))}
        </div>
      </div>

      {/* Last run info */}
      {scanSettings?.last_run && (
        <p className="text-xs text-vault-text-muted mb-4">
          {t('settings.schedule.lastRun')}: {new Date(scanSettings.last_run).toLocaleString()}
        </p>
      )}

      {/* Rescan All Libraries */}
      <div className="pt-3 border-t border-vault-border/50">
        <p className="text-xs text-vault-text-muted mb-3">
          {t('settings.media.rescan.desc')}
        </p>

        {isRunning && processed !== undefined && total !== undefined && (
          <div className="mb-3 bg-vault-input border border-vault-border rounded-lg px-4 py-3">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm text-vault-text">
                {t('settings.media.rescan.running', { processed, total })}
              </span>
              <span className="text-xs text-blue-400">
                {total > 0 ? Math.round((processed / total) * 100) : 0}%
              </span>
            </div>
            <div className="h-1.5 bg-vault-border rounded-full overflow-hidden">
              <div
                className="h-full rounded-full bg-blue-500 transition-all duration-500"
                style={{ width: `${total > 0 ? Math.round((processed / total) * 100) : 0}%` }}
              />
            </div>
            {rescanStatus?.current_gallery && (
              <p className="text-xs text-vault-text-muted mt-1.5 truncate">
                {rescanStatus.current_gallery}
              </p>
            )}
            <button
              onClick={async () => {
                try { await cancelRescan() } catch { /* ignore */ }
              }}
              disabled={cancelling}
              className="mt-2 flex items-center gap-1.5 px-3 py-1 text-xs text-red-400 hover:text-red-300 border border-red-500/30 hover:border-red-500/50 rounded transition-colors disabled:opacity-50"
            >
              <Square size={11} />
              {cancelling ? t('settings.media.rescan.cancelling') : t('settings.media.rescan.cancel')}
            </button>
          </div>
        )}

        {!isRunning && rescanStatus?.status === 'cancelled' && (
          <p className="text-xs text-orange-400 mb-3">{t('settings.media.rescan.cancelled')}</p>
        )}

        {!isRunning && rescanStatus && processed !== undefined && total !== undefined && processed === total && total > 0 && rescanStatus.status !== 'cancelled' && (
          <p className="text-xs text-green-400 mb-3">{t('settings.media.rescan.done')}</p>
        )}

        <button
          onClick={handleRescan}
          disabled={rescanning || isRunning}
          className="flex items-center gap-2 px-4 py-2 bg-vault-input border border-vault-border hover:border-vault-accent/50 text-vault-text-secondary hover:text-vault-text rounded text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <ScanLine size={15} />
          {isRunning ? t('settings.loading') : t('settings.media.rescan')}
        </button>
      </div>
    </div>
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

      {/* Browse History toggle */}
      <BrowseHistoryToggle onForceRerender={onForceRerender} />
    </div>
  )
}

// ── Browse History Toggle sub-component ──────────────────────────────

function BrowseHistoryToggle({ onForceRerender }: { onForceRerender: () => void }) {
  const historyEnabled =
    typeof window !== 'undefined' && localStorage.getItem('history_enabled') !== 'false'
  return (
    <div className="mt-5 flex items-center justify-between">
      <div>
        <p className="text-sm text-vault-text">{t('settings.browseHistory')}</p>
        <p className="text-xs text-vault-text-muted mt-0.5">{t('settings.browseHistoryDesc')}</p>
      </div>
      <button
        onClick={() => {
          const next = localStorage.getItem('history_enabled') === 'false'
          localStorage.setItem('history_enabled', next ? 'true' : 'false')
          onForceRerender()
        }}
        className={`relative w-11 h-6 rounded-full transition-colors ${historyEnabled ? 'bg-vault-accent' : 'bg-vault-border'}`}
      >
        <span
          className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform ${historyEnabled ? 'translate-x-5' : ''}`}
        />
      </button>
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
  const { locale, setLocale: changeLocale } = useLocale()
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
  const [pixivLoginMode, setPixivLoginMode] = useState<'oauth' | 'token' | 'cookie'>('oauth')
  const [pixivToken, setPixivToken] = useState('')
  const [pixivCookie, setPixivCookie] = useState('')
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

  // Cache stats
  const [cacheStats, setCacheStats] = useState<CacheStats | null>(null)
  const [cacheLoading, setCacheLoading] = useState(false)
  const [cacheClearingAll, setCacheClearingAll] = useState(false)
  const [cacheClearingCategory, setCacheClearingCategory] = useState<string | null>(null)

  // Blocked Tags
  const [blockedTags, setBlockedTags] = useState<BlockedTag[]>([])
  const [blockedTagsLoaded, setBlockedTagsLoaded] = useState(false)
  const [blockedTagsLoading, setBlockedTagsLoading] = useState(false)
  const [newBlockedTag, setNewBlockedTag] = useState('')
  const [blockingTag, setBlockingTag] = useState(false)
  const [removingBlockedTagId, setRemovingBlockedTagId] = useState<number | null>(null)

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
    if (!confirm(t('settings.clearEhConfirm'))) return
    try {
      await api.settings.deleteCredential('ehentai')
      toast.success(t('settings.ehCookiesCleared'))
      setCredentials((prev) => (prev ? { ...prev, ehentai: { configured: false } } : prev))
      setEhAccount(null)
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : t('settings.clearFailed'))
    }
  }

  // Pixiv: Clear credential
  const handleClearPixiv = async () => {
    if (!confirm(t('settings.confirmClearPixiv'))) return
    try {
      await api.settings.deleteCredential('pixiv')
      toast.success(t('settings.pixivTokenCleared'))
      setCredentials((prev) => (prev ? { ...prev, pixiv: { configured: false } } : prev))
      setPixivUsername(null)
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : t('settings.clearFailed'))
    }
  }

  // System: Load health + info + cache
  const handleLoadSystem = useCallback(async () => {
    setSystemLoading(true)
    try {
      const [h, i, rl, cs] = await Promise.all([
        api.system.health(),
        api.system.info(),
        api.settings.getRateLimit(),
        api.system.getCache(),
      ])
      setHealth(h)
      setSystemInfo(i)
      setRateLimitEnabled(rl.enabled)
      setCacheStats(cs)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.systemLoadFailed'))
    } finally {
      setSystemLoading(false)
    }
  }, [])

  // Cache: Refresh stats only
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

  // Cache: Clear all
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

  // Cache: Clear category
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

  // Blocked Tags: Load
  const handleLoadBlockedTags = useCallback(async () => {
    setBlockedTagsLoading(true)
    try {
      const items = await api.tags.listBlocked()
      setBlockedTags(items)
      setBlockedTagsLoaded(true)
    } catch {
      toast.error(t('common.failedToLoad'))
      setBlockedTagsLoaded(true)
    } finally {
      setBlockedTagsLoading(false)
    }
  }, [])

  // Blocked Tags: Add
  const handleAddBlockedTag = useCallback(async () => {
    const raw = newBlockedTag.trim()
    if (!raw) return
    // accept "namespace:name" or fall back to "tag:name"
    const colonIdx = raw.indexOf(':')
    let namespace: string
    let name: string
    if (colonIdx > 0) {
      namespace = raw.slice(0, colonIdx).trim()
      name = raw.slice(colonIdx + 1).trim()
    } else {
      namespace = 'tag'
      name = raw
    }
    if (!name) return
    setBlockingTag(true)
    try {
      await api.tags.addBlocked(namespace, name)
      toast.success(t('settings.tagBlockAdded'))
      setNewBlockedTag('')
      await handleLoadBlockedTags()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.tagBlockAddFailed'))
    } finally {
      setBlockingTag(false)
    }
  }, [newBlockedTag, handleLoadBlockedTags])

  // Blocked Tags: Remove
  const handleRemoveBlockedTag = useCallback(
    async (id: number) => {
      setRemovingBlockedTagId(id)
      try {
        await api.tags.removeBlocked(id)
        toast.success(t('settings.tagBlockRemoved'))
        setBlockedTags((prev) => prev.filter((bt) => bt.id !== id))
      } catch (err) {
        toast.error(err instanceof Error ? err.message : t('settings.tagBlockRemoveFailed'))
      } finally {
        setRemovingBlockedTagId(null)
      }
    },
    [],
  )

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
      const created = await api.tokens.create(newTokenName.trim(), expDays)
      setApiTokens((prev) => [created, ...prev])
      toast.success('Token created')
      setNewTokenName('')
      setNewTokenExpiry('')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to create token')
    } finally {
      setTokenCreating(false)
    }
  }, [newTokenName, newTokenExpiry])

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
    if (activeSection === 'blockedTags' && !blockedTagsLoaded && !blockedTagsLoading) {
      handleLoadBlockedTags()
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
    blockedTagsLoaded,
    blockedTagsLoading,
    handleLoadBlockedTags,
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
          {/* ── Language ── */}
          <div className="bg-vault-card rounded-xl border border-vault-border overflow-hidden">
            <div className="px-5 py-4">
              <h3 className="font-medium text-vault-text text-sm mb-3">{t('settings.language')}</h3>
              <select
                value={locale}
                onChange={(e) => changeLocale(e.target.value as Locale)}
                className="bg-vault-input text-vault-text text-sm rounded-lg px-3 py-2 border border-vault-border focus:outline-none focus:ring-1 focus:ring-vault-accent"
              >
                {SUPPORTED_LOCALES.map((loc: Locale) => (
                  <option key={loc} value={loc}>
                    {t(`common.locale.${loc}`)}
                  </option>
                ))}
              </select>
            </div>
          </div>

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
                        placeholder={t('settings.ehUsernamePlaceholder')}
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
                        placeholder={t('settings.ehPasswordPlaceholder')}
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
                      <label className="block text-xs text-vault-text-muted mb-1">sk</label>
                      <input
                        type="text"
                        value={ehSk}
                        onChange={(e) => setEhSk(e.target.value)}
                        placeholder={t('settings.enterSk')}
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
                        placeholder={t('settings.enterIgneous')}
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
                      <p className="text-yellow-400/70">
                        {t('settings.pixivOauthHint2')}
                      </p>
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
                                <span className="text-sm font-mono text-vault-text-secondary">{value}</span>
                              </div>
                            ))}
                        </div>
                      </div>
                    )}

                    {/* Info */}
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

          {/* ── Blocked Tags ── */}
          <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
            <div className="flex items-center justify-between">
              <div className="flex-1">
                <SectionHeader
                  title={t('settings.blockedTags')}
                  sectionKey="blockedTags"
                  activeSection={activeSection}
                  onToggle={toggleSection}
                />
              </div>
              {blockedTags.length > 0 && (
                <div className="pr-5">
                  <span className="inline-flex items-center gap-1 text-xs text-vault-text-muted">
                    <Tag size={12} />
                    {blockedTags.length}
                  </span>
                </div>
              )}
            </div>

            {activeSection === 'blockedTags' && (
              <div className="px-5 pb-5 border-t border-vault-border">
                <p className="text-xs text-vault-text-muted mt-4 mb-3">
                  {t('settings.tagBlockingDesc')}
                </p>

                {/* Add new blocked tag */}
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={newBlockedTag}
                    onChange={(e) => setNewBlockedTag(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && handleAddBlockedTag()}
                    placeholder={t('settings.blockedTagPlaceholder')}
                    className={inputClass + ' flex-1'}
                  />
                  <button
                    onClick={handleAddBlockedTag}
                    disabled={blockingTag || !newBlockedTag.trim()}
                    className={btnPrimary + ' flex items-center gap-1.5 shrink-0'}
                  >
                    <Plus size={14} />
                    {blockingTag ? t('settings.saving') : t('settings.addBlockedTag')}
                  </button>
                </div>

                {/* Blocked tag list */}
                <div className="mt-4">
                  <div className="flex items-center justify-between mb-2">
                    <p className="text-xs text-vault-text-muted uppercase tracking-wide">
                      {t('settings.blockedTags')}
                    </p>
                    <button
                      onClick={handleLoadBlockedTags}
                      disabled={blockedTagsLoading}
                      className="text-xs text-vault-text-muted hover:text-vault-text-secondary transition-colors"
                    >
                      {blockedTagsLoading ? t('settings.loading') : t('settings.refresh')}
                    </button>
                  </div>

                  {blockedTagsLoading && blockedTags.length === 0 ? (
                    <div className="flex justify-center py-4">
                      <LoadingSpinner />
                    </div>
                  ) : blockedTags.length === 0 ? (
                    <p className="text-xs text-vault-text-muted py-2">
                      {t('settings.noBlockedTags')}
                    </p>
                  ) : (
                    <div className="flex flex-wrap gap-2">
                      {blockedTags.map((bt) => (
                        <div
                          key={bt.id}
                          className="inline-flex items-center gap-1.5 bg-vault-input border border-vault-border rounded-full px-3 py-1 text-sm text-vault-text"
                        >
                          <span className="text-vault-text-muted text-xs">{bt.namespace}:</span>
                          <span>{bt.name}</span>
                          <button
                            onClick={() => handleRemoveBlockedTag(bt.id)}
                            disabled={removingBlockedTagId === bt.id}
                            className="ml-0.5 text-vault-text-muted hover:text-red-400 transition-colors disabled:opacity-40"
                            title={t('settings.unblock')}
                          >
                            {removingBlockedTagId === bt.id ? (
                              <span className="text-[10px]">...</span>
                            ) : (
                              <X size={12} />
                            )}
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* ── AI Tagging ── */}
          <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
            <SectionHeader
              title={t('settings.aiTaggingSection')}
              sectionKey="aiTagging"
              activeSection={activeSection}
              onToggle={toggleSection}
            />
            {activeSection === 'aiTagging' && (
              <AiTaggingSection />
            )}
          </div>


          {/* ── Schedule ── */}
          <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
            <div className="flex items-center justify-between">
              <div className="flex-1">
                <SectionHeader
                  title={t('settings.schedule')}
                  sectionKey="schedule"
                  activeSection={activeSection}
                  onToggle={toggleSection}
                />
              </div>
              <div className="pr-5">
                <CalendarClock size={14} className="text-vault-text-muted" />
              </div>
            </div>
            {activeSection === 'schedule' && <ScanScheduleSection />}
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
                  title={t('settings.apiTokensSection')}
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
                    {t('settings.createToken')}
                  </p>
                  <div className="space-y-3">
                    <div>
                      <label className="block text-xs text-vault-text-muted mb-1">{t('settings.tokenName')}</label>
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
                <div className="mt-5 pt-4 border-t border-vault-border">
                  <div className="flex items-center justify-between mb-2">
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
