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
import type {
  SiteConfigItem,
  SiteDownloadKey,
  SiteSleepValue,
  ProbeField,
  ProbeFieldMapping,
} from '@/lib/types'

// ── Helpers ───────────────────────────────────────────────────────────

function formatSleep(val: SiteSleepValue | undefined): string {
  if (val === null || val === undefined) return '—'
  if (Array.isArray(val))
    return t('admin.sites.sleepRange', { min: String(val[0]), max: String(val[1]) })
  return t('admin.sites.sleepFixed', { value: String(val) })
}

function categoryLabel(cat: string): string {
  return cat.charAt(0).toUpperCase() + cat.slice(1)
}

// ── Download Settings Form ────────────────────────────────────────────

type SleepKey = 'sleep_request' | 'sleep_download'

interface DownloadFormState {
  retries: number
  http_timeout: number
  sleep_request_raw: string // free text: "2", "1-5", or empty
  sleep_download_raw: string // same format as sleep_request_raw
  concurrency: number
  inactivity_timeout: number
  spread_personas: boolean
}

const SLEEP_FIXED_RE = /^\d+(?:\.\d+)?$/
const SLEEP_RANGE_RE = /^(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)$/

/** Parse "2" / "1-5" / "" into a sleep value; `ok: false` for anything else. */
function parseSleep(raw: string): { ok: true; value: SiteSleepValue } | { ok: false } {
  const text = raw.trim()
  if (!text) return { ok: true, value: null }
  if (SLEEP_FIXED_RE.test(text)) return { ok: true, value: Number(text) }
  const range = SLEEP_RANGE_RE.exec(text)
  if (range) return { ok: true, value: [Number(range[1]), Number(range[2])] }
  return { ok: false }
}

function sleepToRaw(val: SiteSleepValue | undefined): string {
  if (val === null || val === undefined) return ''
  if (Array.isArray(val)) return `${val[0]}-${val[1]}`
  return String(val)
}

function siteToForm(site: SiteConfigItem): DownloadFormState {
  return {
    retries: site.download.retries,
    http_timeout: site.download.http_timeout,
    sleep_request_raw: sleepToRaw(site.download.sleep_request),
    sleep_download_raw: sleepToRaw(site.download.sleep_download),
    concurrency: site.download.concurrency,
    inactivity_timeout: site.download.inactivity_timeout,
    spread_personas: site.download.spread_personas ?? false,
  }
}

interface DownloadChanges {
  /** Only the keys whose form value differs from the value at load. */
  payload: Record<string, unknown>
  /** Overridden sleep fields the user cleared: reset instead of storing null. */
  resets: SleepKey[]
  /** A sleep field holds text that is neither a number nor a range. */
  invalid: boolean
}

function computeDownloadChanges(site: SiteConfigItem, form: DownloadFormState): DownloadChanges {
  const payload: Record<string, unknown> = {}
  const resets: SleepKey[] = []
  let invalid = false
  const base = site.download

  if (form.retries !== base.retries) payload.retries = form.retries
  if (form.http_timeout !== base.http_timeout) payload.http_timeout = form.http_timeout
  if (form.concurrency !== base.concurrency) payload.concurrency = form.concurrency
  if (form.inactivity_timeout !== base.inactivity_timeout)
    payload.inactivity_timeout = form.inactivity_timeout
  if (form.spread_personas !== (base.spread_personas ?? false))
    payload.spread_personas = form.spread_personas

  const sleeps: [SleepKey, string][] = [
    ['sleep_request', form.sleep_request_raw],
    ['sleep_download', form.sleep_download_raw],
  ]
  for (const [key, raw] of sleeps) {
    const parsed = parseSleep(raw)
    if (!parsed.ok) {
      invalid = true
      continue
    }
    const before = JSON.stringify(base[key] ?? null)
    if (JSON.stringify(parsed.value) === before) continue
    if (parsed.value === null) {
      // Cleared. Never PUT null: it would store an explicit null override.
      if (site.overridden.includes(key)) resets.push(key)
      continue
    }
    payload[key] = parsed.value
  }
  return { payload, resets, invalid }
}

