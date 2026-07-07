'use client'

import { useState } from 'react'
import Link from 'next/link'
import { NotebookText } from 'lucide-react'
import useSWR from 'swr'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { EmptyState } from '@/components/EmptyState'
import { novelNoteHref } from '@/lib/novels'

const TYPES = ['character', 'location', 'event', 'item', 'concept'] as const

export default function NovelNotesPage() {
  useLocale()
  const [type, setType] = useState('')
  // Event notes carry a story_order — sorting by it yields the plot timeline.
  const sort = type === 'event' ? 'story_order' : ''

  const { data, isLoading } = useSWR(['novel-notes', type, sort], ([, ty, so]) =>
    api.novels.notes({ type: ty || undefined, sort: so || undefined }),
  )
  const notes = data?.notes ?? []

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-6">
      <h1 className="mb-4 flex items-center gap-2 text-2xl font-semibold text-vault-text">
        <NotebookText className="size-6" />
        {t('novels.notes')}
      </h1>

      <div className="mb-4 flex items-center gap-2">
        <label htmlFor="note-type" className="text-sm text-vault-text-muted">
          {t('novels.filterByType')}
        </label>
        <select
          id="note-type"
          value={type}
          onChange={(e) => setType(e.target.value)}
          className="rounded-lg border border-vault-border bg-vault-card px-3 py-1.5 text-sm text-vault-text"
        >
          <option value="">{t('novels.allTypes')}</option>
          {TYPES.map((ty) => (
            <option key={ty} value={ty}>
              {t(`novels.noteType.${ty}`)}
            </option>
          ))}
        </select>
      </div>

      {isLoading ? (
        <LoadingSpinner />
      ) : notes.length === 0 ? (
        <EmptyState icon={NotebookText} title={t('novels.noNotes')} />
      ) : (
        <ul className="space-y-2">
          {notes.map((n) => (
            <li key={n.path}>
              <Link
                href={novelNoteHref(n.path)}
                className="flex items-center justify-between rounded-lg border border-vault-border bg-vault-card px-4 py-3 transition-colors hover:border-vault-accent"
              >
                <span className="truncate font-medium text-vault-text">{n.title}</span>
                {n.note_type && (
                  <span className="ml-2 shrink-0 text-xs text-vault-text-muted">
                    {t(`novels.noteType.${n.note_type}`)}
                  </span>
                )}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
