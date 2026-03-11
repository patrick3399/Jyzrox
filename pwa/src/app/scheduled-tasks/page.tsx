import { t } from '@/lib/i18n'
import { TaskList } from '@/components/ScheduledTasks/TaskList'

export default function ScheduledTasksPage() {
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
