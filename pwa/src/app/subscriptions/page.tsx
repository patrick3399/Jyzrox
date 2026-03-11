'use client'

import { useState } from 'react'
import { Rss, Plus, X, RefreshCw, Trash2, ExternalLink } from 'lucide-react'
import { toast } from 'sonner'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { useSubscriptions, useCreateSubscription, useUpdateSubscription, useDeleteSubscription, useCheckSubscription } from '@/hooks/useSubscriptions'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import type { Subscription } from '@/lib/types'

const SOURCE_COLORS: Record<string, string> = {
  pixiv: 'bg-blue-500/20 text-blue-400',
  twitter: 'bg-sky-500/20 text-sky-400',
  ehentai: 'bg-purple-500/20 text-purple-400',
}

function sourceBadge(source: string | null) {
  const cls = SOURCE_COLORS[source || ''] || 'bg-vault-border text-vault-text-muted'
  const label = source
    ? source === 'pixiv' ? 'Pixiv'
    : source === 'twitter' ? 'Twitter'
    : source === 'ehentai' ? 'E-Hentai'
    : source
    : t('subscriptions.sourceOther')
  return <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${cls}`}>{label}</span>
}

function statusBadge(status: string) {
  const cls =
    status === 'ok' ? 'text-green-400'
    : status === 'failed' ? 'text-red-400'
    : status === 'pending' ? 'text-yellow-400'
    : 'text-vault-text-muted'
  const label =
    status === 'ok' ? t('subscriptions.statusOk')
    : status === 'failed' ? t('subscriptions.statusFailed')
    : status === 'pending' ? t('subscriptions.statusPending')
    : status
  return <span className={`text-[10px] font-medium ${cls}`}>{label}</span>
}

function timeAgo(iso: string | null): string {
  if (!iso) return t('settings.tasks.never')
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return t('history.justNow')
  if (mins < 60) return t('history.minutesAgo', { n: String(mins) })
  const hours = Math.floor(mins / 60)
  if (hours < 24) return t('history.hoursAgo', { n: String(hours) })
  const days = Math.floor(hours / 24)
  return t('history.daysAgo', { n: String(days) })
}

const CRON_PRESETS = [
  { label: 'Every hour', value: '0 * * * *' },
  { label: 'Every 2 hours', value: '0 */2 * * *' },
  { label: 'Every 6 hours', value: '0 */6 * * *' },
  { label: 'Daily', value: '0 0 * * *' },
]

export default function SubscriptionsPage() {
  useLocale()
  const { data, mutate, isLoading } = useSubscriptions()
  const { trigger: createSub, isMutating: creating } = useCreateSubscription()
  const { trigger: updateSub } = useUpdateSubscription()
  const { trigger: deleteSub } = useDeleteSubscription()
  const { trigger: checkSub } = useCheckSubscription()

  const [showAdd, setShowAdd] = useState(false)
  const [url, setUrl] = useState('')
  const [name, setName] = useState('')
  const [autoDownload, setAutoDownload] = useState(true)
  const [cronExpr, setCronExpr] = useState('0 */2 * * *')
  const [checkingId, setCheckingId] = useState<number | null>(null)

  const handleAdd = async () => {
    if (!url.trim()) return
    try {
      await createSub({ url: url.trim(), name: name.trim() || undefined, auto_download: autoDownload, cron_expr: cronExpr })
      toast.success(t('subscriptions.added'))
      setUrl('')
      setName('')
      setAutoDownload(true)
      setCronExpr('0 */2 * * *')
      setShowAdd(false)
      mutate()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('subscriptions.addFailed'))
    }
  }

  const handleDelete = async (sub: Subscription) => {
    if (!confirm(t('subscriptions.deleteConfirm', { name: sub.name || sub.url }))) return
    try {
      await deleteSub(sub.id)
      toast.success(t('subscriptions.deleted'))
      mutate()
    } catch {
      toast.error(t('subscriptions.deleteFailed'))
    }
  }

  const handleToggle = async (sub: Subscription) => {
    try {
      await updateSub({ id: sub.id, data: { enabled: !sub.enabled } })
      toast.success(t('subscriptions.updated'))
      mutate()
    } catch {
      toast.error(t('subscriptions.updateFailed'))
    }
  }

  const handleCheck = async (sub: Subscription) => {
    setCheckingId(sub.id)
    try {
      await checkSub(sub.id)
      toast.success(t('subscriptions.checked'))
      mutate()
    } catch {
      toast.error(t('subscriptions.checkFailed'))
    } finally {
      setCheckingId(null)
    }
  }

  return (
    <div className="max-w-3xl mx-auto px-4 py-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Rss size={24} className="text-vault-accent" />
          <h1 className="text-xl font-bold text-vault-text">{t('subscriptions.title')}</h1>
        </div>
        <button
          onClick={() => setShowAdd(!showAdd)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm font-medium bg-vault-accent text-white hover:bg-vault-accent/90 transition-colors"
        >
          {showAdd ? <X size={16} /> : <Plus size={16} />}
          {showAdd ? t('common.cancel') : t('subscriptions.addNew')}
        </button>
      </div>

      {/* Add form */}
      {showAdd && (
        <div className="bg-vault-card border border-vault-border rounded-xl p-4 mb-6 space-y-3">
          <div>
            <label className="text-xs text-vault-text-muted block mb-1">{t('subscriptions.url')}</label>
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder={t('subscriptions.urlPlaceholder')}
              className="w-full px-3 py-2 bg-vault-input border border-vault-border rounded-lg text-sm text-vault-text placeholder-vault-text-muted"
              autoFocus
            />
          </div>
          <div>
            <label className="text-xs text-vault-text-muted block mb-1">{t('subscriptions.name')}</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('subscriptions.namePlaceholder')}
              className="w-full px-3 py-2 bg-vault-input border border-vault-border rounded-lg text-sm text-vault-text placeholder-vault-text-muted"
            />
          </div>
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <label className="text-xs text-vault-text-muted">{t('subscriptions.autoDownload')}</label>
              <button
                onClick={() => setAutoDownload(!autoDownload)}
                className={`relative w-9 h-5 rounded-full transition-colors ${autoDownload ? 'bg-vault-accent' : 'bg-vault-border'}`}
              >
                <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform shadow ${autoDownload ? 'translate-x-4' : ''}`} />
              </button>
            </div>
            <div className="flex items-center gap-2">
              <label className="text-xs text-vault-text-muted">{t('subscriptions.cronExpr')}</label>
              <select
                value={cronExpr}
                onChange={(e) => setCronExpr(e.target.value)}
                className="px-2 py-1 bg-vault-input border border-vault-border rounded text-xs text-vault-text"
              >
                {CRON_PRESETS.map((p) => (
                  <option key={p.value} value={p.value}>{p.label}</option>
                ))}
              </select>
            </div>
          </div>
          <button
            onClick={handleAdd}
            disabled={creating || !url.trim()}
            className="px-4 py-2 rounded-lg text-sm font-medium bg-vault-accent text-white hover:bg-vault-accent/90 transition-colors disabled:opacity-50"
          >
            {creating ? t('subscriptions.adding') : t('subscriptions.add')}
          </button>
        </div>
      )}

      {/* List */}
      {isLoading ? (
        <div className="flex justify-center py-12"><LoadingSpinner /></div>
      ) : !data?.subscriptions.length ? (
        <div className="text-center py-12">
          <Rss size={40} className="mx-auto text-vault-text-muted mb-3" />
          <p className="text-sm text-vault-text-muted">{t('subscriptions.noSubscriptions')}</p>
          <p className="text-xs text-vault-text-muted mt-1">{t('subscriptions.noSubscriptionsHint')}</p>
        </div>
      ) : (
        <div className="space-y-2">
          {data.subscriptions.map((sub) => (
            <div key={sub.id} className="bg-vault-card border border-vault-border rounded-xl p-3">
              <div className="flex items-start justify-between gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-sm font-medium text-vault-text truncate">
                      {sub.name || sub.url}
                    </span>
                    {sourceBadge(sub.source)}
                    {statusBadge(sub.last_status)}
                    {!sub.enabled && (
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-vault-border text-vault-text-muted">
                        {t('subscriptions.disabled')}
                      </span>
                    )}
                  </div>
                  {sub.name && (
                    <p className="text-xs text-vault-text-muted truncate mb-1">{sub.url}</p>
                  )}
                  <div className="flex flex-wrap items-center gap-3 text-[10px] text-vault-text-muted">
                    {sub.cron_expr && <span className="font-mono">{sub.cron_expr}</span>}
                    {sub.last_checked_at && (
                      <span>{t('subscriptions.lastChecked')}: {timeAgo(sub.last_checked_at)}</span>
                    )}
                    {sub.auto_download && (
                      <span className="text-vault-accent">{t('subscriptions.autoDownload')}</span>
                    )}
                  </div>
                  {sub.last_error && (
                    <p className="text-[10px] text-red-400 mt-1 truncate" title={sub.last_error}>
                      {sub.last_error}
                    </p>
                  )}
                </div>

                <div className="flex items-center gap-1 shrink-0">
                  <button
                    onClick={() => handleToggle(sub)}
                    className={`relative w-9 h-5 rounded-full transition-colors ${sub.enabled ? 'bg-vault-accent' : 'bg-vault-border'}`}
                  >
                    <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform shadow ${sub.enabled ? 'translate-x-4' : ''}`} />
                  </button>
                  <button
                    onClick={() => handleCheck(sub)}
                    disabled={checkingId === sub.id}
                    className="p-1.5 rounded text-vault-text-muted hover:text-vault-accent transition-colors"
                    title={t('subscriptions.checkNow')}
                  >
                    <RefreshCw size={14} className={checkingId === sub.id ? 'animate-spin' : ''} />
                  </button>
                  <a
                    href={sub.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="p-1.5 rounded text-vault-text-muted hover:text-vault-text transition-colors"
                  >
                    <ExternalLink size={14} />
                  </a>
                  <button
                    onClick={() => handleDelete(sub)}
                    className="p-1.5 rounded text-vault-text-muted hover:text-red-400 transition-colors"
                  >
                    <Trash2 size={14} />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
