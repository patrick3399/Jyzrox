'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { PageContainer } from '@/components/layout/PageContainer'

function PixivFollowingPageInner() {
  const router = useRouter()

  useEffect(() => {
    router.replace('/pixiv?tab=following')
  }, [router])

  return null
}

export default function PixivFollowingPage() {
  return (
    <PageContainer>
      <PixivFollowingPageInner />
    </PageContainer>
  )
}
