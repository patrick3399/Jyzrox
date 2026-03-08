import { type LucideIcon } from 'lucide-react'
import Link from 'next/link'

interface EmptyStateProps {
  icon?: LucideIcon
  title: string
  description?: string
  action?: { label: string; href: string }
}

export function EmptyState({ icon: Icon, title, description, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      {Icon && (
        <div className="w-12 h-12 rounded-full bg-vault-card border border-vault-border flex items-center justify-center mb-4">
          <Icon size={24} className="text-vault-text-muted" />
        </div>
      )}
      <p className="text-sm text-vault-text-secondary font-medium">{title}</p>
      {description && <p className="text-xs text-vault-text-muted mt-1 max-w-xs">{description}</p>}
      {action && (
        <Link
          href={action.href}
          className="mt-4 px-4 py-2 bg-vault-accent text-white text-sm font-medium rounded-lg hover:bg-vault-accent/90 transition-colors"
        >
          {action.label}
        </Link>
      )}
    </div>
  )
}