/** Where a field's default comes from, as a short hint line. */
function defaultHint(site: SiteConfigItem, key: SiteDownloadKey): string {
  if (key === 'sleep_request' || key === 'sleep_download') {
    const own = site.defaults[key]
    if (own !== null && own !== undefined) {
      return t('admin.sites.defaultValue', { value: formatSleep(own) })
    }
    const builtin = site.extractor_defaults[key]
    if (builtin !== null && builtin !== undefined) {
      return t('admin.sites.defaultExtractor', { value: formatSleep(builtin) })
    }
    return t('admin.sites.defaultNone')
  }
  if (key === 'spread_personas') {
    return t('admin.sites.defaultValue', {
      value: site.defaults.spread_personas ? t('admin.sites.valueOn') : t('admin.sites.valueOff'),
    })
  }
  return t('admin.sites.defaultValue', { value: String(site.defaults[key]) })
}

interface FieldMarkersProps {
  site: SiteConfigItem
  fieldKey: SiteDownloadKey
  label: string
  busy: boolean
  onReset: (key: SiteDownloadKey) => void
}

/** Overridden / auto-tuned markers plus the per-field reset button. */
function FieldMarkers({ site, fieldKey, label, busy, onReset }: FieldMarkersProps) {
  const overridden = site.overridden.includes(fieldKey)
  const adaptive = !overridden && site.adaptive.includes(fieldKey)
  if (!overridden && !adaptive) return null
  return (
    <span className="inline-flex items-center gap-1.5">
      {overridden && (
        <span className="px-1.5 py-0.5 rounded bg-vault-accent/15 text-vault-accent text-[10px] font-medium">
          {t('admin.sites.overridden')}
        </span>
      )}
      {adaptive && (
        <span className="px-1.5 py-0.5 rounded bg-vault-card text-vault-text-secondary text-[10px] font-medium">
          {t('admin.sites.autoTuned')}
        </span>
      )}
      {overridden && (
        <button
          type="button"
          onClick={() => onReset(fieldKey)}
          disabled={busy}
          title={t('admin.sites.resetField', { field: label })}
          aria-label={t('admin.sites.resetField', { field: label })}
          className="p-0.5 rounded text-vault-text-secondary hover:text-vault-text transition-colors disabled:opacity-50"
        >
          <RotateCcw className="w-3 h-3" />
        </button>
      )}
    </span>
  )
}

type NumberFieldKey = 'retries' | 'http_timeout' | 'concurrency' | 'inactivity_timeout'

const NUMBER_FIELDS: {
  key: NumberFieldKey
  labelKey:
    | 'admin.sites.retries'
    | 'admin.sites.httpTimeout'
    | 'admin.sites.concurrency'
    | 'admin.sites.inactivityTimeout'
  withSeconds: boolean
  min: number
  max: number
}[] = [
  { key: 'retries', labelKey: 'admin.sites.retries', withSeconds: false, min: 0, max: 50 },
  { key: 'http_timeout', labelKey: 'admin.sites.httpTimeout', withSeconds: true, min: 5, max: 300 },
  { key: 'concurrency', labelKey: 'admin.sites.concurrency', withSeconds: false, min: 1, max: 20 },
  {
    key: 'inactivity_timeout',
    labelKey: 'admin.sites.inactivityTimeout',
    withSeconds: true,
    min: 30,
    max: 3600,
  },
]

const SLEEP_FIELDS: {
  key: SleepKey
  rawKey: 'sleep_request_raw' | 'sleep_download_raw'
  labelKey: 'admin.sites.sleepRequest' | 'admin.sites.sleepDownload'
  hintKey: 'admin.sites.sleepRequestHint' | 'admin.sites.sleepDownloadHint'
}[] = [
  {
    key: 'sleep_request',
    rawKey: 'sleep_request_raw',
    labelKey: 'admin.sites.sleepRequest',
    hintKey: 'admin.sites.sleepRequestHint',
  },
  {
    key: 'sleep_download',
    rawKey: 'sleep_download_raw',
    labelKey: 'admin.sites.sleepDownload',
    hintKey: 'admin.sites.sleepDownloadHint',
  },
]

