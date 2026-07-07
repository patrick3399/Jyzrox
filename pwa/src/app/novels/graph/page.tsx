'use client'

import { Share2 } from 'lucide-react'
import useSWR from 'swr'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { EmptyState } from '@/components/EmptyState'
import { KnowledgeGraph } from '@/components/novels/KnowledgeGraph'

export default function NovelGraphPage() {
  useLocale()
  const { data, isLoading } = useSWR('novel-graph', () => api.novels.graph())
  const empty = !data || data.nodes.length === 0

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-6">
      <h1 className="mb-4 flex items-center gap-2 text-2xl font-semibold text-vault-text">
        <Share2 className="size-6" />
        {t('novels.graph')}
      </h1>

      {isLoading ? (
        <LoadingSpinner />
      ) : empty ? (
        <EmptyState icon={Share2} title={t('novels.graphEmpty')} />
      ) : (
        <div className="h-[70vh] overflow-hidden rounded-lg border border-vault-border bg-vault-card">
          <KnowledgeGraph data={data} />
        </div>
      )}
    </div>
  )
}
