'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import Link from 'next/link'
import { useLocale } from '@/components/LocaleProvider'
import { SUPPORTED_LOCALES, type Locale, formatBytes } from '@/lib/i18n'
import { ChevronUp, ChevronDown, Shield, Monitor, CalendarClock, Key } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { useAuth } from '@/hooks/useAuth'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { t } from '@/lib/i18n'
import { Copy, BookOpen, X, Plus, Tag, ScanLine } from 'lucide-react'
import { useRescanLibrary, useRescanStatus, useCancelRescan } from '@/hooks/useImport'
import { TaskList } from '@/components/ScheduledTasks/TaskList'
import { loadReaderSettings, saveReaderSettings } from '@/components/Reader/hooks'
import { loadSWCacheConfig, saveSWCacheConfig, type SWCacheConfig, DEFAULT_SW_CACHE_CONFIG } from '@/lib/swCacheConfig'
import { BottomTabConfig } from '@/components/BottomTabConfig'
import { DashboardLinksConfig } from '@/components/DashboardLinksConfig'
import type { ViewMode, ScaleMode, ReadingDirection } from '@/components/Reader/types'
import type {
  SystemHealth,
  SystemInfo,
  SessionInfo,
  ApiTokenInfo,
  BlockedTag,
  CacheStats,
  RateLimitSettings,
  SiteRateConfig,
  StorageInfo,
} from '@/lib/types'

