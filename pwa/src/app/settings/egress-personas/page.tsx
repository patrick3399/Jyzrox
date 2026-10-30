'use client'

import { useState } from 'react'
import useSWR from 'swr'
import { toast } from 'sonner'
import { useLocale } from '@/components/LocaleProvider'
import { useAdminGuard } from '@/hooks/useAdminGuard'
import { BackButton } from '@/components/BackButton'
import { t } from '@/lib/i18n'
import { PageHeader } from '@/components/layout/PageHeader'
import { api } from '@/lib/api'
import type { CredentialAccount, EgressPersona, PersonaTestResult } from '@/lib/types'

const BTN =
  'px-3 py-1.5 rounded text-xs font-medium bg-vault-accent/20 text-vault-accent hover:bg-vault-accent/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed'
const DANGER_BTN =
  'px-3 py-1.5 rounded text-xs font-medium bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed'
const INPUT =
  'w-full bg-vault-bg border border-vault-border rounded px-3 py-2 text-sm text-vault-text disabled:opacity-50 disabled:cursor-not-allowed'
const LABEL = 'text-xs text-vault-text-secondary block mb-1'

type AccountsBySource = Record<string, CredentialAccount[]>

function toProfile(value: string): EgressPersona['browser_profile'] {
  return value === 'chrome' || value === 'firefox' ? value : null
}

function accountKey(source: string, account: string): string {
  return `${source}\u0000${account}`
}

function BrowserOptions() {
  return (
    <>
      <option value="">{t('personas.browserNone')}</option>
      <option value="chrome">Chrome</option>
      <option value="firefox">Firefox</option>
    </>
  )
}

// ── Create form ───────────────────────────────────────────────────────

function CreateForm({ onCreated }: { onCreated: () => Promise<unknown> }) {
  const [name, setName] = useState('')
  const [proxyUrl, setProxyUrl] = useState('')
  const [browser, setBrowser] = useState('')
  const [userAgent, setUserAgent] = useState('')
  const [busy, setBusy] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    try {
      // browser_profile and user_agent are mutually exclusive (ADR 0022).
      await api.adminPersonas.create({
        name: name.trim(),
        proxy_url: proxyUrl.trim() || null,
        browser_profile: toProfile(browser),
        user_agent: browser ? null : userAgent.trim() || null,
      })
      setName('')
      setProxyUrl('')
      setBrowser('')
      setUserAgent('')
      toast.success(t('common.saved'))
      await onCreated()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToSave'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="bg-vault-card border border-vault-border rounded-xl p-4 mb-4 space-y-3"
    >
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label htmlFor="persona-new-name" className={LABEL}>
            {t('personas.name')}
          </label>
          <input
            id="persona-new-name"
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            className={INPUT}
          />
        </div>
        <div>
          <label htmlFor="persona-new-proxy" className={LABEL}>
            {t('personas.proxyUrl')}
          </label>
          <input
            id="persona-new-proxy"
            type="text"
            value={proxyUrl}
            onChange={(e) => setProxyUrl(e.target.value)}
            placeholder={t('personas.proxyDirect')}
            className={INPUT}
          />
        </div>
        <div>
          <label htmlFor="persona-new-browser" className={LABEL}>
            {t('personas.browserProfile')}
          </label>
          <select
            id="persona-new-browser"
            value={browser}
            onChange={(e) => {
              setBrowser(e.target.value)
              if (e.target.value) setUserAgent('')
            }}
            className={INPUT}
          >
            <BrowserOptions />
          </select>
        </div>
        <div>
          <label htmlFor="persona-new-ua" className={LABEL}>
            {t('personas.userAgent')}
          </label>
          <input
            id="persona-new-ua"
            type="text"
            value={userAgent}
            disabled={browser !== ''}
            onChange={(e) => setUserAgent(e.target.value)}
            className={INPUT}
          />
        </div>
      </div>
      <p className="text-xs text-vault-text-muted">{t('personas.identityHint')}</p>
      <button type="submit" disabled={busy || !name.trim()} className={BTN}>
        {t('personas.create')}
      </button>
    </form>
  )
}

// ── Persona card ──────────────────────────────────────────────────────

interface PersonaCardProps {
  persona: EgressPersona
  sources: string[]
  accountsBySource: AccountsBySource | undefined
  takenAccounts: Set<string>
  onChanged: () => Promise<unknown>
}

