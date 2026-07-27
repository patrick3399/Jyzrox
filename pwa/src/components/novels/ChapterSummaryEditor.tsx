'use client'

import { useEffect, useState } from 'react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'

/**
 * Inline editor for one file's `summary:` frontmatter.
 *
 * `base_sha` is captured when the editor opens, NOT when Save is pressed.
 * Reading HEAD at save time makes the sha match by construction, so the
 * server's stale-write check can never fire and the author silently overwrites
 * whatever landed while they were typing. Opening-time capture is what makes a
 * 409 possible; the conflict branch below then lets the author decide.
 */
export function ChapterSummaryEditor({
  path,
  initial,
  onSaved,
  onCancel,
}: {
  path: string
  initial?: string | null
  onSaved: () => void
  onCancel: () => void
}) {
  const [text, setText] = useState(initial ?? '')
  const [saving, setSaving] = useState(false)
  const [baseSha, setBaseSha] = useState<string | null>(null)
  const [conflictSha, setConflictSha] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api.novels
      .status()
      .then((s) => {
        if (!cancelled) setBaseSha(s.head)
      })
      .catch(() => {
        if (!cancelled) toast.error(t('novels.summaryFailed'))
      })
    return () => {
      cancelled = true
    }
  }, [path])

  const save = async (sha: string) => {
    setSaving(true)
    try {
      const res = await api.novels.putSummary(path, text, sha)
      if (res.ok) {
        toast.success(t('novels.summarySaved'))
        onSaved()
        return
      }
      if (res.status === 409 && res.conflict) {
        // Someone committed while this editor was open — keep the author's text
        // and let them choose, rather than clobbering the newer summary.
        setConflictSha(res.conflict.current_sha)
        toast.error(t('novels.summaryConflict'))
        return
      }
      toast.error(t('novels.summaryFailed'))
    } catch {
      toast.error(t('novels.summaryFailed'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="border-t border-vault-border px-4 py-3">
      <label className="mb-1 block text-xs font-semibold text-vault-text-muted" htmlFor={`sum-${path}`}>
        {t('novels.summary')}
      </label>
      <textarea
        id={`sum-${path}`}
        rows={2}
        value={text}
        placeholder={t('novels.summaryPlaceholder')}
        onChange={(e) => setText(e.target.value)}
        className="w-full resize-y rounded border border-vault-border bg-vault-input p-2 text-sm text-vault-text"
      />
      {conflictSha && (
        <p role="alert" className="mt-2 text-xs text-amber-500">
          {t('novels.summaryConflict')}
        </p>
      )}
      <div className="mt-2 flex justify-end gap-2">
        <button
          type="button"
          className="rounded border border-vault-border px-3 py-1 text-xs text-vault-text-muted hover:text-vault-text"
          onClick={onCancel}
        >
          {t('novels.cancel')}
        </button>
        {conflictSha ? (
          <>
            <button
              type="button"
              className="rounded border border-vault-border px-3 py-1 text-xs text-vault-text-muted hover:text-vault-text"
              onClick={onSaved}
            >
              {t('novels.summaryDiscardMine')}
            </button>
            <button
              type="button"
              disabled={saving}
              className="rounded bg-amber-600 px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
              onClick={() => save(conflictSha)}
            >
              {t('novels.summaryOverwrite')}
            </button>
          </>
        ) : (
          <button
            type="button"
            disabled={saving || baseSha === null}
            className="rounded bg-vault-accent px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
            onClick={() => baseSha !== null && save(baseSha)}
          >
            {t('novels.save')}
          </button>
        )}
      </div>
    </div>
  )
}
