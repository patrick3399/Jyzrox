'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import { t } from '@/lib/i18n'
import { useProfile } from '@/hooks/useProfile'
import { TaskList } from '@/components/ScheduledTasks/TaskList'
import { BackupList } from '@/components/Backups/BackupList'
import { PageContainer } from '@/components/layout/PageContainer'
import { PageHeader } from '@/components/layout/PageHeader'

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
      <PageContainer variant="secondary">
        <div className="flex items-center justify-center min-h-[60vh]">
          <div className="text-vault-text-secondary text-sm">{t('common.loading')}</div>
        </div>
      </PageContainer>
    )
  }

  return (
    <PageContainer variant="secondary">
      <PageHeader title={t('scheduledTasks.title')} subtitle={t('scheduledTasks.subtitle')} />
      <main className="space-y-6">
        <TaskList pollWhileRunning={true} />
        <BackupList />
      </main>
    </PageContainer>
  )
}
