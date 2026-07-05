'use client'

import { useState } from 'react'
import useSWR from 'swr'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { DiffView } from './DiffView'

export function HistoryPanel({ path }: { path: string }) {
  const [rev, setRev] = useState<string | null>(null)
  const { data, isLoading } = useSWR(path ? ['novel-history', path] : null, ([, p]) =>
    api.novels.history(p as string),
  )
  const { data: diffData } = useSWR(rev && path ? ['novel-diff', path, rev] : null, ([, p, r]) =>
    api.novels.diff(p as string, r as string),
  )
  const commits = data?.commits ?? []

  if (isLoading) return <LoadingSpinner />

  return (
    <div className="flex flex-col gap-3">
      <ul className="flex flex-col divide-y divide-vault-border rounded-lg border border-vault-border">
        {commits.map((c) => (
          <li key={c.hash}>
            <button
              type="button"
              aria-pressed={rev === c.hash}
              className={`flex w-full flex-col items-start px-3 py-2 text-left hover:bg-vault-card ${
                rev === c.hash ? 'bg-vault-card' : ''
              }`}
              onClick={() => setRev(rev === c.hash ? null : c.hash)}
            >
              <span className="truncate text-sm text-vault-text">{c.message}</span>
              <span className="text-xs text-vault-text-muted">
                {c.hash.slice(0, 7)} · {c.date.slice(0, 10)}
              </span>
            </button>
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