type SectionKey =
  | 'system'
  | 'account'
  | 'browse'
  | 'bottomTab'
  | 'dashboardLinks'
  | 'security'
  | 'features'
  | 'rateLimits'
  | 'apiTokens'
  | 'reader'
  | 'blockedTags'
  | 'aiTagging'
  | 'schedule'
  | 'browserCache'

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
  openSections,
  onToggle,
}: {
  title: string
  sectionKey: SectionKey
  openSections: Set<SectionKey>
  onToggle: (key: SectionKey) => void
}) {
  const isOpen = openSections.has(sectionKey)
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

function ToggleRow({
  label,
  description,
  checked,
  onChange,
  disabled,
}: {
  label: string
  description: string
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
}) {
  return (
    <div className="flex items-center justify-between py-3">
      <div className="flex-1 min-w-0 pr-4">
        <p className="text-sm font-medium text-vault-text">{label}</p>
        <p className="text-xs text-vault-text-muted mt-0.5">{description}</p>
      </div>
      <button
        onClick={() => onChange(!checked)}
        disabled={disabled}
        className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none ${
          checked ? 'bg-green-600' : 'bg-vault-border'
        } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
      >
        <span
          className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ${
            checked ? 'translate-x-4' : 'translate-x-0'
          }`}
        />
      </button>
    </div>
  )
}

// ── AI Tagging sub-component ──────────────────────────────────────────

function AiTaggingSection() {
  const [isRetagging, setIsRetagging] = useState(false)
  const [isImporting, setIsImporting] = useState(false)

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

  const handleImportEhtag = async () => {
    setIsImporting(true)
    try {
      const result = await api.tags.importEhtag()
      toast.success(t('settings.importEhtagSuccess', { count: result.count }))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.importEhtagFailed'))
    } finally {
      setIsImporting(false)
    }
  }

  return (
    <div className="px-5 pb-5 border-t border-vault-border">
      <p className="text-xs text-vault-text-muted mt-4 mb-4">
        {t('settings.aiTaggingDesc')}
      </p>
      <div className="flex flex-wrap gap-3">
        <button
          onClick={handleRetagAll}
          disabled={isRetagging}
          className="px-4 py-2 bg-purple-900/30 border border-purple-700/50 text-purple-400 hover:bg-purple-900/50 rounded text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isRetagging ? t('settings.retagging') : t('settings.retagAll')}
        </button>
        <div>
          <button
            onClick={handleImportEhtag}
            disabled={isImporting}
            className="px-4 py-2 bg-blue-900/30 border border-blue-700/50 text-blue-400 hover:bg-blue-900/50 rounded text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {isImporting ? t('settings.importingEhtag') : t('settings.importEhtag')}
          </button>
          <p className="text-[10px] text-vault-text-muted mt-1">
            {t('settings.importEhtagDesc')}
          </p>
        </div>
      </div>
    </div>
  )
}

// ── Rate Limits sub-component ─────────────────────────────────────────

const SITE_LABELS: Record<string, string> = {
  ehentai: 'E-Hentai',
  pixiv: 'Pixiv',
  gallery_dl: 'gallery-dl',
}

function SiteRateRow({
  label,
  value,
  min,
  max,
  onChange,
}: {
  label: string
  value: number
  min: number
  max: number
  onChange: (v: number) => void
}) {
  return (
    <div className="flex items-center justify-between py-2">
      <span className="text-sm text-vault-text-muted">{label}</span>
      <div className="flex items-center gap-2 shrink-0">
        <input
          type="range"
          min={min}
          max={max}
          step={1}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className="w-24 accent-vault-accent"
        />
        <span className="text-xs tabular-nums text-vault-text-secondary w-4 text-right">
          {value}
        </span>
      </div>
    </div>
  )
}

function DelayRow({
  label,
  suffix,
  value,
  onChange,
}: {
  label: string
  suffix: string
  value: number
  onChange: (v: number) => void
}) {
  return (
    <div className="flex items-center justify-between py-2">
      <span className="text-sm text-vault-text-muted">{label}</span>
      <div className="flex items-center gap-2 shrink-0">
        <input
          type="number"
          min={0}
          max={10000}
          step={100}
          value={value}
          onChange={(e) => onChange(Number(e.target.value))}
          className="w-20 bg-vault-input border border-vault-border rounded px-2 py-1.5 text-sm text-vault-text focus:outline-none focus:border-vault-accent text-right"
        />
        <span className="text-xs text-vault-text-muted w-6">{suffix}</span>
      </div>
    </div>
  )
}

function RateLimitsSection() {
  const [data, setData] = useState<RateLimitSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [overrideLoading, setOverrideLoading] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const pendingPatchRef = useRef<Record<string, any>>({})
  const [subDelay, setSubDelay] = useState(500)
  const [subBatchMax, setSubBatchMax] = useState(0)

  useEffect(() => {
    api.settings.getRateLimits()
      .then(setData)
      .catch(() => toast.error(t('common.failedToLoad')))
      .finally(() => setLoading(false))
    api.settings.getFeatures()
      .then((f: any) => {
        setSubDelay(f.subscription_enqueue_delay_ms ?? 500)
        setSubBatchMax(f.subscription_batch_max ?? 0)
        setUpdateCheckDays(f.gallery_update_check_days ?? -1)
      })
      .catch(() => {})
  }, [])

  const debouncedPatch = useCallback((patch: Parameters<typeof api.settings.patchRateLimits>[0]) => {
    if (patch.sites) {
      pendingPatchRef.current.sites = pendingPatchRef.current.sites || {}
      for (const [site, cfg] of Object.entries(patch.sites)) {
        pendingPatchRef.current.sites[site] = {
          ...(pendingPatchRef.current.sites[site] || {}),
          ...cfg,
        }
      }
    }
    if (patch.schedule) {
      pendingPatchRef.current.schedule = {
        ...(pendingPatchRef.current.schedule || {}),
        ...patch.schedule,
      }
    }
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(async () => {
      const merged = pendingPatchRef.current
      pendingPatchRef.current = {}
      try {
        const updated = await api.settings.patchRateLimits(merged)
        setData(updated)
      } catch (err) {
        toast.error(err instanceof Error ? err.message : t('common.failedToSave'))
      }
    }, 300)
  }, [])

  const handleSiteChange = useCallback(
    (site: string, field: keyof SiteRateConfig, value: number) => {
      setData((prev) => {
        if (!prev) return prev
        const updated: RateLimitSettings = {
          ...prev,
          sites: {
            ...prev.sites,
            [site]: { ...prev.sites[site], [field]: value },
          },
        }
        debouncedPatch({ sites: { [site]: { [field]: value } } })
        return updated
      })
    },
    [debouncedPatch],
  )

  const handleScheduleChange = useCallback(
    (field: keyof RateLimitSettings['schedule'], value: boolean | number | string) => {
      setData((prev) => {
        if (!prev) return prev
        const updated: RateLimitSettings = {
          ...prev,
          schedule: { ...prev.schedule, [field]: value },
        }
        debouncedPatch({ schedule: { [field]: value } as Partial<RateLimitSettings['schedule']> })
        return updated
      })
    },
    [debouncedPatch],
  )

  const handleOverride = useCallback(async () => {
    if (!data) return
    const unlocked = !data.override_active
    setOverrideLoading(true)
    try {
      await api.settings.setRateLimitOverride(unlocked)
      setData((prev) => prev ? { ...prev, override_active: unlocked } : prev)
      toast.success(t('common.saved'))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToSave'))
    } finally {
      setOverrideLoading(false)
    }
  }, [data])

  const [updateCheckDays, setUpdateCheckDays] = useState(-1)
  const updateCheckDebounce = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const subDelayDebounce = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const subBatchDebounce = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const handleSubDelayChange = useCallback((v: number) => {
    setSubDelay(v)
    clearTimeout(subDelayDebounce.current)
    subDelayDebounce.current = setTimeout(async () => {
      try {
        await api.settings.setFeatureValue('subscription_enqueue_delay_ms', Math.max(100, v))
        toast.success(t('common.saved'))
      } catch { toast.error(t('common.failedToSave')) }
    }, 500)
  }, [])

  const handleSubBatchMaxChange = useCallback((v: number) => {
    setSubBatchMax(v)
    clearTimeout(subBatchDebounce.current)
    subBatchDebounce.current = setTimeout(async () => {
      try {
        await api.settings.setFeatureValue('subscription_batch_max', Math.max(0, v))
        toast.success(t('common.saved'))
      } catch { toast.error(t('common.failedToSave')) }
    }, 500)
  }, [])

  const handleUpdateCheckDaysChange = useCallback((v: number) => {
    setUpdateCheckDays(v)
    clearTimeout(updateCheckDebounce.current)
    updateCheckDebounce.current = setTimeout(async () => {
      try {
        await api.settings.setFeatureValue('gallery_update_check_days', Math.max(-1, v))
        toast.success(t('common.saved'))
      } catch { toast.error(t('common.failedToSave')) }
    }, 500)
  }, [])

  if (loading) {
    return (
      <div className="px-5 pb-5 border-t border-vault-border flex justify-center py-8">
        <LoadingSpinner />
      </div>
    )
  }

  if (!data) {
    return (
      <div className="px-5 pb-5 border-t border-vault-border">
        <p className="text-xs text-vault-text-muted mt-4">{t('common.failedToLoad')}</p>
      </div>
    )
  }

  const siteOrder = ['ehentai', 'pixiv', 'gallery_dl']
  const orderedSites = [
    ...siteOrder.filter((s) => s in data.sites),
    ...Object.keys(data.sites).filter((s) => !siteOrder.includes(s)),
  ]

  return (
    <div className="px-5 pb-5 border-t border-vault-border space-y-5 mt-4">
      <p className="text-xs text-vault-text-muted">{t('settings.rateLimitsDesc')}</p>

      {/* Per-site config */}
      {orderedSites.map((site) => {
        const cfg = data.sites[site]
        const label = SITE_LABELS[site] ?? site
        const isGalleryDl = site === 'gallery_dl'
        const isPixiv = site === 'pixiv'
        return (
          <div key={site}>
            <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-1">{label}</p>
            <div className="bg-vault-input border border-vault-border rounded-lg px-3 py-1 space-y-0 divide-y divide-vault-border/50">
              <SiteRateRow
                label={t('settings.rateLimitsJobConcurrency')}
                value={cfg.concurrency}
                min={1}
                max={10}
                onChange={(v) => handleSiteChange(site, 'concurrency', v)}
              />
              {!isGalleryDl && !isPixiv && cfg.image_concurrency !== null && (
                <SiteRateRow
                  label={t('settings.rateLimitsImageConcurrency')}
                  value={cfg.image_concurrency ?? 1}
                  min={1}
                  max={10}
                  onChange={(v) => handleSiteChange(site, 'image_concurrency', v)}
                />
              )}
              {isPixiv ? (
                <>
                  <DelayRow
                    label={t('settings.rateLimitsPageDelay')}
                    suffix={t('settings.rateLimitsMs')}
                    value={cfg.page_delay_ms ?? 500}
                    onChange={(v) => handleSiteChange(site, 'page_delay_ms', v)}
                  />
                  <DelayRow
                    label={t('settings.rateLimitsPaginationDelay')}
                    suffix={t('settings.rateLimitsMs')}
                    value={cfg.pagination_delay_ms ?? 1000}
                    onChange={(v) => handleSiteChange(site, 'pagination_delay_ms', v)}
                  />
                  <DelayRow
                    label={t('settings.rateLimitsIllustDelay')}
                    suffix={t('settings.rateLimitsMs')}
                    value={cfg.illust_delay_ms ?? 2000}
                    onChange={(v) => handleSiteChange(site, 'illust_delay_ms', v)}
                  />
                </>
              ) : (
                <DelayRow
                  label={isGalleryDl ? t('settings.rateLimitsRequestDelay') : t('settings.rateLimitsPageDelay')}
                  suffix={t('settings.rateLimitsMs')}
                  value={cfg.delay_ms ?? 0}
                  onChange={(v) => handleSiteChange(site, 'delay_ms', v)}
                />
              )}
              {isGalleryDl && (
                <div className="py-2">
                  <p className="text-xs text-vault-text-muted italic">
                    {t('settings.rateLimitsManagedInternally')}
                  </p>
                </div>
              )}
            </div>
          </div>
        )
      })}

      {/* Schedule */}
      <div>
        <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-1">
          {t('settings.rateLimitsSchedule')}
        </p>
        <div className="bg-vault-input border border-vault-border rounded-lg px-3 py-2 space-y-3">
          {/* Enable toggle */}
          <div className="flex items-center justify-between">
            <span className="text-sm text-vault-text">{t('settings.rateLimitsScheduleEnable')}</span>
            <button
              onClick={() => handleScheduleChange('enabled', !data.schedule.enabled)}
              className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none ${
                data.schedule.enabled ? 'bg-green-600' : 'bg-vault-border'
              }`}
            >
              <span
                className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ${
                  data.schedule.enabled ? 'translate-x-4' : 'translate-x-0'
                }`}
              />
            </button>
          </div>

          {/* Window */}
          <div className="flex items-center justify-between">
            <span className="text-sm text-vault-text">{t('settings.rateLimitsScheduleWindow')}</span>
            <div className="flex items-center gap-2">
              <select
                value={data.schedule.start_hour}
                onChange={(e) => handleScheduleChange('start_hour', Number(e.target.value))}
                className="bg-vault-bg border border-vault-border rounded px-2 py-1 text-sm text-vault-text focus:outline-none focus:border-vault-accent"
              >
                {Array.from({ length: 24 }, (_, i) => (
                  <option key={i} value={i}>{String(i).padStart(2, '0')}</option>
                ))}
              </select>
              <span className="text-xs text-vault-text-muted">{t('settings.rateLimitsScheduleTo')}</span>
              <select
                value={data.schedule.end_hour}
                onChange={(e) => handleScheduleChange('end_hour', Number(e.target.value))}
                className="bg-vault-bg border border-vault-border rounded px-2 py-1 text-sm text-vault-text focus:outline-none focus:border-vault-accent"
              >
                {Array.from({ length: 24 }, (_, i) => (
                  <option key={i} value={i}>{String(i).padStart(2, '0')}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Mode */}
          <div className="flex items-center justify-between">
            <span className="text-sm text-vault-text">{t('settings.rateLimitsScheduleMode')}</span>
            <select
              value={data.schedule.mode}
              onChange={(e) => handleScheduleChange('mode', e.target.value as 'full_speed' | 'standard')}
              className="bg-vault-bg border border-vault-border rounded px-2 py-1 text-sm text-vault-text focus:outline-none focus:border-vault-accent"
            >
              <option value="full_speed">{t('settings.rateLimitsScheduleFullSpeed')}</option>
              <option value="standard">{t('settings.rateLimitsScheduleStandard')}</option>
            </select>
          </div>

          {/* Status */}
          <div className="flex items-center justify-between">
            <span className="text-xs text-vault-text-muted uppercase tracking-wide">
              {t('settings.rateLimitsScheduleStatus')}
            </span>
            <span
              className={`inline-flex items-center gap-1.5 text-xs ${
                data.schedule.enabled && data.schedule_active
                  ? 'text-green-400'
                  : data.schedule.enabled
                    ? 'text-amber-400'
                    : 'text-vault-text-muted'
              }`}
            >
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  data.schedule.enabled && data.schedule_active
                    ? 'bg-green-500'
                    : data.schedule.enabled
                      ? 'bg-amber-500'
                      : 'bg-vault-text-muted'
                }`}
              />
              {data.schedule.enabled && data.schedule_active
                ? t('settings.rateLimitsScheduleActive')
                : data.schedule.enabled
                  ? t('settings.rateLimitsScheduleOutsideWindow')
                  : t('settings.rateLimitsScheduleDisabled')}
            </span>
          </div>
        </div>
      </div>

      {/* Manual Override */}
      <div>
        <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-1">
          {t('settings.rateLimitsOverride')}
        </p>
        <div className="bg-vault-input border border-vault-border rounded-lg px-3 py-3 flex items-center justify-between gap-4">
          <div className="space-y-0.5">
            <span className="text-xs text-vault-text-muted">
              {data.override_active
                ? t('settings.rateLimitsStatusFullSpeed')
                : t('settings.rateLimitsStatusNormal')}
            </span>
            {data.override_active && (
              <p className="text-xs text-vault-text-muted/60">
                {t('settings.rateLimitsOverrideCondition')}
              </p>
            )}
          </div>
          <button
            onClick={handleOverride}
            disabled={overrideLoading}
            className={`px-4 py-2 rounded text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed shrink-0 ${
              data.override_active
                ? 'bg-amber-600/20 border border-amber-500/40 text-amber-400 hover:bg-amber-600/30'
                : 'bg-green-600/20 border border-green-500/40 text-green-400 hover:bg-green-600/30'
            }`}
          >
            {data.override_active
              ? t('settings.rateLimitsRestore')
              : t('settings.rateLimitsUnlock')}
          </button>
        </div>
      </div>

      {/* Subscription Enqueue */}
      <div>
        <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-1">
          {t('settings.subscriptionEnqueue')}
        </p>
        <div className="bg-vault-input border border-vault-border rounded-lg px-3 py-1 space-y-0 divide-y divide-vault-border/50">
          <DelayRow
            label={t('settings.subscriptionEnqueueDelay')}
            suffix={t('settings.rateLimitsMs')}
            value={subDelay}
            onChange={handleSubDelayChange}
          />
          <div className="flex items-center justify-between py-2">
            <span className="text-sm text-vault-text-muted">{t('settings.subscriptionBatchMax')}</span>
            <div className="flex items-center gap-2 shrink-0">
              <input
                type="number"
                min={0}
                max={9999}
                step={10}
                value={subBatchMax}
                onChange={(e) => handleSubBatchMaxChange(Number(e.target.value))}
                className="w-20 bg-vault-input border border-vault-border rounded px-2 py-1.5 text-sm text-vault-text focus:outline-none focus:border-vault-accent text-right"
              />
              <span className="text-xs text-vault-text-muted w-6"></span>
            </div>
          </div>
        </div>
        <p className="text-[10px] text-vault-text-muted mt-1">{t('settings.subscriptionEnqueueDesc')}</p>
      </div>

      {/* Gallery Metadata Auto-Check */}
      <div>
        <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-1">
          {t('settings.galleryUpdateCheckDays')}
        </p>
        <div className="bg-vault-input border border-vault-border rounded-lg px-3 py-2 flex items-center gap-2">
          <input
            type="number"
            min={-1}
            max={365}
            step={1}
            value={updateCheckDays}
            onChange={(e) => handleUpdateCheckDaysChange(Number(e.target.value))}
            className="w-20 bg-vault-input border border-vault-border rounded px-2 py-1.5 text-sm text-vault-text focus:outline-none focus:border-vault-accent text-right"
          />
          <span className="text-xs text-vault-text-muted">{t('common.days')}</span>
        </div>
        <p className="text-[10px] text-vault-text-muted mt-1">{t('settings.galleryUpdateCheckDaysDesc')}</p>
      </div>
    </div>
  )
}

