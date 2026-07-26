'use client'

import { useState } from 'react'
import useSWR, { mutate } from 'swr'
import { toast } from 'sonner'
import { CheckCircle2, Wand2 } from 'lucide-react'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { LoadingSpinner } from '@/components/LoadingSpinner'

/** Wording for a rule id, falling back to the id itself for a rule the UI does
 * not know yet (a new backend rule must never render as a blank line). */
export function ruleLabel(rule: string): string {
  const key = `novels.lint.${rule}`
  const label = t(key)
  return label === key ? rule : label
}

export function FormatPanel({ path, canEdit = false }: { path: string; canEdit?: boolean }) {
  const [fixing, setFixing] = useState(false)
  const { data, isLoading } = useSWR(path ? ['novel-lint', path] : null, ([, p]) =>
    api.novels.lintFile(p as string),
  )
  const issues = data?.issues ?? []

  const handleFix = async () => {
    setFixing(true)
    try {
      const status = await api.novels.status()
      const res = await api.novels.fixFile(path, status.head)
      toast.success(
        res.changes.length > 0
          ? t('novels.formatFixed', { count: res.changes.length })
          : t('novels.formatNothingToFix'),
      )
      await Promise.all([
        mutate(['novel-lint', path]),
        mutate(['novel-file', path]),
        mutate('novel-status'),
      ])
    } catch {
      toast.error(t('novels.formatFixFailed'))
    } finally {
      setFixing(false)
    }
  }

  if (isLoading) return <LoadingSpinner />

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm text-vault-text-muted">
          {t('novels.formatIssueCount', { count: issues.length })}
        </p>
        {canEdit && issues.length > 0 && (
          <button
            type="button"
            disabled={fixing}
            className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-vault-border px-2 py-1 text-xs text-vault-text-muted hover:border-vault-accent hover:text-vault-text disabled:opacity-50"
            onClick={handleFix}
          >
            <Wand2 className="size-3" />
            {t('novels.formatFix')}
          </button>
        )}
      </div>

      {issues.length === 0 ? (
        <p className="flex items-center justify-center gap-2 py-6 text-sm text-vault-text-muted">
          <CheckCircle2 className="size-4 text-green-500" />
          {t('novels.formatClean')}
        </p>
      ) : (
        <ul
          data-testid="format-issues"
          className="flex flex-col divide-y divide-vault-border rounded-lg border border-vault-border"
        >
          {issues.map((issue) => (
            <li key={`${issue.line}-${issue.rule}`} className="flex flex-col gap-0.5 px-3 py-2">
              <span className="text-sm text-vault-text">
                {t('novels.formatAtLine', { line: issue.line })} · {ruleLabel(issue.rule)}
              </span>
              {issue.text && (
                <span className="truncate font-mono text-xs text-vault-text-muted">
                  {issue.text}
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
