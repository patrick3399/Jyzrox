'use client'

import { useLocale } from '@/components/LocaleProvider'
import { useAdminGuard } from '@/hooks/useAdminGuard'
import { BackButton } from '@/components/BackButton'
import { t } from '@/lib/i18n'
import { toast } from 'sonner'
import { ScanLine } from 'lucide-react'
import { useRescanLibrary, useRescanStatus, useCancelRescan } from '@/hooks/useImport'
import { TaskList } from '@/components/ScheduledTasks/TaskList'

export default function ScheduledSettingsPage() {
  useLocale()
  const authorized = useAdminGuard()

  const { trigger: rescan, isMutating: rescanning } = useRescanLibrary()
  const { data: rescanStatus } = useRescanStatus()
  const { trigger: cancelRescan, isMutating: cancelling } = useCancelRescan()

  const handleRescan = async () => {
    try {
      await rescan()
      toast.success(t('settings.media.rescan'))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToLoad'))
    }
  }

  const isRunning = rescanStatus?.running ?? false
  const processed = rescanStatus?.processed
  const total = rescanStatus?.total

  if (!authorized) return null

  return (
    <div className="max-w-2xl">
      <BackButton fallback="/settings" />
      <h1 className="text-2xl font-bold mb-6 text-vault-text">{t('settingsCategory.scheduled')}</h1>

      <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
        <div className="px-5 pb-5">
          <p className="text-xs text-vault-text-muted mt-4 mb-4">{t('settings.tasks.desc')}</p>

          {/* Rescan Library button + progress */}
          <div className="mb-5 pb-4 border-b border-vault-border">
            <div className="flex items-center justify-between mb-2">
              <div>
                <p className="text-sm text-vault-text">{t('settings.media.rescan')}</p>
                <p className="text-xs text-vault-text-muted mt-0.5">
                  {t('settings.media.rescan.desc')}
                </p>
              </div>
              {isRunning ? (
                <button
                  onClick={async () => {
                    try {
                      await cancelRescan()
                      toast.success(t('settings.media.rescan.cancelled'))
                    } catch {
                      toast.error(t('common.failedToLoad'))
                    }
                  }}
                  disabled={cancelling}
                  className="px-3 py-1.5 rounded text-xs font-medium bg-red-500/20 text-red-400 hover:bg-red-500/30 transition-colors"
                >
                  {cancelling
                    ? t('settings.media.rescan.cancelling')
                    : t('settings.media.rescan.cancel')}
                </button>
              ) : (
                <button
                  onClick={handleRescan}
                  disabled={rescanning}
                  className="px-3 py-1.5 rounded text-xs font-medium bg-vault-accent/20 text-vault-accent hover:bg-vault-accent/30 transition-colors flex items-center gap-1.5"
                >
                  <ScanLine size={14} />
                  {t('settings.media.rescan')}
                </button>
              )}
            </div>
            {isRunning && processed != null && total != null && (
              <div className="space-y-1">
                <div className="w-full bg-vault-input rounded-full h-1.5">
                  <div
                    className="bg-vault-accent rounded-full h-1.5 transition-all"
                    style={{ width: `${total > 0 ? (processed / total) * 100 : 0}%` }}
                  />
                </div>
                <p className="text-xs text-vault-text-muted">
                  {t('settings.media.rescan.running', {
                    processed: String(processed),
                    total: String(total),
                  })}
                </p>
              </div>
            )}
          </div>

          {/* Scheduled Tasks list */}
          <TaskList pollWhileRunning={false} />
        </div>
      </div>
    </div>
  )
}
