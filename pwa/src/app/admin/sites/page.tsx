'use client'

import { useState, useEffect, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { Globe, Search, X, Star, RotateCcw, Save, Loader2 } from 'lucide-react'
import { toast } from 'sonner'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { useProfile } from '@/hooks/useProfile'
import {
  useSiteConfigs,
  useProbe,
  useUpdateSiteConfig,
  useUpdateFieldMapping,
  useResetSiteField,
  useResetAdaptive,
} from '@/hooks/useSiteConfigs'
import type { SiteConfigItem, ProbeField, ProbeFieldMapping } from '@/lib/types'

// ── Helpers ───────────────────────────────────────────────────────────

function formatSleep(val: SiteConfigItem['download']['sleep_request']): string {
  if (val === null || val === undefined) return '—'
  if (Array.isArray(val))
    return t('admin.sites.sleepRange', { min: String(val[0]), max: String(val[1]) })
  return t('admin.sites.sleepFixed', { value: String(val) })
}

function categoryLabel(cat: string): string {
  return cat.charAt(0).toUpperCase() + cat.slice(1)
}

// ── Download Settings Form ────────────────────────────────────────────

interface DownloadFormState {
  retries: number
  http_timeout: number
  sleep_request_raw: string // free text: "2", "1-5", or empty
  concurrency: number
  inactivity_timeout: number
}

function parseFormToPayload(form: DownloadFormState): Record<string, unknown> {
  const raw = form.sleep_request_raw.trim()
  let sleep_request: number | [number, number] | null = null
  if (raw) {
    if (raw.includes('-')) {
      const parts = raw.split('-').map(Number)
      if (parts.length === 2 && !isNaN(parts[0]) && !isNaN(parts[1])) {
        sleep_request = [parts[0], parts[1]]
      }
    } else {
      const n = Number(raw)
      if (!isNaN(n)) sleep_request = n
    }
  }
  return {
    retries: form.retries,
    http_timeout: form.http_timeout,
    sleep_request,
    concurrency: form.concurrency,
    inactivity_timeout: form.inactivity_timeout,
  }
}

function siteToForm(site: SiteConfigItem): DownloadFormState {
  const s = site.download.sleep_request
  let sleep_request_raw = ''
  if (s !== null && s !== undefined) {
    if (Array.isArray(s)) sleep_request_raw = `${s[0]}-${s[1]}`
    else sleep_request_raw = String(s)
  }
  return {
    retries: site.download.retries,
    http_timeout: site.download.http_timeout,
    sleep_request_raw,
    concurrency: site.download.concurrency,
    inactivity_timeout: site.download.inactivity_timeout,
  }
}

// ── Editor Panel ──────────────────────────────────────────────────────

interface EditorPanelProps {
  site: SiteConfigItem
  probeResult?: { fields: ProbeField[]; mappings: ProbeFieldMapping[] } | null
  onClose: () => void
  onSaved: () => void
}

function EditorPanel({ site, probeResult, onClose, onSaved }: EditorPanelProps) {
  const [form, setForm] = useState<DownloadFormState>(() => siteToForm(site))
  const [fieldMapping, setFieldMapping] = useState<Record<string, string | null>>(() => {
    // Use existing field_mapping if available
    if (site.field_mapping && Object.keys(site.field_mapping).length > 0) {
      return site.field_mapping
    }
    // Otherwise, auto-fill from probe suggested mappings
    if (probeResult?.mappings) {
      const merged: Record<string, string | null> = {}
      for (const m of probeResult.mappings) {
        if (m.suggested && m.gdl_field) merged[m.jyzrox_field] = m.gdl_field
      }
      if (Object.keys(merged).length > 0) return merged
    }
    return {}
  })
  const [saving, setSaving] = useState(false)
  const [savingMapping, setSavingMapping] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [resettingAdaptive, setResettingAdaptive] = useState(false)

  const { trigger: updateConfig } = useUpdateSiteConfig()
  const { trigger: updateMapping } = useUpdateFieldMapping()
  const { trigger: resetField } = useResetSiteField()
  const { trigger: resetAdaptive } = useResetAdaptive()

  const handleSaveDownload = async () => {
    setSaving(true)
    try {
      await updateConfig({ sourceId: site.source_id, data: { download: parseFormToPayload(form) } })
      toast.success(t('admin.sites.saved'))
      onSaved()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.error'))
    } finally {
      setSaving(false)
    }
  }

  const handleSaveMapping = async () => {
    setSavingMapping(true)
    try {
      await updateMapping({ sourceId: site.source_id, fieldMapping })
      toast.success(t('admin.sites.mappingSaved'))
      onSaved()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.error'))
    } finally {
      setSavingMapping(false)
    }
  }

  const handleResetDownload = async () => {
    setResetting(true)
    try {
      await resetField({ sourceId: site.source_id, fieldPath: 'download' })
      toast.success(t('admin.sites.resetDone'))
      onSaved()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.error'))
    } finally {
      setResetting(false)
    }
  }

  const handleResetAdaptive = async () => {
    setResettingAdaptive(true)
    try {
      await resetAdaptive(site.source_id)
      toast.success(t('admin.sites.adaptiveReset'))
      onSaved()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.error'))
    } finally {
      setResettingAdaptive(false)
    }
  }

  // Available gallery-dl field options from probe
  const gdlFieldOptions: string[] = useMemo(() => {
    if (!probeResult?.fields) return []
    return probeResult.fields.map((f) => f.key)
  }, [probeResult?.fields])

  // Jyzrox fields to configure (from probe mappings if available)
  const jyzroxFields: string[] = useMemo(() => {
    if (probeResult?.mappings && probeResult.mappings.length > 0) {
      return probeResult.mappings.map((m) => m.jyzrox_field)
    }
    return Object.keys(fieldMapping)
  }, [probeResult?.mappings, fieldMapping])

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />
      {/* Panel */}
      <div className="relative w-full max-w-2xl bg-vault-bg border-l border-vault-border flex flex-col overflow-hidden shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-vault-border shrink-0">
          <div>
            <h2 className="text-vault-text font-semibold text-lg">{t('admin.sites.editor')}</h2>
            <p className="text-vault-text-secondary text-sm mt-0.5">
              {site.name} — {site.domain}
            </p>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg text-vault-text-secondary hover:text-vault-text hover:bg-vault-card transition-colors"
            aria-label={t('admin.sites.close')}
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Scrollable body */}
        <div className="flex-1 overflow-y-auto p-6 space-y-8">
          {/* Download Settings */}
          <section>
            <h3 className="text-vault-text font-medium mb-4">
              {t('admin.sites.downloadSettings')}
            </h3>
            <div className="grid grid-cols-2 gap-4">
              <label className="flex flex-col gap-1">
                <span className="text-vault-text-secondary text-xs">
                  {t('admin.sites.retries')}
                </span>
                <input
                  type="number"
                  min={0}
                  max={50}
                  value={form.retries}
                  onChange={(e) => setForm((f) => ({ ...f, retries: Number(e.target.value) }))}
                  className="vault-input rounded-lg px-3 py-2 text-sm"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-vault-text-secondary text-xs">
                  {t('admin.sites.httpTimeout')} ({t('admin.sites.seconds')})
                </span>
                <input
                  type="number"
                  min={5}
                  max={300}
                  value={form.http_timeout}
                  onChange={(e) => setForm((f) => ({ ...f, http_timeout: Number(e.target.value) }))}
                  className="vault-input rounded-lg px-3 py-2 text-sm"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-vault-text-secondary text-xs">
                  {t('admin.sites.concurrency')}
                </span>
                <input
                  type="number"
                  min={1}
                  max={20}
                  value={form.concurrency}
                  onChange={(e) => setForm((f) => ({ ...f, concurrency: Number(e.target.value) }))}
                  className="vault-input rounded-lg px-3 py-2 text-sm"
                />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-vault-text-secondary text-xs">
                  {t('admin.sites.inactivityTimeout')} ({t('admin.sites.seconds')})
                </span>
                <input
                  type="number"
                  min={30}
                  max={3600}
                  value={form.inactivity_timeout}
                  onChange={(e) =>
                    setForm((f) => ({ ...f, inactivity_timeout: Number(e.target.value) }))
                  }
                  className="vault-input rounded-lg px-3 py-2 text-sm"
                />
              </label>
              <label className="col-span-2 flex flex-col gap-1">
                <span className="text-vault-text-secondary text-xs">
                  {t('admin.sites.sleepRequest')} ({t('admin.sites.seconds')}, e.g. 2 or 1-5)
                </span>
                <input
                  type="text"
                  value={form.sleep_request_raw}
                  onChange={(e) => setForm((f) => ({ ...f, sleep_request_raw: e.target.value }))}
                  placeholder="e.g. 2 or 1-5"
                  className="vault-input rounded-lg px-3 py-2 text-sm"
                />
              </label>
            </div>
            <div className="flex gap-2 mt-4">
              <button
                onClick={handleSaveDownload}
                disabled={saving}
                className="flex items-center gap-2 px-4 py-2 rounded-lg bg-vault-accent text-white text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
              >
                {saving ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Save className="w-4 h-4" />
                )}
                {t('admin.sites.save')}
              </button>
              <button
                onClick={handleResetDownload}
                disabled={resetting}
                className="flex items-center gap-2 px-4 py-2 rounded-lg border border-vault-border text-vault-text-secondary text-sm hover:text-vault-text hover:border-vault-text transition-colors disabled:opacity-50"
              >
                {resetting ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <RotateCcw className="w-4 h-4" />
                )}
                {t('admin.sites.resetToDefault')}
              </button>
              <button
                onClick={handleResetAdaptive}
                disabled={resettingAdaptive}
                className="flex items-center gap-2 px-4 py-2 rounded-lg border border-vault-border text-vault-text-secondary text-sm hover:text-vault-text hover:border-vault-text transition-colors disabled:opacity-50"
              >
                {resettingAdaptive ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <RotateCcw className="w-4 h-4" />
                )}
                {t('admin.sites.resetAdaptive')}
              </button>
            </div>
          </section>

          {/* Field Mapping — only shown when probe data is available */}
          {(jyzroxFields.length > 0 || probeResult?.fields) && (
            <section>
              <h3 className="text-vault-text font-medium mb-4">{t('admin.sites.fieldMapping')}</h3>
              <div className="overflow-x-auto rounded-lg border border-vault-border">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-vault-border bg-vault-card">
                      <th className="text-left px-4 py-2 text-vault-text-secondary font-medium">
                        {t('admin.sites.jyzroxField')}
                      </th>
                      <th className="text-left px-4 py-2 text-vault-text-secondary font-medium">
                        {t('admin.sites.gdlField')}
                      </th>
                      <th className="w-8 px-2 py-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {jyzroxFields.map((jField) => {
                      const isSuggested =
                        probeResult?.mappings?.find((m) => m.jyzrox_field === jField)?.suggested ??
                        false
                      return (
                        <tr key={jField} className="border-b border-vault-border last:border-0">
                          <td className="px-4 py-2 text-vault-text font-mono text-xs">{jField}</td>
                          <td className="px-4 py-2">
                            <select
                              value={fieldMapping[jField] ?? ''}
                              onChange={(e) =>
                                setFieldMapping((m) => ({ ...m, [jField]: e.target.value || null }))
                              }
                              className="vault-input rounded px-2 py-1 text-xs w-full"
                            >
                              <option value="">{t('admin.sites.noMapping')}</option>
                              {gdlFieldOptions.map((opt) => (
                                <option key={opt} value={opt}>
                                  {opt}
                                </option>
                              ))}
                            </select>
                          </td>
                          <td className="px-2 py-2">
                            {isSuggested && (
                              <Star
                                className="w-3.5 h-3.5 text-yellow-400"
                                aria-label={t('admin.sites.suggested')}
                              />
                            )}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>

              {/* Probe fields reference table */}
              {probeResult?.fields && probeResult.fields.length > 0 && (
                <details className="mt-3">
                  <summary className="text-vault-text-secondary text-xs cursor-pointer hover:text-vault-text select-none">
                    {t('admin.sites.livePreview')}
                  </summary>
                  <div className="mt-2 overflow-x-auto rounded-lg border border-vault-border">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="border-b border-vault-border bg-vault-card">
                          <th className="text-left px-3 py-1.5 text-vault-text-secondary">
                            {t('admin.sites.gdlField')}
                          </th>
                          <th className="text-left px-3 py-1.5 text-vault-text-secondary">
                            {t('admin.sites.fieldType')}
                          </th>
                          <th className="text-left px-3 py-1.5 text-vault-text-secondary">
                            {t('admin.sites.level')}
                          </th>
                          <th className="text-left px-3 py-1.5 text-vault-text-secondary">
                            {t('admin.sites.sampleValue')}
                          </th>
                        </tr>
                      </thead>
                      <tbody>
                        {probeResult.fields.map((f) => (
                          <tr key={f.key} className="border-b border-vault-border last:border-0">
                            <td className="px-3 py-1.5 font-mono text-vault-text">{f.key}</td>
                            <td className="px-3 py-1.5 text-vault-text-secondary">
                              {f.field_type}
                            </td>
                            <td className="px-3 py-1.5 text-vault-text-secondary">{f.level}</td>
                            <td
                              className="px-3 py-1.5 text-vault-text-secondary truncate max-w-[160px]"
                              title={f.sample_value}
                            >
                              {f.sample_value}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </details>
              )}

              <button
                onClick={handleSaveMapping}
                disabled={savingMapping}
                className="flex items-center gap-2 mt-4 px-4 py-2 rounded-lg bg-vault-accent text-white text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
              >
                {savingMapping ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Save className="w-4 h-4" />
                )}
                {t('admin.sites.save')}
              </button>
            </section>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Probe Dialog ──────────────────────────────────────────────────────

interface ProbeDialogProps {
  onClose: () => void
  onProbeSuccess: (
    fields: ProbeField[],
    mappings: ProbeFieldMapping[],
    detectedSource?: string,
  ) => void
}

function ProbeDialog({ onClose, onProbeSuccess }: ProbeDialogProps) {
  const [url, setUrl] = useState('')
  const { trigger: probe, isMutating } = useProbe()

  const handleProbe = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (!url.trim()) return
    try {
      const result = await probe(url.trim())
      if (result) {
        toast.success(t('admin.sites.probeSuccess'))
        onProbeSuccess(result.fields ?? [], result.suggested_mappings ?? [], result.detected_source)
        onClose()
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('admin.sites.probeError'))
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-md bg-vault-bg border border-vault-border rounded-xl shadow-2xl p-6">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-vault-text font-semibold">{t('admin.sites.probeUrl')}</h3>
          <button
            onClick={onClose}
            className="p-1.5 rounded text-vault-text-secondary hover:text-vault-text transition-colors"
            aria-label={t('admin.sites.close')}
          >
            <X className="w-4 h-4" />
          </button>
        </div>
        <form onSubmit={handleProbe} className="space-y-4">
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder={t('admin.sites.probeUrlPlaceholder')}
            className="vault-input w-full rounded-lg px-3 py-2 text-sm"
            autoFocus
            required
          />
          <button
            type="submit"
            disabled={isMutating || !url.trim()}
            className="w-full flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-vault-accent text-white text-sm font-medium hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            {isMutating ? (
              <>
                <Loader2 className="w-4 h-4 animate-spin" />
                {t('admin.sites.probing')}
              </>
            ) : (
              <>
                <Globe className="w-4 h-4" />
                {t('admin.sites.probe')}
              </>
            )}
          </button>
        </form>
      </div>
    </div>
  )
}

// ── Site Row ──────────────────────────────────────────────────────────

interface SiteRowProps {
  site: SiteConfigItem
  onEdit: (site: SiteConfigItem) => void
}

function SiteRow({ site, onEdit }: SiteRowProps) {
  const sleep = formatSleep(site.download.sleep_request)
  return (
    <div className="flex items-center gap-4 px-4 py-3 vault-card-hover rounded-lg">
      <Globe className="w-4 h-4 text-vault-text-secondary shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="text-vault-text text-sm font-medium truncate">{site.name}</div>
        <div className="text-vault-text-secondary text-xs truncate">{site.domain}</div>
      </div>
      <div className="hidden sm:flex items-center gap-4 text-xs text-vault-text-secondary shrink-0">
        <span title={t('admin.sites.retries')}>
          {t('admin.sites.retries')}: {site.download.retries}
        </span>
        <span title={t('admin.sites.concurrency')}>
          {t('admin.sites.concurrency')}: {site.download.concurrency}
        </span>
        {sleep !== '—' && (
          <span title={t('admin.sites.sleepRequest')}>
            {t('admin.sites.sleepRequest')}: {sleep}
          </span>
        )}
      </div>
      <button
        onClick={() => onEdit(site)}
        className="shrink-0 px-3 py-1.5 rounded-lg text-xs font-medium border border-vault-border text-vault-text-secondary hover:text-vault-text hover:border-vault-accent transition-colors"
      >
        {t('admin.sites.edit')}
      </button>
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────

export default function AdminSitesPage() {
  useLocale()
  const router = useRouter()
  const { data: profile, isLoading: profileLoading } = useProfile()

  const { data: sites, isLoading, mutate } = useSiteConfigs()

  const [search, setSearch] = useState('')
  const [selectedSite, setSelectedSite] = useState<SiteConfigItem | null>(null)
  const [showProbe, setShowProbe] = useState(false)
  const [probeResult, setProbeResult] = useState<{
    fields: ProbeField[]
    mappings: ProbeFieldMapping[]
    detectedSource?: string
  } | null>(null)

  const isAdmin = profile?.role === 'admin'

  useEffect(() => {
    if (!profileLoading && profile && !isAdmin) {
      router.replace('/forbidden')
    }
  }, [profileLoading, profile, isAdmin, router])

  // Filter sites by search — hooks must be called before any early return
  const filteredSites = useMemo(() => {
    if (!sites) return []
    const q = search.toLowerCase()
    if (!q) return sites
    return sites.filter(
      (s) => s.name.toLowerCase().includes(q) || s.domain.toLowerCase().includes(q),
    )
  }, [sites, search])

  // Group by category
  const grouped = useMemo(() => {
    const map = new Map<string, SiteConfigItem[]>()
    for (const site of filteredSites) {
      const cat = site.category || 'other'
      if (!map.has(cat)) map.set(cat, [])
      map.get(cat)!.push(site)
    }
    return map
  }, [filteredSites])

  if (profileLoading || !profile || !isAdmin) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-vault-text-secondary text-sm">{t('common.loading')}</div>
      </div>
    )
  }

  const handleProbeSuccess = (
    fields: ProbeField[],
    mappings: ProbeFieldMapping[],
    detectedSource?: string,
  ) => {
    setProbeResult({ fields, mappings, detectedSource })

    // Auto-open editor for detected source
    if (detectedSource && sites) {
      const match = sites.find((s) => s.source_id === detectedSource)
      if (match) setSelectedSite(match)
    }
  }

  const handleSaved = () => {
    mutate()
    if (selectedSite && sites) {
      const updated = sites.find((s) => s.source_id === selectedSite.source_id)
      if (updated) setSelectedSite(updated)
    }
  }

  return (
    <div className="max-w-5xl mx-auto px-4 py-6 space-y-6">
      {/* Page header */}
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-vault-text text-xl font-semibold">{t('admin.sites.title')}</h1>
        <button
          onClick={() => setShowProbe(true)}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-vault-accent text-white text-sm font-medium hover:opacity-90 transition-opacity"
        >
          <Globe className="w-4 h-4" />
          {t('admin.sites.probe')}
        </button>
      </div>

      {/* Probe detected source banner */}
      {probeResult?.detectedSource && (
        <div className="flex items-center gap-3 px-4 py-3 rounded-lg bg-vault-accent/10 border border-vault-accent/30 text-sm">
          <Globe className="w-4 h-4 text-vault-accent shrink-0" />
          <span className="text-vault-text">
            {t('admin.sites.detectedSource')}:{' '}
            <span className="font-medium">{probeResult.detectedSource}</span>
          </span>
          <button
            onClick={() => setProbeResult(null)}
            className="ml-auto p-1 text-vault-text-secondary hover:text-vault-text transition-colors"
            aria-label={t('admin.sites.close')}
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {/* Search bar */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-vault-text-secondary pointer-events-none" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t('admin.sites.search')}
          className="vault-input w-full rounded-lg pl-9 pr-9 py-2 text-sm"
        />
        {search && (
          <button
            onClick={() => setSearch('')}
            className="absolute right-3 top-1/2 -translate-y-1/2 text-vault-text-secondary hover:text-vault-text transition-colors"
            aria-label={t('admin.sites.close')}
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Site list */}
      {isLoading ? (
        <div className="flex items-center justify-center py-16">
          <Loader2 className="w-6 h-6 text-vault-text-secondary animate-spin" />
        </div>
      ) : grouped.size === 0 ? (
        <div className="text-center py-16 text-vault-text-secondary text-sm">
          {t('admin.sites.noSites')}
        </div>
      ) : (
        <div className="space-y-6">
          {Array.from(grouped.entries()).map(([category, catSites]) => (
            <section key={category}>
              <div className="flex items-center gap-2 mb-2">
                <h2 className="text-vault-text-secondary text-xs font-semibold uppercase tracking-wider">
                  {categoryLabel(category)}
                </h2>
                <span className="text-vault-text-secondary text-xs">({catSites.length})</span>
              </div>
              <div className="vault-card rounded-xl divide-y divide-vault-border overflow-hidden">
                {catSites.map((site) => (
                  <SiteRow
                    key={site.source_id}
                    site={site}
                    onEdit={(s) => {
                      setSelectedSite(s)
                      // Clear probe state when opening a different site manually
                      if (
                        !probeResult?.detectedSource ||
                        s.source_id !== probeResult.detectedSource
                      ) {
                        setProbeResult(null)
                      }
                    }}
                  />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}

      {/* Editor panel */}
      {selectedSite && (
        <EditorPanel
          site={selectedSite}
          probeResult={probeResult}
          onClose={() => setSelectedSite(null)}
          onSaved={handleSaved}
        />
      )}

      {/* Probe dialog */}
      {showProbe && (
        <ProbeDialog onClose={() => setShowProbe(false)} onProbeSuccess={handleProbeSuccess} />
      )}
    </div>
  )
}
