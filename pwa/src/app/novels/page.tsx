'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { BookText, NotebookText, Plus, Search, Share2 } from 'lucide-react'
import useSWR, { mutate } from 'swr'
import { api } from '@/lib/api'
import { novelChapterHref } from '@/lib/novels'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { useProfile } from '@/hooks/useProfile'
import { hasRole } from '@/lib/pageRegistry'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { EmptyState } from '@/components/EmptyState'
import { RepoStatusBar } from '@/components/novels/RepoStatusBar'
import { NovelCreateDialog } from '@/components/novels/NovelCreateDialog'

export default function NovelsPage() {
  useLocale()
  const router = useRouter()
  const { data, isLoading } = useSWR('novel-works', () => api.novels.listWorks())
  const { data: profile } = useProfile()
  const canEdit = hasRole(profile?.role, 'member')
  const [showCreate, setShowCreate] = useState(false)
  const works = data?.works ?? []

  const goToChapter = (work: string, chapter: string) => {
    router.push(novelChapterHref(work, chapter, `${work}/${chapter}.md`))
  }

  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-6">
      <div className="mb-4 flex items-center justify-between gap-2">
        <h1 className="flex items-center gap-2 text-2xl font-semibold text-vault-text">
          <BookText className="size-6" />
          {t('novels.title')}
        </h1>
        <div className="flex items-center gap-2">
          {canEdit && (
            <button
              type="button"
              onClick={() => setShowCreate(true)}
              className="inline-flex items-center gap-1 rounded-lg border border-vault-border px-3 py-2 text-sm text-vault-text-muted hover:border-vault-accent hover:text-vault-text"
            >
              <Plus className="size-4" />
              {t('novels.newWork')}
            </button>
          )}
          <Link
            href="/novels/graph"
            className="inline-flex items-center gap-1 rounded-lg border border-vault-border px-3 py-2 text-sm text-vault-text-muted hover:border-vault-accent hover:text-vault-text"
          >
            <Share2 className="size-4" />
            {t('novels.graph')}
          </Link>
          <Link
            href="/novels/notes"
            className="inline-flex items-center gap-1 rounded-lg border border-vault-border px-3 py-2 text-sm text-vault-text-muted hover:border-vault-accent hover:text-vault-text"
          >
            <NotebookText className="size-4" />
            {t('novels.notes')}
          </Link>
          <Link
            href="/novels/search"
            className="inline-flex items-center gap-1 rounded-lg border border-vault-border px-3 py-2 text-sm text-vault-text-muted hover:border-vault-accent hover:text-vault-text"
          >
            <Search className="size-4" />
            {t('novels.search')}
          </Link>
        </div>
      </div>

      <RepoStatusBar />

      {isLoading ? (
        <LoadingSpinner />
      ) : works.length === 0 ? (
        <EmptyState icon={BookText} title={t('novels.noWorks')} />
      ) : (
        <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {works.map((w) => (
            <li key={w.name}>
              <Link
                href={`/novels/${encodeURIComponent(w.name)}`}
                className="flex items-center justify-between rounded-lg border border-vault-border bg-vault-card px-4 py-3 transition-colors hover:border-vault-accent"
              >
                <span className="truncate font-medium text-vault-text">{w.name}</span>
                <span className="ml-2 shrink-0 text-sm text-vault-text-muted">
                  {t('novels.chapterCount', { count: w.chapter_count })}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}

      {showCreate && (
        <NovelCreateDialog
          mode="work"
          onClose={() => setShowCreate(false)}
          onCreated={(work, chapter) => {
            setShowCreate(false)
            mutate('novel-works')
            goToChapter(work, chapter)
          }}
        />
      )}
    </div>
  )
}
