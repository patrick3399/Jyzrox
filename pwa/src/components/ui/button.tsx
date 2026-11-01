import type { ButtonHTMLAttributes, Ref } from 'react'
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/cn'

export const buttonVariants = cva(
  'inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-lg text-sm font-medium transition-colors duration-(--motion-fast) ease-vault-out focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-vault-accent disabled:pointer-events-none disabled:opacity-50 [&_svg]:shrink-0',
  {
    variants: {
      variant: {
        primary: 'bg-vault-accent text-vault-accent-fg hover:bg-vault-accent-hover',
        secondary: 'border border-vault-border bg-vault-input text-vault-text-secondary hover:border-vault-border-hover hover:text-vault-text',
        ghost: 'text-vault-text-muted hover:bg-vault-card-hover hover:text-vault-text',
        danger: 'bg-vault-danger text-white hover:bg-vault-danger-hover',
      },
      size: {
        sm: 'h-8 px-3',
        md: 'h-10 px-4',
        icon: 'size-10 p-0',
        'icon-sm': 'size-8 p-0',
      },
    },
    defaultVariants: { variant: 'secondary', size: 'md' },
  },
)

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof buttonVariants> & { ref?: Ref<HTMLButtonElement> }

export function Button({ variant, size, className, type = 'button', ref, ...props }: ButtonProps) {
  return <button ref={ref} type={type} className={cn(buttonVariants({ variant, size }), className)} {...props} />
}
