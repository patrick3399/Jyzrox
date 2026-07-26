'use client'

import { useMemo, useState } from 'react'
import Link from 'next/link'
import { useParams, useSearchParams } from 'next/navigation'
import { mutate } from 'swr'
import { ArrowLeft, ChevronLeft, ChevronRight, History, Pencil } from 'lucide-react'
import useSWR from 'swr'
import { api } from '@/lib/api'
import { novelChapterHref } from '@/lib/novels'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { useProfile } from '@/hooks/useProfile'
import { hasRole } from '@/lib/pageRegistry'
import { BackButton } from '@/components/BackButton'
import { Reader } from '@/components/novels/Reader'
import { Editor } from '@/components/novels/Editor'
import { HistoryPanel } from '@/components/novels/HistoryPanel'

export default function NovelChapterPage() {
  useLocale()
  const params = useParams<{ work: string; chapter: string }>()
  const search = useSearchParams()
  const work = decodeURIComponent(params?.work ?? '')
  const chapterName = decodeURIComponent(params?.chapter ?? '')
  const path = search?.get('path') ?? ''
  const [editing, setEditing] = useState(false)
  const [showHistory, setShowHistory] = useState(false)
  const { data: profile } = useProfile()
  const canEdit = hasRole(profile?.role, 'member')

  const { data } = useSWR(work ? ['novel-chapters', work] : null, ([, w]) =>
    api.novels.listChapters(w),
  )

  const { prev, next } = useMemo(() => {
    const chapters = data?.chapters ?? []
    const idx = chapters.findIndex((c) => c.path === path)
    return {
      prev: idx > 0 ? chapters[idx - 1] : null,
      next: idx >= 0 && idx < chapters.length - 1 ? chapters[idx + 1] : null,
    }
  }, [data?.chapters, path])

  const chapterHref = (name: string, p: string) => novelChapterHref(work, name, p)

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-6">
      <div className="mb-4 flex items-center justify-between gap-2">
        <Link
          href={`/novels/${encodeURIComponent(work)}`}
          className="inline-flex items-center gap-1 text-sm text-vault-text-muted hover:text-vault-text"
        >
          <ArrowLeft className="size-4" />
          {work}
        </Link>
        <div className="flex min-w-0 items-center gap-3">
          <h1 className="truncate text-lg font-semibold text-vault-text">{chapterName}</h1>
          {path && !editing && (
            <button
              type="button"
              aria-pressed={showHistory}
              className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-vault-border px-2 py-1 text-xs text-vault-text-muted hover:border-vault-accent hover:text-vault-text"
              onClick={() => setShowHistory((v) => !v)}
            >
              <History className="size-3" />
              {t('novels.history')}
            </button>
          )}
          {canEdit && !editing && path && (
            <button
              type="button"
              className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-vault-border px-2 py-1 text-xs text-vault-text-muted hover:border-vault-accent hover:text-vault-text"
              onClick={() => setEditing(true)}
            >
              <Pencil className="size-3" />
              {t('novels.edit')}
            </button>
          )}
        </div>
      </div>

      {!path ? (
        <p className="py-10 text-center text-vault-text-muted">{t('novels.loadFailed')}</p>
      ) : editing ? (
        <Editor
          path={path}
          onSaved={() => {
            setEditing(false)
            mutate(['novel-file', path])
            mutate(['novel-edit', path])
          }}
          onCancel={() => setEditing(false)}
        />
      ) : showHistory ? (
        <HistoryPanel path={path} canEdit={canEdit} />
      ) : (
        <Reader path={path} canEdit={canEdit} />
      )}

      <div className="mt-6 mb-[var(--fab-offset)] flex items-center justify-between">
        {prev ? (
          <Link
            href={chapterHref(prev.name, prev.path)}
            className="inline-flex items-center gap-1 rounded-lg border border-vault-border px-3 py-2 text-sm text-vault-text hover:border-vault-accent"
          >
            <ChevronLeft className="size-4" />
            {t('novels.prevChapter')}
          </Link>
        ) : (
          <span />
        )}
        {next ? (
          <Link
            href={chapterHref(next.name, next.path)}
            className="inline-flex items-center gap-1 rounded-lg border border-vault-border px-3 py-2 text-sm text-vault-text hover:border-vault-accent"
          >
            {t('novels.nextChapter')}
            <ChevronRight className="size-4" />
          </Link>
        ) : (
          <span />
        )}
      </div>

      {/* Always-reachable back that climbs to the work's chapter list (its
          structural parent), not the browser's previous page — a chapter opened
          from search or an adjacent chapter still goes up to the chapter list. */}
      <BackButton fallback={`/novels/${encodeURIComponent(work)}`} toParent />
    </div>
  )
}
