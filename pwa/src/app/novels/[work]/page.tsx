'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useParams, useRouter } from 'next/navigation'
import { BookText, ArrowLeft, Plus } from 'lucide-react'
import useSWR, { mutate } from 'swr'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { useProfile } from '@/hooks/useProfile'
import { hasRole } from '@/lib/pageRegistry'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { EmptyState } from '@/components/EmptyState'
import { NovelCreateDialog } from '@/components/novels/NovelCreateDialog'

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
  const chapters = data?.chapters ?? []

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

      {isLoading ? (
        <LoadingSpinner />
      ) : chapters.length === 0 ? (
        <EmptyState icon={BookText} title={t('novels.noWorks')} />
      ) : (
        <ul className="flex flex-col gap-1">
          {chapters.map((c) => (
            <li key={c.path}>
              <Link
                href={`/novels/${encodeURIComponent(work)}/${encodeURIComponent(c.name)}?path=${encodeURIComponent(c.path)}`}
                className="flex items-center justify-between rounded-lg border border-vault-border bg-vault-card px-4 py-3 transition-colors hover:border-vault-accent"
              >
                <span className="truncate font-medium text-vault-text">{c.name}</span>
                <span className="ml-2 shrink-0 text-xs text-vault-text-muted">
                  {c.chars.toLocaleString()}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}

      {showCreate && (
        <NovelCreateDialog
          mode="chapter"
          work={work}
          onClose={() => setShowCreate(false)}
          onCreated={(createdWork, chapter) => {
            setShowCreate(false)
            mutate(['novel-chapters', work])
            const path = `${createdWork}/${chapter}.md`
            router.push(
              `/novels/${encodeURIComponent(createdWork)}/${encodeURIComponent(chapter)}?path=${encodeURIComponent(path)}`,
            )
          }}
        />
      )}
    </div>
  )
}
