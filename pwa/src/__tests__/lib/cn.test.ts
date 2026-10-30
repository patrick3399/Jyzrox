import { describe, expect, it } from 'vitest'
import { cn } from '@/lib/cn'

describe('cn', () => {
  it('lets a later padding override an earlier one', () => {
    expect(cn('px-4 py-2', 'px-2')).toBe('py-2 px-2')
  })

  it('keeps a vault text colour next to a text size (different groups)', () => {
    expect(cn('text-sm', 'text-vault-text-muted')).toBe('text-sm text-vault-text-muted')
  })

  it('lets a later vault background override an earlier one', () => {
    expect(cn('bg-vault-card', 'bg-vault-accent')).toBe('bg-vault-accent')
  })

  it('drops falsy entries', () => {
    expect(cn('a', false, undefined, null, 'b')).toBe('a b')
  })
})
