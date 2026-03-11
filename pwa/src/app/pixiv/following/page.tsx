'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

export default function PixivFollowingPage() {
  const router = useRouter()

  useEffect(() => {
    router.replace('/pixiv?tab=following')
  }, [router])

  return null
}
