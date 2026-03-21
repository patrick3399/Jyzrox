'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { useLocale } from '@/components/LocaleProvider'
import { useAdminGuard } from '@/hooks/useAdminGuard'
import { BackButton } from '@/components/BackButton'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import type { RateLimitSettings, SiteRateConfig } from '@/lib/types'

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

export default function RateLimitsSettingsPage() {
  useLocale()
  const authorized = useAdminGuard()

  const [data, setData] = useState<RateLimitSettings | null>(null)
  const [loading, setLoading] = useState(true)
  const [overrideLoading, setOverrideLoading] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const pendingPatchRef = useRef<Record<string, any>>({})
  const [subDelay, setSubDelay] = useState(500)
  const [subBatchMax, setSubBatchMax] = useState(0)
  const [updateCheckDays, setUpdateCheckDays] = useState(-1)

  const updateCheckDebounce = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const subDelayDebounce = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const subBatchDebounce = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  useEffect(() => {
    if (authorized) {
      api.settings
        .getRateLimits()
        .then(setData)
        .catch(() => toast.error(t('common.failedToLoad')))
        .finally(() => setLoading(false))
      api.settings
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .getFeatures()
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        .then((f: any) => {
          setSubDelay(f.subscription_enqueue_delay_ms ?? 500)
          setSubBatchMax(f.subscription_batch_max ?? 0)
          setUpdateCheckDays(f.gallery_update_check_days ?? -1)
        })
        .catch(() => {})
    }
  }, [authorized])

  const debouncedPatch = useCallback(
    (patch: Parameters<typeof api.settings.patchRateLimits>[0]) => {
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
    },
    [],
  )

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
      setData((prev) => (prev ? { ...prev, override_active: unlocked } : prev))
      toast.success(t('common.saved'))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToSave'))
    } finally {
      setOverrideLoading(false)
    }
  }, [data])

  const handleSubDelayChange = useCallback((v: number) => {
    setSubDelay(v)
    clearTimeout(subDelayDebounce.current)
    subDelayDebounce.current = setTimeout(async () => {
      try {
        await api.settings.setFeatureValue('subscription_enqueue_delay_ms', Math.max(100, v))
        toast.success(t('common.saved'))
      } catch {
        toast.error(t('common.failedToSave'))
      }
    }, 500)
  }, [])

  const handleSubBatchMaxChange = useCallback((v: number) => {
    setSubBatchMax(v)
    clearTimeout(subBatchDebounce.current)
    subBatchDebounce.current = setTimeout(async () => {
      try {
        await api.settings.setFeatureValue('subscription_batch_max', Math.max(0, v))
        toast.success(t('common.saved'))
      } catch {
        toast.error(t('common.failedToSave'))
      }
    }, 500)
  }, [])

  const handleUpdateCheckDaysChange = useCallback((v: number) => {
    setUpdateCheckDays(v)
    clearTimeout(updateCheckDebounce.current)
    updateCheckDebounce.current = setTimeout(async () => {
      try {
        await api.settings.setFeatureValue('gallery_update_check_days', Math.max(-1, v))
        toast.success(t('common.saved'))
      } catch {
        toast.error(t('common.failedToSave'))
      }
    }, 500)
  }, [])

  if (!authorized) return null

  if (loading) {
    return (
      <div className="max-w-2xl">
        <BackButton fallback="/settings" />
        <h1 className="text-2xl font-bold mb-6 text-vault-text">
          {t('settingsCategory.rateLimits')}
        </h1>
        <div className="flex justify-center py-8">
          <LoadingSpinner />
        </div>
      </div>
    )
  }

  if (!data) {
    return (
      <div className="max-w-2xl">
        <BackButton fallback="/settings" />
        <h1 className="text-2xl font-bold mb-6 text-vault-text">
          {t('settingsCategory.rateLimits')}
        </h1>
        <p className="text-xs text-vault-text-muted">{t('common.failedToLoad')}</p>
      </div>
    )
  }

  const siteOrder = ['ehentai', 'pixiv', 'gallery_dl']
  const orderedSites = [
    ...siteOrder.filter((s) => s in data.sites),
    ...Object.keys(data.sites).filter((s) => !siteOrder.includes(s)),
  ]

  return (
    <div className="max-w-2xl">
      <BackButton fallback="/settings" />
      <h1 className="text-2xl font-bold mb-6 text-vault-text">
        {t('settingsCategory.rateLimits')}
      </h1>

      <div className="space-y-5">
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
                    label={
                      isGalleryDl
                        ? t('settings.rateLimitsRequestDelay')
                        : t('settings.rateLimitsPageDelay')
                    }
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
              <span className="text-sm text-vault-text">
                {t('settings.rateLimitsScheduleEnable')}
              </span>
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
              <span className="text-sm text-vault-text">
                {t('settings.rateLimitsScheduleWindow')}
              </span>
              <div className="flex items-center gap-2">
                <select
                  value={data.schedule.start_hour}
                  onChange={(e) => handleScheduleChange('start_hour', Number(e.target.value))}
                  className="bg-vault-bg border border-vault-border rounded px-2 py-1 text-sm text-vault-text focus:outline-none focus:border-vault-accent"
                >
                  {Array.from({ length: 24 }, (_, i) => (
                    <option key={i} value={i}>
                      {String(i).padStart(2, '0')}
                    </option>
                  ))}
                </select>
                <span className="text-xs text-vault-text-muted">
                  {t('settings.rateLimitsScheduleTo')}
                </span>
                <select
                  value={data.schedule.end_hour}
                  onChange={(e) => handleScheduleChange('end_hour', Number(e.target.value))}
                  className="bg-vault-bg border border-vault-border rounded px-2 py-1 text-sm text-vault-text focus:outline-none focus:border-vault-accent"
                >
                  {Array.from({ length: 24 }, (_, i) => (
                    <option key={i} value={i}>
                      {String(i).padStart(2, '0')}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* Mode */}
            <div className="flex items-center justify-between">
              <span className="text-sm text-vault-text">
                {t('settings.rateLimitsScheduleMode')}
              </span>
              <select
                value={data.schedule.mode}
                onChange={(e) =>
                  handleScheduleChange('mode', e.target.value as 'full_speed' | 'standard')
                }
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
              <span className="text-sm text-vault-text-muted">
                {t('settings.subscriptionBatchMax')}
              </span>
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
          <p className="text-[10px] text-vault-text-muted mt-1">
            {t('settings.subscriptionEnqueueDesc')}
          </p>
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
          <p className="text-[10px] text-vault-text-muted mt-1">
            {t('settings.galleryUpdateCheckDaysDesc')}
          </p>
        </div>
      </div>
    </div>
  )
}
