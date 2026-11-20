'use client'

export function Toggle({
  enabled,
  disabled,
  ariaLabel,
  onToggle,
}: {
  enabled: boolean
  disabled?: boolean
  ariaLabel: string
  onToggle: () => void
}) {
  return (
    <button
      onClick={onToggle}
      disabled={disabled}
      aria-label={ariaLabel}
      aria-pressed={enabled}
      className={`relative shrink-0 inline-flex h-5 w-9 rounded-full border-2 border-transparent transition-colors ${
        enabled ? 'bg-green-600' : 'bg-vault-border'
      } ${disabled ? 'opacity-40 cursor-not-allowed' : ''}`}
    >
      <span
        className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition ${
          enabled ? 'translate-x-4' : 'translate-x-0'
        }`}
      />
    </button>
  )
}

export function StatBadge({
  label,
  count,
  accent,
}: {
  label: string
  count: number
  accent?: boolean
}) {
  return (
    <div
      className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs ${
        accent
          ? 'bg-blue-500/10 border border-blue-500/20 text-blue-400'
          : 'bg-vault-border/40 border border-vault-border text-vault-text-muted'
      }`}
    >
      <span>{label}</span>
      <span className="font-mono font-semibold">{count}</span>
    </div>
  )
}

export function ActionButton({
  icon,
  label,
  onClick,
  variant = 'default',
}: {
  icon: string
  label: string
  onClick: () => void
  variant?: 'default' | 'danger' | 'warning' | 'success'
}) {
  const variantClass = {
    default:
      'bg-vault-border/40 border border-vault-border text-vault-text-muted hover:bg-vault-border/70 hover:text-vault-text',
    danger: 'bg-red-500/10 border border-red-500/20 text-red-400 hover:bg-red-500/20',
    warning: 'bg-amber-500/10 border border-amber-500/20 text-amber-400 hover:bg-amber-500/20',
    success: 'bg-green-500/10 border border-green-500/20 text-green-400 hover:bg-green-500/20',
  }[variant]

  return (
    <button
      onClick={onClick}
      className={`flex flex-col items-center justify-center gap-0.5 w-14 py-2 rounded-lg text-[10px] font-medium transition-colors ${variantClass}`}
    >
      <span className="text-base leading-none">{icon}</span>
      <span>{label}</span>
    </button>
  )
}
