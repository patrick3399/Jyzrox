import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

interface PageHeaderProps {
  title: ReactNode
  /** Inline next to the title, e.g. a count. */
  meta?: ReactNode
  subtitle?: ReactNode
  icon?: ReactNode
  actions?: ReactNode
  /** Tight spacing for pages whose toolbar sits right under the title (Library). */
  dense?: boolean
  className?: string
}

export function PageHeader({ title, meta, subtitle, icon, actions, dense = false, className }: PageHeaderProps) {
  return (
    <header className={cn('flex items-start justify-between gap-3', dense ? 'mb-2' : 'mb-4 sm:mb-6', className)}>
      <div className="min-w-0">
        <div className="flex min-w-0 items-center gap-2">
          {icon}
          <h1 className="truncate text-xl font-bold text-vault-text sm:text-2xl">{title}</h1>
          {meta && <span className="whitespace-nowrap text-sm text-vault-text-muted">{meta}</span>}
        </div>
        {subtitle && <p className="mt-1 text-sm text-vault-text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </header>
  )
}
