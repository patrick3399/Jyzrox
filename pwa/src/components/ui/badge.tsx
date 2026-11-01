import type { HTMLAttributes } from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/cn'

export const badgeVariants = cva('inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium', {
  variants: {
    tone: {
      neutral: 'border-vault-border bg-vault-input text-vault-text-secondary',
      accent: 'border-vault-accent/40 bg-vault-accent/10 text-vault-accent',
      success: 'border-vault-success/40 bg-vault-success/10 text-vault-success',
      warning: 'border-vault-warning/40 bg-vault-warning/10 text-vault-warning',
      danger: 'border-vault-danger/40 bg-vault-danger/10 text-vault-danger',
    },
  },
  defaultVariants: { tone: 'neutral' },
})

export function Badge({ tone, className, ...props }: HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />
}
