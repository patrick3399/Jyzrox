'use client'

import { useState } from 'react'
import useSWR, { mutate } from 'swr'
import { toast } from 'sonner'
import { GitCompare, RotateCcw, X } from 'lucide-react'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { DiffView } from './DiffView'

export function HistoryPanel({ path, canEdit = false }: { path: string; canEdit?: boolean }) {
  const [rev, setRev] = useState<string | null>(null)
  // Compare base: when set, the diff is base…rev instead of rev against its parent.
  const [base, setBase] = useState<string | null>(null)
  const [reverting, setReverting] = useState(false)
  const { data, isLoading } = useSWR(path ? ['novel-history', path] : null, ([, p]) =>
    api.novels.history(p as string),
  )
  const { data: diffData } = useSWR(
    rev && path ? ['novel-diff', path, rev, base] : null,
    ([, p, r, b]) => api.novels.diff(p as string, r as string, (b as string) ?? undefined),
  )
  const commits = data?.commits ?? []

  const handleRevert = async (hash: string) => {
    if (!window.confirm(t('novels.revertConfirm', { rev: hash.slice(0, 7) }))) return
    setReverting(true)
    try {
      // Read HEAD fresh: the revert carries the same lost-update guard as a save,
      // so a commit that landed since this panel loaded must be seen, not clobbered.
      const status = await api.novels.status()
      await api.novels.revertFile(path, hash, status.head)
      toast.success(t('novels.reverted'))
      setRev(null)
      setBase(null)
      await Promise.all([
        mutate(['novel-history', path]),
        mutate(['novel-file', path]),
        mutate('novel-status'),
      ])
    } catch {
      toast.error(t('novels.revertFailed'))
    } finally {
      setReverting(false)
    }
  }

  if (isLoading) return <LoadingSpinner />

  return (
    <div className="flex flex-col gap-3">
      {base && (
        <div className="flex items-center gap-2 text-xs text-vault-text-muted">
          <span data-testid="compare-base">
            {t('novels.compareBase', { rev: base.slice(0, 7) })}
          </span>
          <button
            type="button"
            aria-label={t('novels.compareClear')}
            className="inline-flex items-center rounded border border-vault-border p-0.5 hover:border-vault-accent"
            onClick={() => setBase(null)}
          >
            <X className="size-3" />
          </button>
        </div>
      )}
      <ul className="flex flex-col divide-y divide-vault-border rounded-lg border border-vault-border">
        {commits.map((c) => (
          <li key={c.hash} className="flex items-stretch">
            <button
              type="button"
              aria-pressed={rev === c.hash}
              className={`flex min-w-0 flex-1 flex-col items-start px-3 py-2 text-left hover:bg-vault-card ${
                rev === c.hash ? 'bg-vault-card' : ''
              }`}
              onClick={() => setRev(rev === c.hash ? null : c.hash)}
            >
              <span className="truncate text-sm text-vault-text">{c.message}</span>
              <span className="text-xs text-vault-text-muted">
                {c.hash.slice(0, 7)} · {c.date.slice(0, 10)}
              </span>
            </button>
            <div className="flex shrink-0 items-center gap-1 pr-2">
              <button
                type="button"
                aria-pressed={base === c.hash}
                aria-label={t('novels.compareWith', { rev: c.hash.slice(0, 7) })}
                title={t('novels.compareWith', { rev: c.hash.slice(0, 7) })}
                className={`rounded border border-vault-border p-1 text-vault-text-muted hover:border-vault-accent hover:text-vault-text ${
                  base === c.hash ? 'border-vault-accent text-vault-text' : ''
                }`}
                onClick={() => setBase(base === c.hash ? null : c.hash)}
              >
                <GitCompare className="size-3" />
              </button>
              {canEdit && (
                <button
                  type="button"
                  disabled={reverting}
                  aria-label={t('novels.revertTo', { rev: c.hash.slice(0, 7) })}
                  title={t('novels.revertTo', { rev: c.hash.slice(0, 7) })}
                  className="rounded border border-vault-border p-1 text-vault-text-muted hover:border-vault-accent hover:text-vault-text disabled:opacity-50"
                  onClick={() => handleRevert(c.hash)}
                >
                  <RotateCcw className="size-3" />
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
      {rev && diffData && <DiffView diff={diffData.diff} />}
      {commits.length === 0 && (
        <p className="py-6 text-center text-sm text-vault-text-muted">{t('novels.noResults')}</p>
      )}
    </div>
  )
}