// ── Editor Panel ──────────────────────────────────────────────────────

interface EditorPanelProps {
  site: SiteConfigItem
  probeResult?: { fields: ProbeField[]; mappings: ProbeFieldMapping[] } | null
  onClose: () => void
  /** Called with the server's SiteConfigItem after any successful mutation. */
  onSaved: (updated: SiteConfigItem) => void
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
  const [resettingKey, setResettingKey] = useState<SiteDownloadKey | null>(null)

  const { trigger: updateConfig } = useUpdateSiteConfig()
  const { trigger: updateMapping } = useUpdateFieldMapping()
  const { trigger: resetField } = useResetSiteField()
  const { trigger: resetAdaptive } = useResetAdaptive()

  const changes = computeDownloadChanges(site, form)
  const dirty =
    changes.invalid || changes.resets.length > 0 || Object.keys(changes.payload).length > 0

  const handleSaveDownload = async () => {
    const { payload, resets, invalid } = computeDownloadChanges(site, form)
    if (invalid) {
      toast.error(t('admin.sites.sleepInvalid'))
      return
    }
    if (resets.length === 0 && Object.keys(payload).length === 0) return
    setSaving(true)
    try {
      let latest: SiteConfigItem | undefined
      // Resets first so the cross-field validation of the PUT sees the final state.
      for (const key of resets) {
        latest = await resetField({ sourceId: site.source_id, fieldPath: `download.${key}` })
      }
      if (Object.keys(payload).length > 0) {
        latest = await updateConfig({ sourceId: site.source_id, data: { download: payload } })
      }
      toast.success(t('admin.sites.saved'))
      if (latest) onSaved(latest)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.error'))
    } finally {
      setSaving(false)
    }
  }

  const handleResetField = async (key: SiteDownloadKey) => {
    setResettingKey(key)
    try {
      const updated = await resetField({
        sourceId: site.source_id,
        fieldPath: `download.${key}`,
      })
      toast.success(t('admin.sites.resetDone'))
      onSaved(updated)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.error'))
    } finally {
      setResettingKey(null)
    }
  }

  const handleSaveMapping = async () => {
    setSavingMapping(true)
    try {
      const updated = await updateMapping({ sourceId: site.source_id, fieldMapping })
      toast.success(t('admin.sites.mappingSaved'))
      onSaved(updated)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.error'))
    } finally {
      setSavingMapping(false)
    }
  }

  const handleResetDownload = async () => {
    setResetting(true)
    try {
      const updated = await resetField({ sourceId: site.source_id, fieldPath: 'download' })
      toast.success(t('admin.sites.resetDone'))
      onSaved(updated)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.error'))
    } finally {
      setResetting(false)
    }
  }