// ── Scheduled Tasks sub-component ────────────────────────────────────

function ScheduledTasksSection() {
  const { trigger: rescan, isMutating: rescanning } = useRescanLibrary()
  const { data: rescanStatus } = useRescanStatus()
  const { trigger: cancelRescan, isMutating: cancelling } = useCancelRescan()

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

  return (
    <div className="px-5 pb-5 border-t border-vault-border">
      <p className="text-xs text-vault-text-muted mt-4 mb-4">
        {t('settings.tasks.desc')}
      </p>

      {/* Rescan Library button + progress */}
      <div className="mb-5 pb-4 border-b border-vault-border">
        <div className="flex items-center justify-between mb-2">
          <div>
            <p className="text-sm text-vault-text">{t('settings.media.rescan')}</p>
            <p className="text-xs text-vault-text-muted mt-0.5">{t('settings.media.rescan.desc')}</p>
          </div>
          {isRunning ? (
            <button
              onClick={async () => {
                try {
                  await cancelRescan()
                  toast.success(t('settings.media.rescan.cancelled'))
                } catch {
                  toast.error(t('common.failedToLoad'))
                }
              }}
              disabled={cancelling}
              className="px-3 py-1.5 rounded text-xs font-medium bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-colors"
            >
              {cancelling ? t('settings.media.rescan.cancelling') : t('settings.media.rescan.cancel')}
            </button>
          ) : (
            <button
              onClick={handleRescan}
              disabled={rescanning}
              className="px-3 py-1.5 rounded text-xs font-medium bg-vault-accent/20 text-vault-accent hover:bg-vault-accent/30 transition-colors flex items-center gap-1.5"
            >
              <ScanLine size={14} />
              {t('settings.media.rescan')}
            </button>
          )}
        </div>
        {isRunning && processed != null && total != null && (
          <div className="space-y-1">
            <div className="w-full bg-vault-input rounded-full h-1.5">
              <div
                className="bg-vault-accent rounded-full h-1.5 transition-all"
                style={{ width: `${total > 0 ? (processed / total) * 100 : 0}%` }}
              />
            </div>
            <p className="text-xs text-vault-text-muted">
              {t('settings.media.rescan.running', { processed: String(processed), total: String(total) })}
            </p>
          </div>
        )}
      </div>

      {/* Scheduled Tasks list — delegated to shared TaskList component */}
      <TaskList pollWhileRunning={false} />
    </div>
  )
}

