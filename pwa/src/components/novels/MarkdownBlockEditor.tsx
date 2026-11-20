'use client'

import { useState, useRef, useEffect, useCallback } from 'react'
import { t } from '@/lib/i18n'
import { Button } from '@/components/ui/button'

export type BlockRange = { start: number; end: number }

const draftKey = (path: string, baseSha: string, r: BlockRange) =>
  `novel:blockdraft:${path}:${baseSha}:${r.start}-${r.end}`

/** In-place raw editor for a single block; seeded from the block's source lines. */
export function BlockEditor({
  path,
  baseSha,
  range,
  initialText,
  saving,
  onSave,
  onCancel,
}: {
  path: string
  baseSha: string
  range: BlockRange
  initialText: string
  saving: boolean
  onSave: (range: BlockRange, text: string) => void
  onCancel: () => void
}) {
  const key = draftKey(path, baseSha, range)
  const [text, setText] = useState(() => {
    try {
      const draft = window.localStorage.getItem(key)
      if (draft !== null && draft !== initialText) return draft
    } catch {
      // ignore
    }
    return initialText
  })
  const draftTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const onChange = useCallback(
    (value: string) => {
      setText(value)
      if (draftTimer.current) clearTimeout(draftTimer.current)
      draftTimer.current = setTimeout(() => {
        try {
          window.localStorage.setItem(key, value)
        } catch {
          // ignore quota
        }
      }, 500)
    },
    [key],
  )

  useEffect(() => {
    return () => {
      if (draftTimer.current) clearTimeout(draftTimer.current)
    }
  }, [])

  const clearDraft = useCallback(() => {
    try {
      window.localStorage.removeItem(key)
    } catch {
      // ignore
    }
  }, [key])

  return (
    <div className="my-2 rounded-lg border border-vault-accent bg-vault-card p-2">
      <textarea
        autoFocus
        aria-label={t('novels.editThisBlock')}
        className="min-h-24 w-full resize-y rounded border border-vault-border bg-vault-input p-2 font-mono text-sm text-vault-text"
        value={text}
        onChange={(e) => onChange(e.target.value)}
      />
      <div className="mt-2 flex justify-end gap-2">
        <Button
          variant="secondary"
          size="sm"
          className="text-xs"
          onClick={() => {
            clearDraft()
            onCancel()
          }}
        >
          {t('novels.cancel')}
        </Button>
        <Button
          variant="primary"
          size="sm"
          className="text-xs"
          disabled={saving}
          onClick={() => {
            clearDraft()
            onSave(range, text)
          }}
        >
          {t('novels.save')}
        </Button>
      </div>
    </div>
  )
}
