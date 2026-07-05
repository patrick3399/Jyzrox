'use client'

import { useState } from 'react'
import { RefreshCw, Lock, RotateCcw } from 'lucide-react'
import { toast } from 'sonner'
import useSWR from 'swr'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { useProfile } from '@/hooks/useProfile'
import { hasRole } from '@/lib/pageRegistry'

export function RepoStatusBar() {
  const { data, mutate } = useSWR('novel-status', () => api.novels.status())
  const { data: profile } = useProfile()
  const isAdmin = hasRole(profile?.role, 'admin')
  const [busy, setBusy] = useState(false)

  if (!data) return null

  const handleSync = async () => {
    setBusy(true)
    try {
      await api.novels.sync()
      await mutate()
      toast.success(t('novels.synced'))
    } catch {
      toast.error(t('novels.loadFailed'))
    } finally {
      setBusy(false)
    }
  }

  const handleReset = async () => {
    if (!window.confirm(t('novels.resetConfirm'))) return
    setBusy(true)
    try {
      await api.novels.reset()
      await mutate()
      toast.success(t('novels.resetDone'))
    } catch {
      toast.error(t('novels.loadFailed'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="mb-4 flex flex-col gap-2">
      {data.locked && (
        <div
          role="alert"
          className="flex items-center gap-2 rounded-lg border border-red-500/50 bg-red-500/10 px-3 py-2 text-sm text-red-400"
        >
          <Lock className="size-4 shrink-0" />
          {t('novels.locked')}
        </div>
      )}
      <div className="flex items-center gap-3 text-xs text-vault-text-muted">
        {data.ahead > 0 && (
          <span data-testid="unpushed-count">{t('novels.unpushed', { count: data.ahead })}</span>
        )}
        <button
          type="button"
          disabled={busy}
          className="inline-flex items-center gap-1 rounded border border-vault-border px-2 py-1 hover:border-vault-accent disabled:opacity-50"
          onClick={handleSync}
        >
          <RefreshCw className={`size-3 ${busy ? 'animate-spin' : ''}`} />
          {t('novels.sync')}
        </button>
        {isAdmin && (
          <button
            type="button"
            disabled={busy}
            className="inline-flex items-center gap-1 rounded border border-vault-border px-2 py-1 text-red-400 hover:border-red-500 disabled:opacity-50"
            onClick={handleReset}
          >
            <RotateCcw className="size-3" />
            {t('novels.reset')}
          </button>
        )}
      </div>
    </div>
  )
}
