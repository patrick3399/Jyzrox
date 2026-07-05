'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import useSWR from 'swr'
import { api, type NovelFile } from '@/lib/api'
import { t } from '@/lib/i18n'
import { LoadingSpinner } from '@/components/LoadingSpinner'

const draftKey = (path: string, baseSha: string) => `novel:draft:${path}:${baseSha}`

export function Editor({
  path,
  onSaved,
  onCancel,
}: {
  path: string
  onSaved: () => void
  onCancel: () => void
}) {
  const { data, isLoading } = useSWR<NovelFile>(path ? ['novel-edit', path] : null, ([, p]) =>
    api.novels.readFile(p as string),
  )
  const [content, setContent] = useState('')
  const [message, setMessage] = useState('')
  const [conflict, setConflict] = useState<{ current: string; current_sha: string } | null>(null)
  const [draftFound, setDraftFound] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const baseShaRef = useRef<string>('')
  const draftTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  // Seed from server; detect a saved draft for this exact base_sha.
  useEffect(() => {
    if (!data) return
    baseShaRef.current = data.base_sha
    setContent(data.content)
    try {
      const draft = window.localStorage.getItem(draftKey(path, data.base_sha))
      if (draft !== null && draft !== data.content) setDraftFound(draft)
    } catch {
      // ignore
    }
  }, [data, path])

  const scheduleDraft = useCallback(
    (next: string) => {
      if (draftTimer.current) clearTimeout(draftTimer.current)
      draftTimer.current = setTimeout(() => {
        try {
          window.localStorage.setItem(draftKey(path, baseShaRef.current), next)
        } catch {
          // ignore quota
        }
      }, 500)
    },
    [path],
  )

  const onContentChange = useCallback(
    (value: string) => {
      setContent(value)
      scheduleDraft(value)
    },
    [scheduleDraft],
  )

  const clearDraft = useCallback(() => {
    try {
      window.localStorage.removeItem(draftKey(path, baseShaRef.current))
    } catch {
      // ignore
    }
  }, [path])

  const handleSave = useCallback(async () => {
    setSaving(true)
    setConflict(null)
    try {
      const result = await api.novels.writeFile({
        path,
        content,
        base_sha: baseShaRef.current,
        message: message || undefined,
      })
      if (result.ok) {
        clearDraft()
        toast.success(t('novels.saved'))
        onSaved()
      } else if (result.conflict) {
        setConflict(result.conflict)
      } else {
        toast.error(result.message || t('novels.saveFailed'))
      }
    } catch {
      toast.error(t('novels.saveFailed'))
    } finally {
      setSaving(false)
    }
  }, [path, content, message, clearDraft, onSaved])

  useEffect(() => {
    return () => {
      if (draftTimer.current) clearTimeout(draftTimer.current)
    }
  }, [])

  if (isLoading) return <LoadingSpinner />

  return (
    <div className="flex flex-col gap-3">
      {draftFound !== null && (
        <div
          role="alert"
          className="flex items-center justify-between gap-2 rounded-lg border border-vault-accent bg-vault-card px-3 py-2 text-sm"
        >
          <span className="text-vault-text">{t('novels.draftRestored')}</span>
          <span className="flex gap-2">
            <button
              type="button"
              className="rounded border border-vault-accent px-2 py-1 text-xs text-vault-text"
              onClick={() => {
                setContent(draftFound)
                setDraftFound(null)
              }}
            >
              {t('novels.restoreDraft')}
            </button>
            <button
              type="button"
              className="rounded border border-vault-border px-2 py-1 text-xs text-vault-text-muted"
              onClick={() => {
                clearDraft()
                setDraftFound(null)
              }}
            >
              {t('novels.discardDraft')}
            </button>
          </span>
        </div>
      )}

      {conflict && (
        <div className="rounded-lg border border-red-500/50 bg-vault-card p-3 text-sm">
          <p className="mb-2 font-medium text-red-400">{t('novels.staleConflict')}</p>
          <p className="mb-1 text-xs text-vault-text-muted">{t('novels.currentVersion')}</p>
          <pre className="max-h-48 overflow-auto whitespace-pre-wrap rounded bg-black/20 p-2 text-xs text-vault-text">
            {conflict.current}
          </pre>
        </div>
      )}

      <textarea
        aria-label={t('novels.edit')}
        className="min-h-[50vh] w-full rounded-lg border border-vault-border bg-vault-input p-3 font-mono text-sm text-vault-text"
        value={content}
        onChange={(e) => onContentChange(e.target.value)}
      />

      <input
        type="text"
        placeholder={t('novels.commitMessage')}
        className="w-full rounded-lg border border-vault-border bg-vault-input px-3 py-2 text-sm text-vault-text"
        value={message}
        onChange={(e) => setMessage(e.target.value)}
      />

      <div className="flex justify-end gap-2">
        <button
          type="button"
          className="rounded-lg border border-vault-border px-3 py-2 text-sm text-vault-text-muted hover:text-vault-text"
          onClick={onCancel}
        >
          {t('novels.cancel')}
        </button>
        <button
          type="button"
          disabled={saving}
          className="rounded-lg bg-vault-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          onClick={handleSave}
        >
          {t('novels.save')}
        </button>
      </div>
    </div>
  )
}