// ── Browse Settings sub-component ────────────────────────────────────

function BrowseSettings() {
  const [historyEnabled, setHistoryEnabled] = useState(
    () => typeof window !== 'undefined' && localStorage.getItem('eh_search_history_enabled') !== 'false',
  )
  const [loadMode, setLoadMode] = useState(
    () =>
      typeof window !== 'undefined'
        ? localStorage.getItem('browse_load_mode') || 'pagination'
        : 'pagination',
  )
  const [perPage, setPerPage] = useState(
    () =>
      typeof window !== 'undefined' ? localStorage.getItem('browse_per_page') || '25' : '25',
  )
  const [browseHistoryEnabled, setBrowseHistoryEnabled] = useState(
    () => typeof window !== 'undefined' && localStorage.getItem('history_enabled') !== 'false',
  )

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
            const next = !historyEnabled
            localStorage.setItem('eh_search_history_enabled', next ? 'true' : 'false')
            if (!next) localStorage.removeItem('eh_search_history')
            setHistoryEnabled(next)
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
              setLoadMode('pagination')
            }}
            className={`px-3 py-1.5 text-xs transition-colors ${loadMode === 'pagination' ? 'bg-vault-accent text-white' : 'text-vault-text-muted hover:text-vault-text'}`}
          >
            {t('settings.pagination')}
          </button>
          <button
            onClick={() => {
              localStorage.setItem('browse_load_mode', 'scroll')
              setLoadMode('scroll')
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
            setPerPage(e.target.value)
          }}
          className="bg-vault-input border border-vault-border rounded px-3 py-1.5 text-sm text-vault-text focus:outline-none"
        >
          <option value="25">25</option>
          <option value="50">50</option>
          <option value="100">100</option>
        </select>
      </div>

      {/* Browse History toggle */}
      <div className="mt-5 flex items-center justify-between">
        <div>
          <p className="text-sm text-vault-text">{t('settings.browseHistory')}</p>
          <p className="text-xs text-vault-text-muted mt-0.5">{t('settings.browseHistoryDesc')}</p>
        </div>
        <button
          onClick={() => {
            const next = !browseHistoryEnabled
            localStorage.setItem('history_enabled', next ? 'true' : 'false')
            setBrowseHistoryEnabled(next)
          }}
          className={`relative w-11 h-6 rounded-full transition-colors ${browseHistoryEnabled ? 'bg-vault-accent' : 'bg-vault-border'}`}
        >
          <span
            className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform ${browseHistoryEnabled ? 'translate-x-5' : ''}`}
          />
        </button>
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
  const { locale, setLocale: changeLocale } = useLocale()
  const [openSections, setOpenSections] = useState<Set<SectionKey>>(new Set(['system']))

  // System info
  const [health, setHealth] = useState<SystemHealth | null>(null)
  const [systemInfo, setSystemInfo] = useState<SystemInfo | null>(null)
  const [systemLoading, setSystemLoading] = useState(false)
  const [systemLoaded, setSystemLoaded] = useState(false)

  // Feature toggles
  const [features, setFeatures] = useState<Record<string, boolean>>({})
  const [featuresLoading, setFeaturesLoading] = useState(true)

  // Cache stats
  const [cacheStats, setCacheStats] = useState<CacheStats | null>(null)
  const [cacheLoading, setCacheLoading] = useState(false)
  const [cacheClearingAll, setCacheClearingAll] = useState(false)
  const [cacheClearingCategory, setCacheClearingCategory] = useState<string | null>(null)

  // Storage info
  const [storageInfo, setStorageInfo] = useState<StorageInfo | null>(null)

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

  // Browser Cache (SW)
  const [swCacheConfig, setSwCacheConfig] = useState<SWCacheConfig>(DEFAULT_SW_CACHE_CONFIG)

  const toggleSection = useCallback((key: SectionKey) => {
    setOpenSections((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }, [])

  // System: Load health + info + cache + storage
  const handleLoadSystem = useCallback(async () => {
    setSystemLoading(true)
    try {
      const [h, i, cs, st] = await Promise.all([
        api.system.health(),
        api.system.info(),
        api.system.getCache(),
        api.system.getStorage().catch(() => null),
      ])
      setHealth(h)
      setSystemInfo(i)
      setCacheStats(cs)
      setStorageInfo(st)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.systemLoadFailed'))
    } finally {
      setSystemLoading(false)
      setSystemLoaded(true)
    }
  }, [])

  // Features: Load
  const handleLoadFeatures = useCallback(async () => {
    setFeaturesLoading(true)
    try {
      const data = await api.settings.getFeatures()
      setFeatures(data as unknown as Record<string, boolean>)
    } catch {
      // silently fail — toggles will use defaults
    } finally {
      setFeaturesLoading(false)
    }
  }, [])

  // Features: Toggle
  const handleFeatureToggle = useCallback(async (feature: string, enabled: boolean) => {
    try {
      await api.settings.setFeature(feature, enabled)
      setFeatures((prev) => ({ ...prev, [feature]: enabled }))
      toast.success(t('common.saved'))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToSave'))
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
      toast.success(t('settings.tokenCreated'))
      setNewTokenName('')
      setNewTokenExpiry('')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.failedCreateToken'))
    } finally {
      setTokenCreating(false)
    }
  }, [newTokenName, newTokenExpiry])

  // API Tokens: Delete
  const handleDeleteToken = useCallback(async (tokenId: string) => {
    if (!window.confirm(t('settings.confirmDeleteToken'))) return
    setDeletingTokenId(tokenId)
    try {
      await api.tokens.delete(tokenId)
      setApiTokens((prev) => prev.filter((t) => t.id !== tokenId))
      toast.success(t('settings.tokenRevoked'))
    } catch {
      toast.error(t('settings.failedRevokeToken'))
    } finally {
      setDeletingTokenId(null)
    }
  }, [])

  useEffect(() => { setSwCacheConfig(loadSWCacheConfig()) }, [])

  const handleSWCacheChange = useCallback((key: keyof SWCacheConfig, value: number) => {
    setSwCacheConfig((prev) => ({ ...prev, [key]: value }))
  }, [])

  const handleSWCacheBlur = useCallback(() => {
    setSwCacheConfig((prev) => {
      saveSWCacheConfig(prev)
      return prev
    })
    toast.success(t('common.saved'))
  }, [])

  const handleClearBrowserCache = useCallback(async () => {
    if (!window.confirm(t('settings.clearBrowserCacheConfirm'))) return
    const names = await caches.keys()
    await Promise.all(names.map((name) => caches.delete(name)))
    toast.success(t('settings.browserCacheCleared'))
    window.location.reload()
  }, [])

  useEffect(() => {
    if (openSections.has('system') && !systemLoaded && !systemLoading) {
      handleLoadSystem()
    }
    if (openSections.has('account')) {
      if (!profileLoaded) handleLoadProfile()
      if (sessions.length === 0 && !sessionsLoading) handleLoadSessions()
    }
    if (openSections.has('apiTokens') && !apiTokensLoaded && !apiTokensLoading) {
      handleLoadApiTokens()
    }
    if (openSections.has('blockedTags') && !blockedTagsLoaded && !blockedTagsLoading) {
      handleLoadBlockedTags()
    }
    if ((openSections.has('security') || openSections.has('features')) && featuresLoading && Object.keys(features).length === 0) {
      handleLoadFeatures()
    }
  }, [
    openSections,
    systemLoaded,
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
    features,
    featuresLoading,
    handleLoadFeatures,
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
    <div className="max-w-2xl">
        <h1 className="text-2xl font-bold mb-6 text-vault-text">{t('settings.title')}</h1>

        {/* ── Credentials link ── */}
        <Link
          href="/credentials"
          className="flex items-center gap-2 mb-4 px-4 py-2.5 bg-vault-card border border-vault-border rounded-xl text-sm text-vault-text-secondary hover:text-vault-accent hover:border-vault-accent/50 transition-colors w-full"
        >
          <Key size={16} />
          <span>{t('credentials.manageCredentials')}</span>
        </Link>

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

          {/* ── System Info ── */}
          <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
            <SectionHeader
              title={t('settings.system')}
              sectionKey="system"
              openSections={openSections}
              onToggle={toggleSection}
            />

            {openSections.has('system') && (
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

                    {/* Storage */}
                    {storageInfo && storageInfo.mounts.length > 0 && (
                      <div>
                        <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">
                          {t('settings.storage')}
                        </p>
                        <div className="bg-vault-input border border-vault-border rounded-lg divide-y divide-vault-border">
                          {storageInfo.mounts.map((mount) => {
                            const barColor =
                              mount.percent > 90
                                ? 'bg-red-500'
                                : mount.percent > 70
                                  ? 'bg-yellow-500'
                                  : 'bg-green-500'
                            return (
                              <div key={mount.path} className="px-3 py-2.5">
                                <div className="flex justify-between items-center mb-1.5">
                                  <span className="text-sm text-vault-text">{mount.label}</span>
                                  <span className="text-xs text-vault-text-muted font-mono">
                                    {formatBytes(mount.used)} / {formatBytes(mount.total)}
                                  </span>
                                </div>
                                <div className="w-full h-2 bg-vault-bg rounded-full overflow-hidden">
                                  <div
                                    className={`h-full rounded-full transition-all ${barColor}`}
                                    style={{ width: `${Math.min(mount.percent, 100)}%` }}
                                  />
                                </div>
                                <div className="flex justify-between mt-1">
                                  <span className="text-xs text-vault-text-muted">
                                    {mount.percent}% {t('settings.storageUsed').toLowerCase()}
                                  </span>
                                  <span className="text-xs text-vault-text-muted">
                                    {formatBytes(mount.free)} {t('settings.storageFree').toLowerCase()}
                                  </span>
                                </div>
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    )}

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

          {/* ── Security ── */}
          <div className="bg-vault-card border border-vault-border rounded-lg overflow-hidden">
            <SectionHeader
              title={t('settings.security')}
              sectionKey="security"
              openSections={openSections}
              onToggle={toggleSection}
            />
            {openSections.has('security') && (
              <div className="px-5 pb-5 space-y-1 divide-y divide-vault-border">
                <ToggleRow
                  label={t('settings.csrfProtection')}
                  description={t('settings.csrfDesc')}
                  checked={features.csrf_enabled ?? true}
                  onChange={(v) => handleFeatureToggle('csrf_enabled', v)}
                  disabled={featuresLoading}
                />
                <ToggleRow
                  label={t('settings.rateLimiting')}
                  description={t('settings.rateLimitDesc')}
                  checked={features.rate_limit_enabled ?? true}
                  onChange={(v) => handleFeatureToggle('rate_limit_enabled', v)}
                  disabled={featuresLoading}
                />
              </div>
            )}
          </div>

          {/* ── Features ── */}
          <div className="bg-vault-card border border-vault-border rounded-lg overflow-hidden">
            <SectionHeader
              title={t('settings.features')}
              sectionKey="features"
              openSections={openSections}
              onToggle={toggleSection}
            />
            {openSections.has('features') && (
              <div className="px-5 pb-5">
                {/* Service Toggles */}
                <div className="space-y-1 divide-y divide-vault-border">
                  <ToggleRow
                    label={t('settings.opdsServer')}
                    description={t('settings.opdsDesc')}
                    checked={features.opds_enabled ?? true}
                    onChange={(v) => handleFeatureToggle('opds_enabled', v)}
                    disabled={featuresLoading}
                  />
                  <ToggleRow
                    label={t('settings.externalApi')}
                    description={t('settings.externalApiDesc')}
                    checked={features.external_api_enabled ?? true}
                    onChange={(v) => handleFeatureToggle('external_api_enabled', v)}
                    disabled={featuresLoading}
                  />
                  <ToggleRow
                    label={t('settings.aiTagging')}
                    description={t('settings.aiTaggingToggleDesc')}
                    checked={features.ai_tagging_enabled ?? false}
                    onChange={(v) => handleFeatureToggle('ai_tagging_enabled', v)}
                    disabled={featuresLoading}
                  />
                </div>

                {/* Download Sources */}
                <h3 className="text-xs text-vault-text-muted uppercase tracking-wide mt-5 mb-2">
                  {t('settings.downloadSources')}
                </h3>
                <div className="space-y-1 divide-y divide-vault-border">
                  <ToggleRow
                    label={t('settings.downloadEh')}
                    description={t('settings.downloadEhDesc')}
                    checked={features.download_eh_enabled ?? true}
                    onChange={(v) => handleFeatureToggle('download_eh_enabled', v)}
                    disabled={featuresLoading}
                  />
                  <ToggleRow
                    label={t('settings.downloadPixiv')}
                    description={t('settings.downloadPixivDesc')}
                    checked={features.download_pixiv_enabled ?? true}
                    onChange={(v) => handleFeatureToggle('download_pixiv_enabled', v)}
                    disabled={featuresLoading}
                  />
                  <ToggleRow
                    label={t('settings.downloadGalleryDl')}
                    description={t('settings.downloadGalleryDlDesc')}
                    checked={features.download_gallery_dl_enabled ?? true}
                    onChange={(v) => handleFeatureToggle('download_gallery_dl_enabled', v)}
                    disabled={featuresLoading}
                  />
                </div>
              </div>
            )}
          </div>

          {/* ── Rate Limits ── */}
          <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
            <SectionHeader
              title={t('settings.rateLimits')}
              sectionKey="rateLimits"
              openSections={openSections}
              onToggle={toggleSection}
            />
            {openSections.has('rateLimits') && <RateLimitsSection />}
          </div>

          {/* ── Browse Settings ── */}
          <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
            <SectionHeader
              title={t('settings.browse')}
              sectionKey="browse"
              openSections={openSections}
              onToggle={toggleSection}
            />
            {openSections.has('browse') && (
              <BrowseSettings />
            )}
          </div>

          {/* ── Bottom Tab Bar ── */}
          <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
            <SectionHeader
              title={t('settings.bottomTab')}
              sectionKey="bottomTab"
              openSections={openSections}
              onToggle={toggleSection}
            />
            {openSections.has('bottomTab') && <BottomTabConfig />}
          </div>

          {/* ── Dashboard Quick Links ── */}
          <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
            <SectionHeader
              title={t('settings.dashboardLinks')}
              sectionKey="dashboardLinks"
              openSections={openSections}
              onToggle={toggleSection}
            />
            {openSections.has('dashboardLinks') && <DashboardLinksConfig />}
          </div>

          {/* ── Blocked Tags ── */}
          <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
            <div className="flex items-center justify-between">
              <div className="flex-1">
                <SectionHeader
                  title={t('settings.blockedTags')}
                  sectionKey="blockedTags"
                  openSections={openSections}
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

            {openSections.has('blockedTags') && (
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
              openSections={openSections}
              onToggle={toggleSection}
            />
            {openSections.has('aiTagging') && (
              <AiTaggingSection />
            )}
          </div>


          {/* ── Schedule ── */}
          <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
            <div className="flex items-center justify-between">
              <div className="flex-1">
                <SectionHeader
                  title={t('settings.tasks')}
                  sectionKey="schedule"
                  openSections={openSections}
                  onToggle={toggleSection}
                />
              </div>
              <div className="pr-5">
                <CalendarClock size={14} className="text-vault-text-muted" />
              </div>
            </div>
            {openSections.has('schedule') && <ScheduledTasksSection />}
          </div>

          {/* ── Reader Settings ── */}
          <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
            <div className="flex items-center justify-between">
              <div className="flex-1">
                <SectionHeader
                  title={t('settings.reader')}
                  sectionKey="reader"
                  openSections={openSections}
                  onToggle={toggleSection}
                />
              </div>
              <div className="pr-5">
                <BookOpen size={14} className="text-vault-text-muted" />
              </div>
            </div>
            {openSections.has('reader') && (
              <ReaderSettingsSection
                onForceRerender={() => {
                  setOpenSections((prev) => {
                    const next = new Set(prev)
                    next.delete('reader')
                    return next
                  })
                  setTimeout(() => setOpenSections((prev) => new Set([...prev, 'reader'])), 0)
                }}
              />
            )}
          </div>

          {/* ── Browser Cache ── */}
          <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
            <SectionHeader
              title={t('settings.browserCache')}
              sectionKey="browserCache"
              openSections={openSections}
              onToggle={toggleSection}
            />
            {openSections.has('browserCache') && (
              <div className="px-5 pb-5 border-t border-vault-border">
                <p className="text-xs text-vault-text-muted mt-4 mb-4">
                  {t('settings.browserCacheDesc')}
                </p>

                <div className="space-y-4">
                  {/* Media Cache TTL */}
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm text-vault-text">{t('settings.mediaCacheTTL')}</p>
                      <p className="text-xs text-vault-text-muted mt-0.5">{t('settings.mediaCacheTTLDesc')}</p>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <input
                        type="number"
                        min={0}
                        step={1}
                        value={swCacheConfig.mediaCacheTTLHours}
                        onChange={(e) => handleSWCacheChange('mediaCacheTTLHours', Number(e.target.value))}
                        onBlur={handleSWCacheBlur}
                        className="w-20 bg-vault-input border border-vault-border rounded px-2 py-1.5 text-sm text-vault-text focus:outline-none focus:border-vault-accent text-right"
                      />
                      <span className="text-xs text-vault-text-muted w-8">{t('settings.hours')}</span>
                    </div>
                  </div>

                  {/* Media Cache Size */}
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm text-vault-text">{t('settings.mediaCacheSizeLimit')}</p>
                      <p className="text-xs text-vault-text-muted mt-0.5">{t('settings.mediaCacheSizeLimitDesc')}</p>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <input
                        type="number"
                        min={0}
                        step={256}
                        value={swCacheConfig.mediaCacheSizeMB}
                        onChange={(e) => handleSWCacheChange('mediaCacheSizeMB', Number(e.target.value))}
                        onBlur={handleSWCacheBlur}
                        className="w-20 bg-vault-input border border-vault-border rounded px-2 py-1.5 text-sm text-vault-text focus:outline-none focus:border-vault-accent text-right"
                      />
                      <span className="text-xs text-vault-text-muted w-8">{t('settings.mb')}</span>
                    </div>
                  </div>

                  {/* Page Cache TTL */}
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="text-sm text-vault-text">{t('settings.pageCacheTTL')}</p>
                      <p className="text-xs text-vault-text-muted mt-0.5">{t('settings.pageCacheTTLDesc')}</p>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <input
                        type="number"
                        min={0}
                        step={1}
                        value={swCacheConfig.pageCacheTTLHours}
                        onChange={(e) => handleSWCacheChange('pageCacheTTLHours', Number(e.target.value))}
                        onBlur={handleSWCacheBlur}
                        className="w-20 bg-vault-input border border-vault-border rounded px-2 py-1.5 text-sm text-vault-text focus:outline-none focus:border-vault-accent text-right"
                      />
                      <span className="text-xs text-vault-text-muted w-8">{t('settings.hours')}</span>
                    </div>
                  </div>

                  {/* Clear browser cache */}
                  <div className="pt-3 border-t border-vault-border/50">
                    <button
                      onClick={handleClearBrowserCache}
                      className="px-4 py-2 bg-red-600/20 border border-red-500/30 text-red-400 hover:bg-red-600/30 rounded text-sm font-medium transition-colors"
                    >
                      {t('settings.clearBrowserCache')}
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>

          {/* ── API Tokens ── */}
          <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
            <div className="flex items-center justify-between">
              <div className="flex-1">
                <SectionHeader
                  title={t('settings.apiTokensSection')}
                  sectionKey="apiTokens"
                  openSections={openSections}
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

            {openSections.has('apiTokens') && (
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

                {/* RSS Feeds */}
                <div className="mt-3 px-3 py-2 bg-vault-bg rounded border border-vault-border">
                  <p className="text-xs text-vault-text-muted mb-1">{t('rss.recentFeed')}</p>
                  <div className="flex items-center gap-2">
                    <code className="text-xs text-vault-text-secondary flex-1 truncate">
                      {typeof window !== 'undefined' ? window.location.origin : ''}/api/rss/recent?token=YOUR_TOKEN
                    </code>
                    <button
                      onClick={() => {
                        navigator.clipboard.writeText(
                          `${window.location.origin}/api/rss/recent?token=YOUR_TOKEN`
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
              openSections={openSections}
              onToggle={toggleSection}
            />
            {openSections.has('account') && (
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
  )
}
