'use client'

import useSWR from 'swr'
import { useLocale } from '@/components/LocaleProvider'
import { useAdminGuard } from '@/hooks/useAdminGuard'
import { BackButton } from '@/components/BackButton'
import { t } from '@/lib/i18n'
import { PageHeader } from '@/components/layout/PageHeader'
import { api } from '@/lib/api'
import { CreateForm } from '@/components/settings/egress-personas/CreateForm'
import { PersonaCard } from '@/components/settings/egress-personas/PersonaCard'
import { accountKey, type AccountsBySource } from '@/components/settings/egress-personas/shared'

export default function EgressPersonasPage() {
  useLocale()
  const authorized = useAdminGuard()

  const { data: personas, mutate } = useSWR(authorized ? 'admin-personas' : null, () =>
    api.adminPersonas.list(),
  )
  const { data: credentials } = useSWR(authorized ? 'settings-credentials' : null, () =>
    api.settings.getCredentials(),
  )

  const sources = Object.entries(credentials ?? {})
    .filter(([, status]) => status.configured)
    .map(([source]) => source)
  const sourcesKey = sources.join(',')

  // Stored accounts per source, fetched eagerly so every card can offer them.
  const { data: accountsBySource } = useSWR(
    authorized && sourcesKey ? ['persona-credential-accounts', sourcesKey] : null,
    async ([, joined]): Promise<AccountsBySource> => {
      const entries = await Promise.all(
        joined.split(',').map(async (source) => {
          const res = await api.settings.listCredentialAccounts(source)
          return [source, res.accounts] as const
        }),
      )
      return Object.fromEntries(entries)
    },
  )

  if (!authorized) return null

  // An account can back at most one persona (DB unique), so hide taken ones.
  const takenAccounts = new Set(
    (personas ?? []).flatMap((p) => p.accounts.map((a) => accountKey(a.source, a.account))),
  )
  const refresh = () => mutate()

  return (
    <div className="max-w-2xl">
      <BackButton fallback="/settings" />
      <PageHeader title={t('personas.title')} />

      <CreateForm onCreated={refresh} />

      {personas && personas.length === 0 && (
        <p className="text-sm text-vault-text-muted">{t('personas.empty')}</p>
      )}
      {(personas ?? []).map((persona) => (
        <PersonaCard
          key={persona.id}
          persona={persona}
          sources={sources}
          accountsBySource={accountsBySource}
          takenAccounts={takenAccounts}
          onChanged={refresh}
        />
      ))}
    </div>
  )
}
