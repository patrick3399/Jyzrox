'use client'

import { useCallback, useEffect, useState } from 'react'
import { Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import type { CredentialAccount } from '@/lib/types'

const inputClass =
  'w-full bg-vault-input border border-vault-border rounded px-3 py-2 text-vault-text placeholder-vault-text-muted focus:outline-none focus:border-vault-accent text-sm'

/**
 * Keep only what the backend accepts for an account name (ACCOUNT_PATTERN in
 * backend/services/credential.py). A typed name can then never be rejected at
 * save time — and an empty name means "update the active account", so a
 * rejected name must not silently turn into one.
 */
export function sanitizeAccountName(raw: string): string {
  return raw
    .replace(/[^A-Za-z0-9._@-]/g, '')
    .replace(/^[._@-]+/, '')
    .slice(0, 40)
}

interface CredentialAccountsProps {
  source: string
  /** Changes whenever the parent saved a credential, so the list reloads. */
  refreshKey: number
  /** Called after the active account or the set of accounts changed. */
  onChanged: () => void
  /** Name for the parent's next save. Omit both to hide the input. */
  newAccount?: string
  onNewAccountChange?: (value: string) => void
}

export function CredentialAccounts({
  source,
  refreshKey,
  onChanged,
  newAccount,
  onNewAccountChange,
}: CredentialAccountsProps) {
  const [accounts, setAccounts] = useState<CredentialAccount[]>([])
  const [busy, setBusy] = useState(false)
  const [reload, setReload] = useState(0)

  useEffect(() => {
    let cancelled = false
    api.settings
      .listCredentialAccounts(source)
      .then((res) => {
        if (!cancelled) setAccounts(res.accounts)
      })
      .catch(() => {
        if (!cancelled) setAccounts([])
      })
    return () => {
      cancelled = true
    }
  }, [source, refreshKey, reload])

  const handleActivate = useCallback(
    async (account: string) => {
      setBusy(true)
      try {
        await api.settings.activateCredentialAccount(source, account)
        toast.success(t('credentials.accountActivated', { account }))
        setReload((n) => n + 1)
        onChanged()
      } catch (err) {
        toast.error(err instanceof Error ? err.message : t('credentials.accountActionFailed'))
      } finally {
        setBusy(false)
      }
    },
    [source, onChanged],
  )

  const handleDelete = useCallback(
    async (account: string) => {
      if (!confirm(t('credentials.deleteAccountConfirm', { account }))) return
      setBusy(true)
      try {
        await api.settings.deleteCredentialAccount(source, account)
        toast.success(t('credentials.accountDeleted', { account }))
        setReload((n) => n + 1)
        onChanged()
      } catch (err) {
        toast.error(err instanceof Error ? err.message : t('credentials.accountActionFailed'))
      } finally {
        setBusy(false)
      }
    },
    [source, onChanged],
  )

  const showInput = onNewAccountChange !== undefined
  if (accounts.length === 0 && !showInput) return null

  const inputId = `credential-new-account-${source}`

  return (
    <div className="mt-4">
      <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">
        {t('credentials.accounts')}
      </p>
      {accounts.length > 0 && (
        <ul className="space-y-1.5">
          {accounts.map((entry) => (
            <li
              key={entry.account}
              className="flex items-center justify-between gap-2 bg-vault-input border border-vault-border rounded-lg px-3 py-2"
            >
              <span className="text-sm text-vault-text font-medium truncate">{entry.account}</span>
              {entry.is_active ? (
                <span className="text-xs text-green-500 shrink-0">
                  {t('credentials.accountActive')}
                </span>
              ) : (
                <div className="flex items-center gap-2 shrink-0">
                  <button
                    onClick={() => handleActivate(entry.account)}
                    disabled={busy}
                    className="text-xs text-vault-accent hover:underline disabled:opacity-40"
                  >
                    {t('credentials.setActive')}
                  </button>
                  <button
                    onClick={() => handleDelete(entry.account)}
                    disabled={busy}
                    aria-label={t('credentials.deleteAccount', { account: entry.account })}
                    className="text-red-400/70 hover:text-red-400 transition-colors px-1 py-1 disabled:opacity-40"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
      {showInput && (
        <div className="mt-3">
          <label htmlFor={inputId} className="block text-xs text-vault-text-muted mb-1">
            {t('credentials.newAccountName')}
          </label>
          <input
            id={inputId}
            type="text"
            value={newAccount ?? ''}
            onChange={(e) => onNewAccountChange?.(sanitizeAccountName(e.target.value))}
            placeholder={t('credentials.newAccountPlaceholder')}
            autoComplete="off"
            className={inputClass}
          />
          <p className="text-xs text-vault-text-muted mt-1">{t('credentials.newAccountHint')}</p>
        </div>
      )}
    </div>
  )
}