  const handleResetAdaptive = async () => {
    setResettingAdaptive(true)
    try {
      const updated = await resetAdaptive(site.source_id)
      toast.success(t('admin.sites.adaptiveReset'))
      onSaved(updated)
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
      <button
        type="button"
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
        aria-label={t('admin.sites.close')}
      />
      {/* Panel */}
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="site-editor-dialog-title"
        className="relative w-full max-w-2xl bg-vault-bg border-l border-vault-border flex flex-col overflow-hidden shadow-2xl"
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-vault-border shrink-0">
          <div>
            <h2 id="site-editor-dialog-title" className="text-vault-text font-semibold text-lg">
              {t('admin.sites.editor')}
            </h2>
            <p className="text-vault-text-secondary text-sm mt-0.5">
              {site.name} — {site.domain}
            </p>
          </div>
          <button
            type="button"
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
              {NUMBER_FIELDS.map(({ key, labelKey, withSeconds, min, max }) => {
                const label = t(labelKey)
                const id = `site-field-${key}`
                return (
                  <div key={key} className="flex flex-col gap-1">
                    <div className="flex items-center justify-between gap-2">
                      <label htmlFor={id} className="text-vault-text-secondary text-xs">
                        {withSeconds ? `${label} (${t('admin.sites.seconds')})` : label}
                      </label>
                      <FieldMarkers
                        site={site}
                        fieldKey={key}
                        label={label}
                        busy={resettingKey === key}
                        onReset={handleResetField}
                      />
                    </div>
                    <input
                      id={id}
                      type="number"
                      min={min}
                      max={max}
                      value={form[key]}
                      onChange={(e) => setForm((f) => ({ ...f, [key]: Number(e.target.value) }))}
                      className="vault-input rounded-lg px-3 py-2 text-sm"
                    />
                    <p className="text-xs text-vault-text-muted">{defaultHint(site, key)}</p>
                  </div>
                )
              })}
              <div className="col-span-2 flex flex-col gap-1">
                <div className="flex items-center justify-between gap-2">
                  <label className="flex items-center gap-2 text-sm text-vault-text">
                    <input
                      type="checkbox"
                      checked={form.spread_personas}
                      onChange={(e) =>
                        setForm((f) => ({ ...f, spread_personas: e.target.checked }))
                      }
                      className="accent-vault-accent"
                    />
                    {t('admin.sites.spreadPersonas')}
                  </label>
                  <FieldMarkers
                    site={site}
                    fieldKey="spread_personas"
                    label={t('admin.sites.spreadPersonas')}
                    busy={resettingKey === 'spread_personas'}
                    onReset={handleResetField}
                  />
                </div>
                <p className="text-xs text-vault-text-muted">
                  {t('admin.sites.spreadPersonasHint')} {defaultHint(site, 'spread_personas')}
                </p>
              </div>
              {SLEEP_FIELDS.map(({ key, rawKey, labelKey, hintKey }) => {
                const label = t(labelKey)
                const id = `site-field-${key}`
                return (
                  <div key={key} className="col-span-2 flex flex-col gap-1">
                    <div className="flex items-center justify-between gap-2">
                      <label htmlFor={id} className="text-vault-text-secondary text-xs">
                        {label} ({t('admin.sites.seconds')})
                      </label>
                      <FieldMarkers
                        site={site}
                        fieldKey={key}
                        label={label}
                        busy={resettingKey === key}
                        onReset={handleResetField}
                      />
                    </div>
                    <input
                      id={id}
                      type="text"
                      value={form[rawKey]}
                      onChange={(e) => setForm((f) => ({ ...f, [rawKey]: e.target.value }))}
                      placeholder={t('admin.sites.sleepRequestExample')}
                      className="vault-input rounded-lg px-3 py-2 text-sm"
                    />
                    <p className="text-xs text-vault-text-muted">
                      {t(hintKey)} {defaultHint(site, key)}
                    </p>
                  </div>
                )
              })}
            </div>
            <div className="flex gap-2 mt-4">
              <button
                onClick={handleSaveDownload}
                disabled={saving || !dirty}
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
      <button
        type="button"
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
        aria-label={t('admin.sites.close')}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="site-probe-dialog-title"
        className="relative w-full max-w-md bg-vault-bg border border-vault-border rounded-xl shadow-2xl p-6"
      >
        <div className="flex items-center justify-between mb-4">
          <h3 id="site-probe-dialog-title" className="text-vault-text font-semibold">
            {t('admin.sites.probeUrl')}
          </h3>
          <button
            type="button"
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
  // Bumped after every mutation so the editor re-initialises from the response.
  const [editorRev, setEditorRev] = useState(0)
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

  const handleSaved = (updated: SiteConfigItem) => {
    setSelectedSite(updated)
    setEditorRev((r) => r + 1)
    mutate()
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
          key={`${selectedSite.source_id}:${editorRev}`}
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