function PersonaCard({
  persona,
  sources,
  accountsBySource,
  takenAccounts,
  onChanged,
}: PersonaCardProps) {
  // null = untouched, fall back to the saved value (avoids a seeding effect).
  const [proxyEdit, setProxyEdit] = useState<string | null>(null)
  const [browserEdit, setBrowserEdit] = useState<string | null>(null)
  const [uaEdit, setUaEdit] = useState<string | null>(null)
  const [picked, setPicked] = useState<Record<string, string>>({})
  const [result, setResult] = useState<PersonaTestResult | null>(null)
  const [busy, setBusy] = useState(false)

  const proxy = proxyEdit ?? persona.proxy_url ?? ''
  const browser = browserEdit ?? persona.browser_profile ?? ''
  const userAgent = browser ? '' : (uaEdit ?? persona.user_agent ?? '')
  const dirty = proxyEdit !== null || browserEdit !== null || uaEdit !== null

  const run = async (fn: () => Promise<void>) => {
    setBusy(true)
    try {
      await fn()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.error'))
    } finally {
      setBusy(false)
    }
  }

  const handleSave = () =>
    run(async () => {
      await api.adminPersonas.update(persona.id, {
        proxy_url: proxy.trim() || null,
        browser_profile: toProfile(browser),
        user_agent: browser ? null : userAgent.trim() || null,
      })
      await onChanged()
      setProxyEdit(null)
      setBrowserEdit(null)
      setUaEdit(null)
      toast.success(t('common.saved'))
    })

  const handleToggle = (enabled: boolean) =>
    run(async () => {
      await api.adminPersonas.update(persona.id, { enabled })
      await onChanged()
    })

  const handleTest = () =>
    run(async () => {
      setResult(await api.adminPersonas.test(persona.id))
    })

  const handleBind = (source: string, account: string) =>
    run(async () => {
      await api.adminPersonas.bindAccount(persona.id, source, account)
      await onChanged()
    })

  const handleUnbind = (source: string) =>
    run(async () => {
      await api.adminPersonas.unbindAccount(persona.id, source)
      await onChanged()
    })

  const handleDelete = () => {
    if (!window.confirm(t('personas.deleteConfirm', { name: persona.name }))) return
    void run(async () => {
      await api.adminPersonas.remove(persona.id)
      await onChanged()
    })
  }

  const rowSources = [
    ...sources,
    ...persona.accounts.map((a) => a.source).filter((s) => !sources.includes(s)),
  ]

  return (
    <div
      data-testid={`persona-card-${persona.id}`}
      className="bg-vault-card border border-vault-border rounded-xl p-4 mb-4 space-y-3"
    >
      <div className="flex items-center justify-between gap-3">
        <span className="text-sm font-semibold text-vault-text break-all">{persona.name}</span>
        <label className="flex items-center gap-2 text-xs text-vault-text-secondary">
          <input
            type="checkbox"
            checked={persona.enabled}
            disabled={busy}
            onChange={(e) => handleToggle(e.target.checked)}
            className="accent-vault-accent"
          />
          {t('personas.enabled')}
        </label>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="sm:col-span-2">
          <label htmlFor={`persona-${persona.id}-proxy`} className={LABEL}>
            {t('personas.proxyUrl')}
          </label>
          <input
            id={`persona-${persona.id}-proxy`}
            type="text"
            value={proxy}
            onChange={(e) => setProxyEdit(e.target.value)}
            placeholder={t('personas.proxyDirect')}
            className={INPUT}
          />
        </div>
        <div>
          <label htmlFor={`persona-${persona.id}-browser`} className={LABEL}>
            {t('personas.browserProfile')}
          </label>
          <select
            id={`persona-${persona.id}-browser`}
            value={browser}
            onChange={(e) => setBrowserEdit(e.target.value)}
            className={INPUT}
          >
            <BrowserOptions />
          </select>
        </div>
        <div>
          <label htmlFor={`persona-${persona.id}-ua`} className={LABEL}>
            {t('personas.userAgent')}
          </label>
          <input
            id={`persona-${persona.id}-ua`}
            type="text"
            value={userAgent}
            disabled={browser !== ''}
            onChange={(e) => setUaEdit(e.target.value)}
            className={INPUT}
          />
        </div>
      </div>
      <p className="text-xs text-vault-text-muted">{t('personas.identityHint')}</p>

      <div className="space-y-2">
        <p className="text-xs font-medium text-vault-text-secondary">{t('personas.accounts')}</p>
        {rowSources.map((source) => {
          const bound = persona.accounts.find((a) => a.source === source)
          const available = accountsBySource?.[source]
          const free = (available ?? []).filter(
            (a) => !takenAccounts.has(accountKey(source, a.account)),
          )
          const selected = picked[source] ?? free[0]?.account ?? ''
          return (
            <div key={source} className="flex flex-wrap items-center gap-2 text-sm">
              <span className="text-vault-text-secondary min-w-20">{source}</span>
              {bound ? (
                <>
                  <span className="text-vault-text">{bound.account}</span>
                  <button
                    type="button"
                    onClick={() => handleUnbind(source)}
                    disabled={busy}
                    className={BTN}
                  >
                    {t('personas.unbind')}
                  </button>
                </>
              ) : free.length > 0 ? (
                <>
                  <select
                    value={selected}
                    onChange={(e) => setPicked((p) => ({ ...p, [source]: e.target.value }))}
                    className="bg-vault-bg border border-vault-border rounded px-2 py-1.5 text-sm text-vault-text"
                  >
                    {free.map((a) => (
                      <option key={a.account} value={a.account}>
                        {a.account}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={() => handleBind(source, selected)}
                    disabled={busy || !selected}
                    className={BTN}
                  >
                    {t('personas.bind')}
                  </button>
                </>
              ) : available ? (
                <span className="text-xs text-vault-text-muted">
                  {t('personas.noFreeAccounts')}
                </span>
              ) : null}
            </div>
          )
        })}
      </div>

      {result && (
        <div className="text-xs space-y-1">
          <p className="text-vault-text">
            {t('personas.testResult', { ip: result.ip ?? '-', colo: result.colo ?? '-' })}
          </p>
          {result.same_ip.length > 0 && (
            <p className="text-yellow-400">
              {t('personas.sameIp', { names: result.same_ip.join(', ') })}
            </p>
          )}
          {result.same_subnet.length > 0 && (
            <p className="text-yellow-400">
              {t('personas.sameSubnet', { names: result.same_subnet.join(', ') })}
            </p>
          )}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <button type="button" onClick={handleSave} disabled={busy || !dirty} className={BTN}>
          {t('common.save')}
        </button>
        <button type="button" onClick={handleTest} disabled={busy} className={BTN}>
          {t('personas.test')}
        </button>
        <button type="button" onClick={handleDelete} disabled={busy} className={DANGER_BTN}>
          {t('personas.delete')}
        </button>
      </div>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────

export default function EgressPersonasPage() {
  useLocale()
  const authorized = useAdminGuard()

  const { data: personas, mutate } = useSWR(authorized ? 'admin-personas' : null, () =>
    api.adminPersonas.list(),
  )
  const { data: credentials } = useSWR(authorized ? 'settings-credentials' : null, () =>
    api.settings.getCredentials(),
  )

  const sources = Object.entries(credentials ?? {})
    .filter(([, status]) => status.configured)
    .map(([source]) => source)
  const sourcesKey = sources.join(',')

  // Stored accounts per source, fetched eagerly so every card can offer them.
  const { data: accountsBySource } = useSWR(
    authorized && sourcesKey ? ['persona-credential-accounts', sourcesKey] : null,
    async ([, joined]): Promise<AccountsBySource> => {
      const entries = await Promise.all(
        joined.split(',').map(async (source) => {
          const res = await api.settings.listCredentialAccounts(source)
          return [source, res.accounts] as const
        }),
      )
      return Object.fromEntries(entries)
    },
  )

  if (!authorized) return null

  // An account can back at most one persona (DB unique), so hide taken ones.
  const takenAccounts = new Set(
    (personas ?? []).flatMap((p) => p.accounts.map((a) => accountKey(a.source, a.account))),
  )
  const refresh = () => mutate()

  return (
    <div className="max-w-2xl">
      <BackButton fallback="/settings" />
      <PageHeader title={t('personas.title')} />

      <CreateForm onCreated={refresh} />

      {personas && personas.length === 0 && (
        <p className="text-sm text-vault-text-muted">{t('personas.empty')}</p>
      )}
      {(personas ?? []).map((persona) => (
        <PersonaCard
          key={persona.id}
          persona={persona}
          sources={sources}
          accountsBySource={accountsBySource}
          takenAccounts={takenAccounts}
          onChanged={refresh}
        />
      ))}
    </div>
  )
}
