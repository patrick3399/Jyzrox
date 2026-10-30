import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export type PageVariant = 'primary' | 'secondary'

/**
 * Page width frame. LayoutShell owns the page padding; this only bounds the width.
 * Primary (browse) pages stay unbounded: grid row heights are derived from the
 * container width (FE-T21), so it must match the shell content box exactly.
 */
export function PageContainer({
  variant = 'primary',
  className,
  children,
}: {
  variant?: PageVariant
  className?: string
  children: ReactNode
}) {
  return (
    <div data-page-variant={variant} className={cn(variant === 'secondary' && 'mx-auto w-full max-w-5xl', className) || undefined}>
      {children}
    </div>
  )
}
