'use client'

import { useParams } from 'next/navigation'
import useSWR from 'swr'
import { FileText } from 'lucide-react'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { EmptyState } from '@/components/EmptyState'
import { MarkdownView } from '@/components/novels/MarkdownView'
import { AppearanceTimeline } from '@/components/novels/AppearanceTimeline'
import { PageContainer } from '@/components/layout/PageContainer'
import { PageHeader } from '@/components/layout/PageHeader'

export default function NovelNotePage() {
  useLocale()
  const params = useParams<{ path: string[] }>()
  const segments = Array.isArray(params.path) ? params.path : []
  // Next returns catch-all segments still percent-encoded (as they appear in
  // the URL). Decode each before joining, or the repo-relative path stays
  // double-encoded and every note read 404s. Tolerate a malformed segment
  // (lone `%`) by falling back to the raw value rather than throwing.
  const notePath = segments
    .map((s) => {
      try {
        return decodeURIComponent(s)
      } catch {
        return s
      }
    })
    .join('/')

  const { data: file, isLoading } = useSWR(notePath ? ['novel-note', notePath] : null, ([, p]) =>
    api.novels.readFile(p),
  )
  const { data: app } = useSWR(notePath ? ['novel-note-appearances', notePath] : null, ([, p]) =>
    api.novels.appearances(p),
  )

  return (
    <PageContainer variant="secondary">
      <div className="mx-auto max-w-3xl">
        <PageHeader
          title={notePath.split('/').pop() ?? t('novels.entityCard')}
          icon={<FileText className="size-5" />}
        />

        {isLoading ? (
          <LoadingSpinner />
        ) : !file ? (
          <EmptyState icon={FileText} title={t('novels.noteNotFound')} />
        ) : (
          <>
            <MarkdownView content={file.content} acts={file.acts} />
            <section className="mt-8">
              <h2 className="mb-3 text-lg font-semibold text-vault-text">
                {t('novels.appearances')}
              </h2>
              <AppearanceTimeline appearances={app?.appearances ?? []} />
            </section>
          </>
        )}
      </div>
    </PageContainer>
  )
}
