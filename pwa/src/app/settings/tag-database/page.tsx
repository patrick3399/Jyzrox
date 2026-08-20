'use client'

import { useState } from 'react'
import { useLocale } from '@/components/LocaleProvider'
import { useAdminGuard } from '@/hooks/useAdminGuard'
import { BackButton } from '@/components/BackButton'
import { t } from '@/lib/i18n'
import { toast } from 'sonner'
import { api } from '@/lib/api'

export default function TagDatabaseSettingsPage() {
  useLocale()
  const authorized = useAdminGuard()

  const [isImporting, setIsImporting] = useState(false)

  const handleImportEhtag = async () => {
    setIsImporting(true)
    try {
      const result = await api.tags.importEhtag()
      toast.success(t('settings.importEhtagSuccess', { count: result.count }))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.importEhtagFailed'))
    } finally {
      setIsImporting(false)
    }
  }

  if (!authorized) return null

  return (
    <div className="max-w-2xl">
      <BackButton fallback="/settings" />
      <h1 className="text-2xl font-bold mb-6 text-vault-text">{t('settingsCategory.tagDatabase')}</h1>

      <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
        <div className="px-5 pb-5">
          <p className="text-xs text-vault-text-muted mt-4 mb-4">{t('settings.tagDatabaseDesc')}</p>
          <div>
            <button
              onClick={handleImportEhtag}
              disabled={isImporting}
              className="px-4 py-2 bg-blue-900/30 border border-blue-700/50 text-blue-400 hover:bg-blue-900/50 rounded text-sm font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isImporting ? t('settings.importingEhtag') : t('settings.importEhtag')}
            </button>
            <p className="text-[10px] text-vault-text-muted mt-1">{t('settings.importEhtagDesc')}</p>
          </div>
        </div>
      </div>
    </div>
  )
}
