'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { t } from '@/lib/i18n'
import { useProfile } from '@/hooks/useProfile'
import { DedupSettingsCard } from '@/components/Dedup/DedupSettingsCard'
import { ReviewList } from '@/components/Dedup/ReviewList'

export default function DedupPage() {
  const router = useRouter()
  const { data: profile, isLoading: profileLoading } = useProfile()

  const isAdmin = profile?.role === 'admin'

  useEffect(() => {
    if (!profileLoading && profile && !isAdmin) {
      router.replace('/forbidden')
    }
  }, [profileLoading, profile, isAdmin, router])

  if (profileLoading || !profile || !isAdmin) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-vault-text-secondary text-sm">{t('common.loading')}</div>
      </div>
    )
  }

  return (
    <main className="max-w-5xl mx-auto px-4 py-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-vault-text">{t('dedup.title')}</h1>
        <p className="text-sm text-vault-text-muted mt-1">{t('dedup.subtitle')}</p>
      </div>
      <DedupSettingsCard />
      <ReviewList />
    </main>
  )
}
