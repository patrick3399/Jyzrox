import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('@/lib/i18n', () => ({
  t: (key: string, vars?: Record<string, string | number>) =>
    vars ? `${key} ${Object.values(vars).join(' ')}` : key,
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const h = vi.hoisted(() => ({ status: { head: 'abc', ahead: 2, behind: 0, clean: true, locked: false }, role: 'viewer' as string }))

vi.mock('swr', () => ({
  default: () => ({ data: h.status, mutate: vi.fn() }),
}))
vi.mock('@/hooks/useProfile', () => ({ useProfile: () => ({ data: { role: h.role } }) }))
vi.mock('@/lib/api', () => ({ api: { novels: { status: vi.fn(), sync: vi.fn(), reset: vi.fn() } } }))

import { RepoStatusBar } from '@/components/novels/RepoStatusBar'

describe('RepoStatusBar', () => {
  beforeEach(() => {
    h.status = { head: 'abc', ahead: 2, behind: 0, clean: true, locked: false }
    h.role = 'viewer'
  })

  it('shows unpushed count and hides reset for non-admins', () => {
    render(<RepoStatusBar />)
    expect(screen.getByTestId('unpushed-count')).toHaveTextContent('novels.unpushed 2')
    expect(screen.queryByRole('button', { name: 'novels.reset' })).not.toBeInTheDocument()
  })

  it('shows the locked banner when locked', () => {
    h.status = { head: 'abc', ahead: 0, behind: 0, clean: true, locked: true }
    render(<RepoStatusBar />)
    expect(screen.getByRole('alert')).toHaveTextContent('novels.locked')
  })

  it('shows the reset button for admins', () => {
    h.role = 'admin'
    render(<RepoStatusBar />)
    expect(screen.getByRole('button', { name: 'novels.reset' })).toBeInTheDocument()
  })
})
