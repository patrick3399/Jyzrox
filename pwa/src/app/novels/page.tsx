'use client'

import Link from 'next/link'
import { BookText, Search } from 'lucide-react'
import useSWR from 'swr'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { EmptyState } from '@/components/EmptyState'
import { RepoStatusBar } from '@/components/novels/RepoStatusBar'

export default function NovelsPage() {
  useLocale()
  const { data, isLoading } = useSWR('novel-works', () => api.novels.listWorks())
  const works = data?.works ?? []

  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-6">
      <div className="mb-4 flex items-center justify-between gap-2">
        <h1 className="flex items-center gap-2 text-2xl font-semibold text-vault-text">
          <BookText className="size-6" />
          {t('novels.title')}
        </h1>
        <Link
          href="/novels/search"
          className="inline-flex items-center gap-1 rounded-lg border border-vault-border px-3 py-2 text-sm text-vault-text-muted hover:border-vault-accent hover:text-vault-text"
        >
          <Search className="size-4" />
          {t('novels.search')}
        </Link>
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
    </div>
  )
}
