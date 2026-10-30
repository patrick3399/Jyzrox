'use client'

import { Suspense } from 'react'
import { SkeletonGrid } from '@/components/Skeleton'
import { ExplorerWorkbench } from '@/components/explorer/ExplorerWorkbench'
import { PageContainer } from '@/components/layout/PageContainer'

export default function ExplorerPage() {
  return (
    <PageContainer>
    <Suspense fallback={<div className="p-6"><SkeletonGrid /></div>}>
      <ExplorerWorkbench />
    </Suspense>
    </PageContainer>
  )
}
