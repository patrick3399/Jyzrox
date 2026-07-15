'use client'

import { useState } from 'react'
import { X } from 'lucide-react'
import { t } from '@/lib/i18n'
import type { SubscriptionGroup } from '@/lib/types'
import { CRON_PRESETS } from './constants'

export function GroupModal({
  group,
  onClose,
  onSave,
}: {
  group: SubscriptionGroup | null
  onClose: () => void
  onSave: (data: {
    name: string
    schedule: string
    concurrency: number
    priority: number
    enabled: boolean
  }) => Promise<void>
}) {
  const [name, setName] = useState(group?.name ?? '')
  const [schedule, setSchedule] = useState(group?.schedule ?? '0 */2 * * *')
  const [concurrency, setConcurrency] = useState(group?.concurrency ?? 2)
  const [priority, setPriority] = useState(group?.priority ?? 0)
  const [enabled, setEnabled] = useState(group?.enabled ?? true)
  const [saving, setSaving] = useState(false)

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    setSaving(true)
    try {
      await onSave({ name: name.trim(), schedule, concurrency, priority, enabled })
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60">
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="subscription-group-dialog-title"
        className="bg-vault-card border border-vault-border rounded-xl w-full max-w-md shadow-xl"
      >
        <div className="flex items-center justify-between p-4 border-b border-vault-border">
          <h2
            id="subscription-group-dialog-title"
            className="text-sm font-semibold text-vault-text"
          >
            {group ? t('subscriptions.groupEdit') : t('subscriptions.groupNew')}
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="text-vault-text-muted hover:text-vault-text"
            aria-label={t('common.close')}
          >
            <X size={16} />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="p-4 space-y-3">
          <div>
            <label className="text-xs text-vault-text-muted block mb-1">
              {t('subscriptions.groupName')}
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder={t('subscriptions.groupNamePlaceholder')}
              className="w-full px-3 py-2 bg-vault-input border border-vault-border rounded-lg text-sm text-vault-text placeholder-vault-text-muted"
              autoFocus
              disabled={group?.is_system}
            />
          </div>
          <div>
            <label className="text-xs text-vault-text-muted block mb-1">
              {t('subscriptions.groupSchedule')}
            </label>
            <div className="flex flex-wrap items-center gap-1.5">
              <input
                type="text"
                value={schedule}
                onChange={(e) => setSchedule(e.target.value)}
                className="w-32 px-2 py-1.5 bg-vault-input border border-vault-border rounded-lg text-xs font-mono text-vault-text"
              />
              {CRON_PRESETS.map((p) => (
                <button
                  key={p.value}
                  type="button"
                  onClick={() => setSchedule(p.value)}
                  className={`px-1.5 py-0.5 rounded text-[10px] transition-colors ${
                    schedule === p.value
                      ? 'bg-vault-accent/20 text-vault-accent'
                      : 'bg-vault-bg border border-vault-border text-vault-text-muted hover:text-vault-text'
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>
          <div className="flex items-center gap-4">
            <div className="flex-1">
              <label className="text-xs text-vault-text-muted block mb-1">
                {t('subscriptions.groupConcurrency')}
              </label>
              <input
                type="number"
                min={1}
                max={10}
                value={concurrency}
                onChange={(e) => setConcurrency(Number(e.target.value))}
                className="w-full px-3 py-2 bg-vault-input border border-vault-border rounded-lg text-sm text-vault-text"
              />
            </div>
            <div className="flex-1">
              <label className="text-xs text-vault-text-muted block mb-1">
                {t('subscriptions.groupPriority')}
              </label>
              <input
                type="number"
                value={priority}
                onChange={(e) => setPriority(Number(e.target.value))}
                className="w-full px-3 py-2 bg-vault-input border border-vault-border rounded-lg text-sm text-vault-text"
              />
            </div>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-xs text-vault-text-muted">
              {t('subscriptions.groupEnabled')}
            </label>
            <button
              type="button"
              onClick={() => setEnabled(!enabled)}
              className={`relative w-9 h-5 rounded-full transition-colors ${enabled ? 'bg-vault-accent' : 'bg-vault-border'}`}
            >
              <span
                className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full transition-transform shadow ${enabled ? 'translate-x-4' : ''}`}
              />
            </button>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 rounded-lg text-xs text-vault-text-muted bg-vault-input border border-vault-border hover:text-vault-text transition-colors"
            >
              {t('common.cancel')}
            </button>
            <button
              type="submit"
              disabled={saving || !name.trim()}
              className="px-4 py-1.5 rounded-lg text-xs font-medium bg-vault-accent text-white hover:bg-vault-accent/90 transition-colors disabled:opacity-50"
            >
              {saving ? t('settings.saving') : t('common.save')}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Group card ───────────────────────────────────────────────────────
