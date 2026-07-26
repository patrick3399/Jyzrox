'use client'

import { useMemo, useState } from 'react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { BookText, ArrowLeft, Pencil, Plus, SpellCheck } from 'lucide-react'
import useSWR, { mutate } from 'swr'
import { api } from '@/lib/api'
import { novelChapterHref } from '@/lib/novels'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { useProfile } from '@/hooks/useProfile'
import { hasRole } from '@/lib/pageRegistry'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { EmptyState } from '@/components/EmptyState'
import { BackButton } from '@/components/BackButton'
import { LazyNovelCreateDialog } from '@/components/LazyDialogs'
import { WorkCategorySection } from '@/components/novels/WorkCategorySection'
import { ChapterSummaryEditor } from '@/components/novels/ChapterSummaryEditor'

export default function NovelWorkPage() {
  useLocale()
  const params = useParams<{ work: string }>()
  const router = useRouter()
  const work = decodeURIComponent(params?.work ?? '')
  const { data, isLoading } = useSWR(work ? ['novel-chapters', work] : null, ([, w]) =>
    api.novels.listChapters(w),
  )
  const { data: profile } = useProfile()
  const canEdit = hasRole(profile?.role, 'member')
  const [showCreate, setShowCreate] = useState(false)
  const [editingSummary, setEditingSummary] = useState<string | null>(null)
  const [lintOn, setLintOn] = useState(false)
  const { data: lint } = useSWR(lintOn && work ? ['novel-lint-work', work] : null, ([, w]) =>
    api.novels.lintWork(w as string),
  )
  const issueCounts = useMemo(
    () => new Map((lint?.files ?? []).map((f) => [f.path, f.issues.length])),
    [lint],
  )
  const chapters = data?.chapters ?? []
  const categories = data?.categories
  const hasAnyCategory = categories ? Object.values(categories).some((n) => n > 0) : false

  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-6">
      <Link
        href="/novels"
        className="mb-4 inline-flex items-center gap-1 text-sm text-vault-text-muted hover:text-vault-text"
      >
        <ArrowLeft className="size-4" />
        {t('novels.works')}
      </Link>
      <div className="mb-4 flex items-center justify-between gap-2">
        <h1 className="flex items-center gap-2 text-2xl font-semibold text-vault-text">
          <BookText className="size-6" />
          {work}
        </h1>
        <div className="flex shrink-0 items-center gap-2">
          {/* Linting reads every chapter, so it is opt-in rather than automatic. */}
          <button
            type="button"
            aria-pressed={lintOn}
            onClick={() => setLintOn((v) => !v)}
            className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-vault-border px-3 py-2 text-sm text-vault-text-muted hover:border-vault-accent hover:text-vault-text"
          >
            <SpellCheck className="size-4" />
            {t('novels.checkFormat')}
          </button>
          {canEdit && (
            <button
              type="button"
              onClick={() => setShowCreate(true)}
              className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-vault-border px-3 py-2 text-sm text-vault-text-muted hover:border-vault-accent hover:text-vault-text"
            >
              <Plus className="size-4" />
              {t('novels.newChapter')}
            </button>
          )}
        </div>
      </div>

      {isLoading ? (
        <LoadingSpinner />
      ) : chapters.length === 0 && !hasAnyCategory ? (
        <EmptyState icon={BookText} title={t('novels.noWorks')} />
      ) : (
        <ul className="flex flex-col gap-1">
          {chapters.map((c) => (
            <li
              key={c.path}
              className="rounded-lg border border-vault-border bg-vault-card transition-colors hover:border-vault-accent"
            >
              <div className="flex items-center gap-2 px-4 py-3">
                <Link
                  href={`/novels/${encodeURIComponent(work)}/${encodeURIComponent(c.name)}?path=${encodeURIComponent(c.path)}`}
                  className="min-w-0 flex-1"
                >
                  <span className="block truncate font-medium text-vault-text">{c.name}</span>
                  {c.summary && (
                    <span className="block truncate text-xs text-vault-text-muted">
                      {c.summary}
                    </span>
                  )}
                </Link>
                {lintOn && issueCounts.has(c.path) && (
                  <span
                    data-testid={`lint-count-${c.name}`}
                    className={`shrink-0 rounded px-1.5 py-0.5 text-xs ${
                      issueCounts.get(c.path)
                        ? 'bg-amber-500/15 text-amber-500'
                        : 'text-vault-text-muted'
                    }`}
                  >
                    {t('novels.formatIssueCount', { count: issueCounts.get(c.path) ?? 0 })}
                  </span>
                )}
                <span className="shrink-0 text-xs text-vault-text-muted">
                  {t('novels.charCount', { count: c.chars.toLocaleString() })}
                </span>
                {canEdit && (
                  <button
                    type="button"
                    aria-label={t('novels.editSummary')}
                    title={t('novels.editSummary')}
                    className="shrink-0 rounded border border-vault-border p-1 text-vault-text-muted hover:border-vault-accent hover:text-vault-text"
                    onClick={() => setEditingSummary(editingSummary === c.path ? null : c.path)}
                  >
                    <Pencil className="size-3" />
                  </button>
                )}
              </div>
              {editingSummary === c.path && (
                <ChapterSummaryEditor
                  path={c.path}
                  initial={c.summary}
                  onSaved={() => {
                    setEditingSummary(null)
                    mutate(['novel-chapters', work])
                  }}
                  onCancel={() => setEditingSummary(null)}
                />
              )}
            </li>
          ))}
        </ul>
      )}

      {categories &&
        (['extra', 'draft', 'reference', 'scrap'] as const).map((cat) => (
          <WorkCategorySection key={cat} work={work} category={cat} count={categories[cat]} />
        ))}

      {showCreate && (
        <LazyNovelCreateDialog
          mode="chapter"
          work={work}
          onClose={() => setShowCreate(false)}
          onCreated={(createdWork, chapter, path) => {
            setShowCreate(false)
            mutate(['novel-chapters', work])
            router.push(novelChapterHref(createdWork, chapter, path))
          }}
        />
      )}

      <BackButton fallback="/novels" toParent />
    </div>
  )
}
