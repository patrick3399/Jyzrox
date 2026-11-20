import { t } from '@/lib/i18n'
import type { CredentialAccount, EgressPersona } from '@/lib/types'

export const BTN = 'text-xs bg-vault-accent/20 text-vault-accent hover:bg-vault-accent/30'
export const DANGER_BTN = 'text-xs bg-red-500/20 text-red-400 hover:bg-red-500/30'
export const INPUT =
  'w-full bg-vault-bg border border-vault-border rounded px-3 py-2 text-sm text-vault-text disabled:opacity-50 disabled:cursor-not-allowed'
export const LABEL = 'text-xs text-vault-text-secondary block mb-1'

export type AccountsBySource = Record<string, CredentialAccount[]>

export function toProfile(value: string): EgressPersona['browser_profile'] {
  return value === 'chrome' || value === 'firefox' ? value : null
}

export function accountKey(source: string, account: string): string {
  return `${source}\u0000${account}`
}

export function BrowserOptions() {
  return (
    <>
      <option value="">{t('personas.browserNone')}</option>
      <option value="chrome">Chrome</option>
      <option value="firefox">Firefox</option>
    </>
  )
}

// ── Create form ───────────────────────────────────────────────────────
