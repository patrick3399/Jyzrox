'use client'

import { useState } from 'react'
import { X } from 'lucide-react'
import { api } from '@/lib/api'
import { novelFilePath } from '@/lib/novels'
import { t } from '@/lib/i18n'

/**
 * Create a new work (folder via its first chapter) or a new chapter in an
 * existing work. Both go through api.novels.createFile (PUT /file, create:true),
 * so the backend refuses to clobber an existing file.
 */
export function NovelCreateDialog({
  mode,
  work,
  onClose,
  onCreated,
}: {
  mode: 'work' | 'chapter'
  work?: string
  onClose: () => void
  onCreated: (createdWork: string, chapterName: string, path: string) => void
}) {
  const [workName, setWorkName] = useState('')
  const [chapterName, setChapterName] = useState('')
  const [category, setCategory] = useState('') // '' = main text at work root
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  const targetWork = mode === 'work' ? workName.trim() : (work ?? '')

  const invalid = (s: string) => s.includes('/') || s.includes('\\')

  const handleCreate = async () => {
    const chap = chapterName.trim()
    if ((mode === 'work' && !targetWork) || !chap) {
      setError(t('novels.nameRequired'))
      return
    }
    if (invalid(targetWork) || invalid(chap)) {
      setError(t('novels.nameInvalid'))
      return
    }
    setError(null)
    setSaving(true)
    const subdir = mode === 'chapter' ? category || undefined : undefined
    try {
      const result = await api.novels.createFile(targetWork, chap, subdir)
      if (result.ok) {
        onCreated(targetWork, chap, novelFilePath(targetWork, chap, subdir))
      } else if (result.message === 'file exists') {
        setError(t('novels.fileExists'))
      } else {
        setError(result.message || t('novels.createFailed'))
      }
    } catch {
      setError(t('novels.createFailed'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-label={mode === 'work' ? t('novels.newWork') : t('novels.newChapter')}
        className="mx-4 w-full max-w-sm rounded-xl border border-vault-border bg-vault-card"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-vault-border px-4 py-3">
          <h3 className="text-sm font-semibold text-vault-text">
            {mode === 'work' ? t('novels.newWork') : t('novels.newChapter')}
          </h3>
          <button
            type="button"
            aria-label={t('novels.cancel')}
            onClick={onClose}
            className="text-vault-text-muted transition-colors hover:text-vault-text"
          >
            <X size={16} />
          </button>
        </div>

        <div className="flex flex-col gap-3 p-4">
          {mode === 'work' && (
            <label className="flex flex-col gap-1 text-xs text-vault-text-muted">
              {t('novels.workName')}
              <input
                type="text"
                autoFocus
                value={workName}
                onChange={(e) => setWorkName(e.target.value)}
                className="rounded-lg border border-vault-border bg-vault-input px-3 py-2 text-sm text-vault-text"
              />
            </label>
          )}
          <label className="flex flex-col gap-1 text-xs text-vault-text-muted">
            {mode === 'work' ? t('novels.firstChapterName') : t('novels.chapterName')}
            <input
              type="text"
              autoFocus={mode === 'chapter'}
              value={chapterName}
              onChange={(e) => setChapterName(e.target.value)}
              className="rounded-lg border border-vault-border bg-vault-input px-3 py-2 text-sm text-vault-text"
            />
          </label>

          {mode === 'chapter' && (
            <label className="flex flex-col gap-1 text-xs text-vault-text-muted">
              {t('novels.createCategory')}
              <select
                value={category}
                onChange={(e) => setCategory(e.target.value)}
                className="rounded-lg border border-vault-border bg-vault-input px-3 py-2 text-sm text-vault-text"
              >
                <option value="">{t('novels.categoryMain')}</option>
                <option value="番外">{t('novels.categoryExtra')}</option>
                <option value="草稿">{t('novels.categoryDraft')}</option>
                <option value="參考">{t('novels.categoryReference')}</option>
                <option value="廢案">{t('novels.categoryScrap')}</option>
              </select>
            </label>
          )}

          {error && <p className="text-xs text-red-400">{error}</p>}

          <div className="flex justify-end gap-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg border border-vault-border px-3 py-2 text-sm text-vault-text-muted hover:text-vault-text"
            >
              {t('novels.cancel')}
            </button>
            <button
              type="button"
              disabled={saving}
              onClick={handleCreate}
              className="rounded-lg bg-vault-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {t('novels.create')}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
