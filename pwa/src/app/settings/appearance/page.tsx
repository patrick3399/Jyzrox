'use client'

import { useLocale } from '@/components/LocaleProvider'
import { BackButton } from '@/components/BackButton'
import { t } from '@/lib/i18n'
import { BottomTabConfig } from '@/components/BottomTabConfig'
import { SidebarConfig } from '@/components/SidebarConfig'
import { DashboardLinksConfig } from '@/components/DashboardLinksConfig'
import { useProfile } from '@/hooks/useProfile'

export default function AppearanceSettingsPage() {
  useLocale()
  const { data: profile } = useProfile()

  return (
    <div className="max-w-2xl">
      <BackButton fallback="/settings" />
      <h1 className="text-2xl font-bold mb-6 text-vault-text">
        {t('settingsCategory.appearance')}
      </h1>

      <div className="space-y-3">
        {/* Bottom Tab */}
        <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
          <div className="px-5 py-4">
            <BottomTabConfig />
          </div>
        </div>

        {/* Sidebar Order */}
        <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
          <div className="px-5 py-4">
            <SidebarConfig userRole={profile?.role} />
          </div>
        </div>

        {/* Dashboard Links */}
        <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
          <div className="px-5 py-4">
            <DashboardLinksConfig />
          </div>
        </div>
      </div>
    </div>
  )
}
