'use client'

import { Suspense } from 'react'
import { SkeletonGrid } from '@/components/Skeleton'
import { ExplorerWorkbench } from '@/components/explorer/ExplorerWorkbench'

export default function ExplorerPage() {
  return (
    <Suspense fallback={<div className="p-6"><SkeletonGrid /></div>}>
      <ExplorerWorkbench />
    </Suspense>
  )
}
