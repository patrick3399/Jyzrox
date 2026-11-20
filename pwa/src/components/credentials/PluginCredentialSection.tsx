'use client'

import { useState, useEffect, useCallback } from 'react'
import { ChevronUp, ChevronDown, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { CredentialAccounts } from '@/components/CredentialAccounts'
import type { EhAccount, PluginInfo, CredentialFlow } from '@/lib/types'
import { Button } from '@/components/ui/button'
import { StatusBadge } from '@/components/credentials/shared'
import { EhExtras, EhFieldsFlow } from '@/components/credentials/EhFlows'
import {
  PixivOAuthFlow,
  PixivTokenFlow,
  PixivCookieFlow,
} from '@/components/credentials/PixivFlows'
import { GenericFieldsFlow } from '@/components/credentials/GenericFlows'

// ── FlowLabel: human-readable flow type label ────────────────────────────

function flowLabel(flow: CredentialFlow): string {
  if (flow.flow_type === 'oauth') return t('credentials.flowOAuth')
  if (flow.flow_type === 'login') return t('credentials.flowLogin')
  return t('credentials.flowFields')
}

// ── PluginCredentialSection ───────────────────────────────────────────────

export function PluginCredentialSection({
  plugin,
  isOpen,
  onToggle,
  configured,
  onDeleted,
  accountCount,
  accountsRefreshKey,
}: {
  plugin: PluginInfo
  isOpen: boolean
  onToggle: () => void
  configured: boolean
  onDeleted: () => void
  accountCount: number
  accountsRefreshKey: number
}) {
  const flows = plugin.credential_flows ?? []
  const [activeFlow, setActiveFlow] = useState(0)
  const [pixivUsername, setPixivUsername] = useState<string | null>(null)
  const [ehAccount, setEhAccount] = useState<EhAccount | null>(null)
  const [ehAccountLoading, setEhAccountLoading] = useState(false)
  const [useEx, setUseEx] = useState(false)
  const [useExLoading, setUseExLoading] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [newAccount, setNewAccount] = useState('')
  // The input is only rendered once a credential exists; never apply a name the
  // user cannot see.
  const saveAs = configured ? newAccount || undefined : undefined

  const afterSave = useCallback(() => {
    setNewAccount('')
    onDeleted()
  }, [onDeleted])

  const isEh = plugin.source_id === 'ehentai'
  const isPixiv = plugin.source_id === 'pixiv'

  useEffect(() => {
    if (isEh && isOpen) {
      api.settings
        .getEhSite()
        .then((res) => setUseEx(res.use_ex))
        .catch(() => {})
    }
  }, [isEh, isOpen])

  const handleToggleEx = useCallback(async () => {
    setUseExLoading(true)
    try {
      const res = await api.settings.setEhSite(!useEx)
      setUseEx(res.use_ex)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('common.failedToLoad'))
    } finally {
      setUseExLoading(false)
    }
  }, [useEx])

  const handleEhRefresh = useCallback(async () => {
    setEhAccountLoading(true)
    try {
      const account = await api.settings.getEhAccount()
      setEhAccount(account)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.ehRefreshFailed'))
    } finally {
      setEhAccountLoading(false)
    }
  }, [])

  const handleDelete = useCallback(async () => {
    if (!confirm(t('credentials.deleteConfirm', { source: plugin.name }))) return
    setDeleting(true)
    try {
      await api.settings.deleteCredential(plugin.source_id)
      toast.success(t('credentials.deleted', { source: plugin.name }))
      onDeleted()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('credentials.clearFailed'))
    } finally {
      setDeleting(false)
    }
  }, [plugin, onDeleted])

  const currentFlow = flows[activeFlow] ?? null

  // Plugins whose flow needs more than field entry (account probing, OAuth
  // exchange, cookie->token conversion) supply a bespoke component here.
  let specialFlow: React.ReactNode = null
  if (currentFlow && isEh && currentFlow.flow_type === 'fields') {
    specialFlow = (
      <EhFieldsFlow
        saveAs={saveAs}
        onSaved={(account) => {
          // A named account is not made active by the backend, so the
          // "current account" panel must keep showing the active one.
          if (!saveAs) setEhAccount(account)
          afterSave() // re-check configured status via parent refresh
        }}
      />
    )
  } else if (currentFlow && isPixiv) {
    const onPixivSaved = (username: string) => {
      if (!saveAs) setPixivUsername(username)
      afterSave()
    }
    if (currentFlow.flow_type === 'oauth')
      specialFlow = <PixivOAuthFlow saveAs={saveAs} onSaved={onPixivSaved} />
    else if (currentFlow.flow_type === 'fields')
      specialFlow = <PixivTokenFlow saveAs={saveAs} onSaved={onPixivSaved} />
    else if (currentFlow.flow_type === 'login')
      specialFlow = <PixivCookieFlow saveAs={saveAs} onSaved={onPixivSaved} />
  }

  // A non-fields flow with no bespoke component has no UI to offer.
  if (!specialFlow && currentFlow && currentFlow.fields.length === 0) {
    specialFlow = (
      <p className="text-xs text-vault-text-muted">{t('credentials.flowUnavailable')}</p>
    )
  }

  return (
    <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between">
        <button
          onClick={onToggle}
          className="flex-1 flex items-center justify-between px-5 py-4 text-left hover:bg-vault-card-hover transition-colors"
        >
          <span className="font-medium text-vault-text text-sm">{plugin.name}</span>
          {isOpen ? (
            <ChevronUp size={16} className="text-vault-text-muted" />
          ) : (
            <ChevronDown size={16} className="text-vault-text-muted" />
          )}
        </button>
        <div className="pr-5 shrink-0">
          <StatusBadge configured={configured} />
        </div>
      </div>

      {/* Body */}
      {isOpen && (
        <div className="px-5 pb-5 border-t border-vault-border">
          {/* EH extras: site toggle + account refresh */}
          {isEh && (
            <EhExtras
              ehAccount={ehAccount}
              ehAccountLoading={ehAccountLoading}
              onRefresh={handleEhRefresh}
              useEx={useEx}
              useExLoading={useExLoading}
              onToggleEx={handleToggleEx}
            />
          )}

          {configured && (
            <CredentialAccounts
              source={plugin.source_id}
              refreshKey={accountsRefreshKey}
              onChanged={onDeleted}
              newAccount={newAccount}
              onNewAccountChange={setNewAccount}
            />
          )}

          {/* Flow tabs (only if multiple flows) */}
          {flows.length > 1 && (
            <div className="flex mt-4 bg-vault-input border border-vault-border rounded overflow-hidden">
              {flows.map((flow, idx) => (
                <button
                  key={idx}
                  onClick={() => setActiveFlow(idx)}
                  className={`flex-1 px-3 py-2 text-sm transition-colors ${activeFlow === idx ? 'bg-vault-accent text-white' : 'text-vault-text-muted hover:text-vault-text'}`}
                >
                  {flowLabel(flow)}
                </button>
              ))}
            </div>
          )}

          {/* Flow content — specialised components are opt-in overrides; every
              other plugin renders from the `fields` its flow declares. */}
          {currentFlow && (
            <div className="mt-4">
              {specialFlow ?? (
                <GenericFieldsFlow
                  plugin={plugin}
                  flow={currentFlow}
                  onSaved={afterSave}
                  saveAs={saveAs}
                />
              )}
            </div>
          )}

          {/* Pixiv username display */}
          {isPixiv && pixivUsername && (
            <div className="mt-4 flex items-center gap-2 text-sm p-3 bg-vault-input border border-vault-border rounded-lg">
              <span className="text-vault-text-muted">{t('settings.pixivAccount')}:</span>
              <span className="text-vault-text-secondary">{pixivUsername}</span>
            </div>
          )}

          {/* Delete button */}
          {configured && accountCount <= 1 && (
            <Button
              variant="ghost"
              size="sm"
              className="mt-4 border border-red-500/30 bg-red-600/20 text-red-400 hover:bg-red-600/30"
              onClick={handleDelete}
              disabled={deleting}
            >
              <Trash2 size={13} />
              {deleting
                ? t('credentials.saving')
                : isEh
                  ? t('settings.clearCookie')
                  : isPixiv
                    ? t('settings.clearToken')
                    : t('credentials.clearCredential')}
            </Button>
          )}
        </div>
      )}
    </div>
  )
}
