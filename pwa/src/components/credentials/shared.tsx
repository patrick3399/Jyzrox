import { t } from '@/lib/i18n'

// ── Shared style constants ─────────────────────────────────────────────────

export const inputClass =
  'w-full bg-vault-input border border-vault-border rounded px-3 py-2 text-vault-text placeholder-vault-text-muted focus:outline-none focus:border-vault-accent text-sm'

// ── StatusBadge ────────────────────────────────────────────────────────────

export function StatusBadge({ configured }: { configured: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1 text-xs ${configured ? 'text-green-500' : 'text-vault-text-muted'}`}
    >
      <span
        className={`w-1.5 h-1.5 rounded-full ${configured ? 'bg-green-500' : 'bg-vault-text-muted'}`}
      />
      {configured ? t('credentials.configured') : t('credentials.notConfigured')}
    </span>
  )
}
