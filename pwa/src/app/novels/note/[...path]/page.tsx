'use client'

import { useParams } from 'next/navigation'
import useSWR from 'swr'
import { FileText } from 'lucide-react'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { MarkdownView } from '@/components/novels/MarkdownView'
import { AppearanceTimeline } from '@/components/novels/AppearanceTimeline'

export default function NovelNotePage() {
  useLocale()
  const params = useParams<{ path: string[] }>()
  const segments = Array.isArray(params.path) ? params.path : []
  // Next decodes route segments; join back into the repo-relative note path.
  const notePath = segments.join('/')

  const { data: file, isLoading } = useSWR(notePath ? ['novel-note', notePath] : null, ([, p]) =>
    api.novels.readFile(p),
  )
  const { data: app } = useSWR(notePath ? ['novel-note-appearances', notePath] : null, ([, p]) =>
    api.novels.appearances(p),
  )

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-6">
      <h1 className="mb-4 flex items-center gap-2 text-xl font-semibold text-vault-text">
        <FileText className="size-5" />
        <span className="truncate">{notePath.split('/').pop() ?? t('novels.entityCard')}</span>
      </h1>

      {isLoading || !file ? (
        <LoadingSpinner />
      ) : (
        <>
          <MarkdownView content={file.content} acts={file.acts} />
          <section className="mt-8">
            <h2 className="mb-3 text-lg font-semibold text-vault-text">{t('novels.appearances')}</h2>
            <AppearanceTimeline appearances={app?.appearances ?? []} />
          </section>
        </>
      )}
    </div>
  )
}
