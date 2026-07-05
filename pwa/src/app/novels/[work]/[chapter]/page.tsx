'use client'

import { useMemo } from 'react'
import Link from 'next/link'
import { useParams, useSearchParams } from 'next/navigation'
import { ArrowLeft, ChevronLeft, ChevronRight } from 'lucide-react'
import useSWR from 'swr'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { Reader } from '@/components/novels/Reader'

export default function NovelChapterPage() {
  useLocale()
  const params = useParams<{ work: string; chapter: string }>()
  const search = useSearchParams()
  const work = decodeURIComponent(params?.work ?? '')
  const chapterName = decodeURIComponent(params?.chapter ?? '')
  const path = search?.get('path') ?? ''

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

  const chapterHref = (name: string, p: string) =>
    `/novels/${encodeURIComponent(work)}/${encodeURIComponent(name)}?path=${encodeURIComponent(p)}`

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
        <h1 className="truncate text-lg font-semibold text-vault-text">{chapterName}</h1>
      </div>

      {path ? (
        <Reader path={path} />
      ) : (
        <p className="py-10 text-center text-vault-text-muted">{t('novels.loadFailed')}</p>
      )}

      <div className="mt-6 flex items-center justify-between">
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
    </div>
  )
}
