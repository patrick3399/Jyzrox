import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('@/lib/i18n', () => ({
  // Only the keys the panel needs are "translated"; anything else falls through
  // as its own key, which is what the real t() does for an unknown key.
  t: (key: string, vars?: Record<string, string | number>) => {
    const known: Record<string, string> = {
      'novels.lint.dialogue_colon_outside_bold': 'colon inside the bold',
    }
    const base = known[key] ?? key
    return vars ? `${base} ${Object.values(vars).join(' ')}` : base
  },
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const h = vi.hoisted(() => ({
  issues: [
    { rule: 'dialogue_colon_outside_bold', line: 3, text: '**張三**：「嗨。」' },
    { rule: 'brand_new_backend_rule', line: 9, text: '???' },
  ] as { rule: string; line: number; text: string }[],
  status: vi.fn(async () => ({ head: 'headsha', ahead: 0, behind: 0, clean: true, locked: false })),
  fixFile: vi.fn(async () => ({ changes: ['dialogue_colon_outside_bold'], head: 'h2', pushed: true })),
  mutate: vi.fn(),
}))

vi.mock('swr', () => ({
  default: (key: unknown) =>
    key ? { data: { path: 'p', issues: h.issues }, isLoading: false } : { data: undefined, isLoading: false },
  mutate: (...args: unknown[]) => h.mutate(...args),
}))
vi.mock('@/lib/api', () => ({
  api: {
    novels: {
      lintFile: vi.fn(),
      status: () => h.status(),
      fixFile: (...args: unknown[]) => h.fixFile(...(args as [])),
    },
  },
}))

import { FormatPanel, ruleLabel } from '@/components/novels/FormatPanel'

describe('FormatPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    h.issues = [
      { rule: 'dialogue_colon_outside_bold', line: 3, text: '**張三**：「嗨。」' },
      { rule: 'brand_new_backend_rule', line: 9, text: '???' },
    ]
  })

  it('lists each issue with its line number and rule wording', () => {
    render(<FormatPanel path="作品A/第01章.md" />)
    const items = screen.getByTestId('format-issues').querySelectorAll('li')
    expect(items).toHaveLength(2)
    expect(items[0].textContent).toContain('novels.formatAtLine 3')
    expect(items[0].textContent).toContain('colon inside the bold')
  })

  it('falls back to the rule id for a rule the UI has no wording for yet', () => {
    // A backend rule added without an i18n key must still render as something.
    expect(ruleLabel('brand_new_backend_rule')).toBe('brand_new_backend_rule')
    render(<FormatPanel path="作品A/第01章.md" />)
    expect(screen.getByText(/brand_new_backend_rule/)).toBeInTheDocument()
  })

  it('offers the auto-fix only to users with write access', () => {
    render(<FormatPanel path="作品A/第01章.md" />)
    expect(screen.queryByRole('button', { name: 'novels.formatFix' })).not.toBeInTheDocument()
  })

  it('hides the auto-fix when the file already conforms', () => {
    h.issues = []
    render(<FormatPanel path="作品A/第01章.md" canEdit />)
    expect(screen.queryByRole('button', { name: 'novels.formatFix' })).not.toBeInTheDocument()
    expect(screen.getByText('novels.formatClean')).toBeInTheDocument()
  })

  it('fixes against a freshly read HEAD and refreshes the lint result', async () => {
    render(<FormatPanel path="作品A/第01章.md" canEdit />)
    await userEvent.click(screen.getByRole('button', { name: 'novels.formatFix' }))
    await waitFor(() => expect(h.fixFile).toHaveBeenCalled())
    expect(h.status).toHaveBeenCalled()
    expect(h.fixFile).toHaveBeenCalledWith('作品A/第01章.md', 'headsha')
    expect(h.mutate).toHaveBeenCalledWith(['novel-lint', '作品A/第01章.md'])
  })
})
