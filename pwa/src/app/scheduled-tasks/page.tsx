'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { t } from '@/lib/i18n'
import { useProfile } from '@/hooks/useProfile'
import { TaskList } from '@/components/ScheduledTasks/TaskList'

export default function ScheduledTasksPage() {
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
    <main className="max-w-4xl mx-auto px-4 py-8 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-vault-text">{t('scheduledTasks.title')}</h1>
        <p className="text-sm text-vault-text-muted mt-1">{t('scheduledTasks.subtitle')}</p>
      </div>
      <TaskList pollWhileRunning={true} />
    </main>
  )
}
