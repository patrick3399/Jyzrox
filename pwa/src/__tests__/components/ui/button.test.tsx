import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { Button, buttonVariants } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'

describe('Button', () => {
  it('defaults to type="button" so it never submits a surrounding form', () => {
    render(<form onSubmit={vi.fn()}><Button>Go</Button></form>)
    expect(screen.getByRole('button', { name: 'Go' }).getAttribute('type')).toBe('button')
  })

  it('applies variant and size classes', () => {
    render(<Button variant="danger" size="sm">Del</Button>)
    const cls = screen.getByRole('button').className
    expect(cls).toContain('bg-vault-danger')
    expect(cls).toContain('h-8')
  })

  it('lets a caller className override a variant class', () => {
    expect(buttonVariants({ variant: 'primary' })).toContain('rounded-lg')
    render(<Button variant="primary" className="rounded-full">R</Button>)
    const cls = screen.getByRole('button').className
    expect(cls).toContain('rounded-full')
    expect(cls).not.toContain('rounded-lg')
  })

  it('icon size is a 40px square', () => {
    expect(buttonVariants({ size: 'icon' })).toContain('size-10')
  })

  it('icon-sm size is a 32px square for dense rows', () => {
    const cls = buttonVariants({ size: 'icon-sm' })
    expect(cls).toContain('size-8')
    expect(cls).not.toContain('size-10')
  })
})

describe('Badge', () => {
  it('maps tone to semantic tokens', () => {
    render(<Badge tone="success">ok</Badge>)
    expect(screen.getByText('ok').className).toContain('text-vault-success')
  })
})
