import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

interface PageHeaderProps {
  title: ReactNode
  /** Inline next to the title, e.g. a count. */
  meta?: ReactNode
  subtitle?: ReactNode
  icon?: ReactNode
  actions?: ReactNode
  /**
   * Bottom margin: 'default' = mb-4 sm:mb-6; 'dense' = mb-2 (toolbar right under the title, e.g. Library);
   * 'none' = no margin (parent supplies spacing, e.g. space-y-*).
   */
  spacing?: 'default' | 'dense' | 'none'
  className?: string
}

export function PageHeader({ title, meta, subtitle, icon, actions, spacing = 'default', className }: PageHeaderProps) {
  return (
    <header
      className={cn(
        'flex flex-wrap items-start justify-between gap-x-3 gap-y-2',
        spacing === 'dense' && 'mb-2',
        spacing === 'default' && 'mb-4 sm:mb-6',
        className,
      )}
    >
      <div className="min-w-0 max-w-full">
        <div className="flex min-w-0 items-center gap-2">
          {icon}
          <h1 className="truncate text-xl font-bold text-vault-text sm:text-2xl">{title}</h1>
          {meta && <span className="whitespace-nowrap text-sm text-vault-text-muted">{meta}</span>}
        </div>
        {subtitle && <p className="mt-1 text-sm text-vault-text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </header>
  )
}
