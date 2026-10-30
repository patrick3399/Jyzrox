'use client'

import { Share2 } from 'lucide-react'
import useSWR from 'swr'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { EmptyState } from '@/components/EmptyState'
import { KnowledgeGraph } from '@/components/novels/KnowledgeGraph'
import { PageContainer } from '@/components/layout/PageContainer'
import { PageHeader } from '@/components/layout/PageHeader'

export default function NovelGraphPage() {
  useLocale()
  const { data, isLoading } = useSWR('novel-graph', () => api.novels.graph())
  const empty = !data || data.nodes.length === 0

  return (
    <PageContainer variant="secondary">
      <PageHeader title={t('novels.graph')} icon={<Share2 className="size-6" />} />

      {isLoading ? (
        <LoadingSpinner />
      ) : empty ? (
        <EmptyState icon={Share2} title={t('novels.graphEmpty')} />
      ) : (
        <div className="h-[70vh] overflow-hidden rounded-lg border border-vault-border bg-vault-card">
          <KnowledgeGraph data={data} />
        </div>
      )}
    </PageContainer>
  )
}
