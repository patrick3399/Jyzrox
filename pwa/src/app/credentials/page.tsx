'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { Key } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { useProfile } from '@/hooks/useProfile'
import type { Credentials, PluginInfo } from '@/lib/types'
import { PageContainer } from '@/components/layout/PageContainer'
import { PageHeader } from '@/components/layout/PageHeader'
import { PluginCredentialSection } from '@/components/credentials/PluginCredentialSection'
import { SiteCredentialSection } from '@/components/credentials/SiteCredentialSection'
import { SauceNaoSection } from '@/components/credentials/SauceNaoSection'

export default function CredentialsPage() {
  useLocale()
  const router = useRouter()
  const { data: profile, isLoading: profileLoading } = useProfile()

  const isAdmin = profile?.role === 'admin'

  useEffect(() => {
    if (!profileLoading && profile && !isAdmin) {
      router.replace('/forbidden')
    }
  }, [profileLoading, profile, isAdmin, router])

  const [plugins, setPlugins] = useState<PluginInfo[]>([])
  const [pluginsLoading, setPluginsLoading] = useState(true)
  const [credentials, setCredentials] = useState<Credentials | null>(null)
  const [credLoading, setCredLoading] = useState(true)
  // Shared by every account list so a source shown in two sections stays in sync.
  const [accountsRefresh, setAccountsRefresh] = useState(0)

  // Track which plugin section is expanded (by source_id)
  const [openSection, setOpenSection] = useState<string | null>('ehentai')

  useEffect(() => {
    api.plugins
      .list()
      .then((res) => {
        // Only show plugins that have credential flows defined
        const withFlows = res.plugins.filter(
          (p) => Array.isArray(p.credential_flows) && p.credential_flows.length > 0,
        )
        setPlugins(withFlows)
      })
      .catch((err) => toast.error(err instanceof Error ? err.message : t('common.failedToLoad')))
      .finally(() => setPluginsLoading(false))

    api.settings
      .getCredentials()
      .then(setCredentials)
      .catch((err) => toast.error(err instanceof Error ? err.message : t('common.failedToLoad')))
      .finally(() => setCredLoading(false))
  }, [])

  // Refresh credentials after a save/delete action
  const refreshCredentials = useCallback(() => {
    setAccountsRefresh((n) => n + 1)
    api.settings
      .getCredentials()
      .then(setCredentials)
      .catch(() => {})
  }, [])

  const toggleSection = useCallback((sourceId: string) => {
    setOpenSection((prev) => (prev === sourceId ? null : sourceId))
  }, [])

  if (profileLoading || !profile || !isAdmin) {
    return (
      <PageContainer variant="secondary">
        <div className="flex items-center justify-center min-h-[60vh]">
          <div className="text-vault-text-secondary text-sm">{t('common.loading')}</div>
        </div>
      </PageContainer>
    )
  }

  // Exclude gallery_dl from the plugin list (rendered as generic cookie section)
  const pluginSections = plugins.filter((p) => p.source_id !== 'gallery_dl')

  return (
    <PageContainer variant="secondary">
      <PageHeader
        title={t('credentials.title')}
        icon={<Key size={22} className="text-vault-accent" />}
      />

      {pluginsLoading ? (
        <div className="text-sm text-vault-text-muted">{t('common.loading')}</div>
      ) : (
        <div className="space-y-3">
          {/* Plugin-driven sections */}
          {pluginSections.map((plugin) => (
            <PluginCredentialSection
              key={plugin.source_id}
              plugin={plugin}
              isOpen={openSection === plugin.source_id}
              onToggle={() => toggleSection(plugin.source_id)}
              configured={credentials?.[plugin.source_id]?.configured ?? false}
              onDeleted={refreshCredentials}
              accountCount={credentials?.[plugin.source_id]?.accounts ?? 1}
              accountsRefreshKey={accountsRefresh}
            />
          ))}

          {/* SauceNAO API key */}
          <SauceNaoSection
            configured={credentials?.['saucenao']?.configured ?? false}
            isOpen={openSection === 'saucenao'}
            onToggle={() => toggleSection('saucenao')}
            onSaved={refreshCredentials}
          />

          {/* Generic cookie section (gallery-dl sites + others) */}
          <SiteCredentialSection
            credentials={credentials}
            credLoading={credLoading}
            onCredentialsChange={setCredentials}
            onRefresh={refreshCredentials}
            accountsRefreshKey={accountsRefresh}
          />
        </div>
      )}
    </PageContainer>
  )
}
