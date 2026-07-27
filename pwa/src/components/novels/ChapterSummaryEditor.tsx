'use client'

import { useState } from 'react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'

/**
 * Inline editor for one file's `summary:` frontmatter. Saving is a normal
 * commit, so it reads HEAD fresh right before writing — the same lost-update
 * guard every other novel write uses.
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

  const save = async () => {
    setSaving(true)
    try {
      const status = await api.novels.status()
      await api.novels.putSummary(path, text, status.head)
      toast.success(t('novels.summarySaved'))
      onSaved()
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
      <div className="mt-2 flex justify-end gap-2">
        <button
          type="button"
          className="rounded border border-vault-border px-3 py-1 text-xs text-vault-text-muted hover:text-vault-text"
          onClick={onCancel}
        >
          {t('novels.cancel')}
        </button>
        <button
          type="button"
          disabled={saving}
          className="rounded bg-vault-accent px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
          onClick={save}
        >
          {t('novels.save')}
        </button>
      </div>
    </div>
  )
}
