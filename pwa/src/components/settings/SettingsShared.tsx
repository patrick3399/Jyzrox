'use client'

import { ChevronUp, ChevronDown } from 'lucide-react'
import { t } from '@/lib/i18n'

// ── Collapsible Section Header ──

export function SectionHeader({
  title,
  isOpen,
  onToggle,
}: {
  title: string
  isOpen: boolean
  onToggle: () => void
}) {
  return (
    <button
      onClick={onToggle}
      className="w-full flex items-center justify-between px-5 py-4 text-left hover:bg-vault-card-hover transition-colors"
    >
      <span className="font-medium text-vault-text text-sm">{title}</span>
      {isOpen ? (
        <ChevronUp size={16} className="text-vault-text-muted" />
      ) : (
        <ChevronDown size={16} className="text-vault-text-muted" />
      )}
    </button>
  )
}

// ── Toggle Row ──

export function ToggleRow({
  label,
  description,
  checked,
  onChange,
  disabled,
}: {
  label: string
  description: string
  checked: boolean
  onChange: (checked: boolean) => void
  disabled?: boolean
}) {
  return (
    <div className="flex items-center justify-between py-3">
      <div className="flex-1 min-w-0 pr-4">
        <p className="text-sm font-medium text-vault-text">{label}</p>
        <p className="text-xs text-vault-text-muted mt-0.5">{description}</p>
      </div>
      <button
        onClick={() => onChange(!checked)}
        disabled={disabled}
        className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none ${
          checked ? 'bg-green-600' : 'bg-vault-border'
        } ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
      >
        <span
          className={`pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200 ${
            checked ? 'translate-x-4' : 'translate-x-0'
          }`}
        />
      </button>
    </div>
  )
}

// ── Status Indicator ──

export function StatusIndicator({ configured }: { configured: boolean }) {
  return (
    <span
      className={`inline-flex items-center gap-1 text-xs ${configured ? 'text-green-500' : 'text-vault-text-muted'}`}
    >
      <span
        className={`w-1.5 h-1.5 rounded-full ${configured ? 'bg-green-500' : 'bg-vault-text-muted'}`}
      />
      {configured ? t('settings.configured') : t('settings.notConfigured')}
    </span>
  )
}

// ── CSS Class Constants ──

export const inputClass =
  'w-full bg-vault-input border border-vault-border rounded px-3 py-2 text-vault-text placeholder-vault-text-muted focus:outline-none focus:border-vault-accent text-sm'

export const btnPrimary =
  'px-4 py-2 bg-vault-accent hover:bg-vault-accent/90 disabled:opacity-40 disabled:cursor-not-allowed rounded text-white text-sm font-medium transition-colors'

export const btnSecondary =
  'px-4 py-2 bg-vault-input border border-vault-border hover:border-vault-border-hover rounded text-vault-text-secondary text-sm transition-colors'
