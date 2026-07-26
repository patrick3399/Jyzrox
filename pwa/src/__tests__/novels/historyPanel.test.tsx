import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

vi.mock('@/lib/i18n', () => ({
  t: (key: string, vars?: Record<string, string | number>) =>
    vars ? `${key} ${Object.values(vars).join(' ')}` : key,
}))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))

const h = vi.hoisted(() => ({
  commits: [
    { hash: 'aaaaaaa1111', date: '2026-07-20T10:00:00Z', message: 'edit: 第01章' },
    { hash: 'bbbbbbb2222', date: '2026-07-19T10:00:00Z', message: 'init' },
  ],
  diff: vi.fn(async () => ({ diff: '@@ -1 +1 @@\n-old\n+new' })),
  status: vi.fn(async () => ({ head: 'headsha', ahead: 0, behind: 0, clean: true, locked: false })),
  revertFile: vi.fn(async () => ({ head: 'newhead', pushed: true, reverted_to: 'bbbbbbb2222' })),
  mutate: vi.fn(),
}))

// Minimal SWR stand-in: routes each key to the matching fetcher result so the
// panel's diff key (which carries the compare base) is exercised for real.
vi.mock('swr', () => ({
  default: (key: unknown, fetcher: (k: unknown) => unknown) => {
    if (!key) return { data: undefined, isLoading: false }
    const k = key as unknown[]
    if (k[0] === 'novel-history') return { data: { commits: h.commits }, isLoading: false }
    fetcher(key) // records the api.novels.diff call with the key's compare base
    return { data: { diff: '@@ -1 +1 @@\n-old\n+new' }, isLoading: false }
  },
  mutate: (...args: unknown[]) => h.mutate(...args),
}))
vi.mock('@/lib/api', () => ({
  api: {
    novels: {
      history: vi.fn(),
      diff: (...args: unknown[]) => h.diff(...(args as [])),
      status: () => h.status(),
      revertFile: (...args: unknown[]) => h.revertFile(...(args as [])),
    },
  },
}))

import { HistoryPanel } from '@/components/novels/HistoryPanel'

describe('HistoryPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
  })

  it('hides revert controls from users without write access', () => {
    render(<HistoryPanel path="作品A/第01章.md" />)
    expect(screen.queryByLabelText(/novels.revertTo/)).not.toBeInTheDocument()
    // Compare is read-only, so it stays available.
    expect(screen.getAllByLabelText(/novels.compareWith/)).toHaveLength(2)
  })

  it('diffs a commit against its parent by default', async () => {
    render(<HistoryPanel path="作品A/第01章.md" canEdit />)
    await userEvent.click(screen.getByText('edit: 第01章'))
    expect(h.diff).toHaveBeenCalledWith('作品A/第01章.md', 'aaaaaaa1111', undefined)
  })

  it('diffs against the chosen base once a compare target is picked', async () => {
    render(<HistoryPanel path="作品A/第01章.md" canEdit />)
    await userEvent.click(screen.getByText('edit: 第01章'))
    await userEvent.click(screen.getByLabelText('novels.compareWith bbbbbbb'))
    expect(h.diff).toHaveBeenLastCalledWith('作品A/第01章.md', 'aaaaaaa1111', 'bbbbbbb2222')
    expect(screen.getByTestId('compare-base')).toHaveTextContent('bbbbbbb')
  })

  it('reverts using a freshly read HEAD, not the stale panel state', async () => {
    render(<HistoryPanel path="作品A/第01章.md" canEdit />)
    await userEvent.click(screen.getByLabelText('novels.revertTo bbbbbbb'))
    await waitFor(() => expect(h.revertFile).toHaveBeenCalled())
    expect(h.status).toHaveBeenCalled()
    expect(h.revertFile).toHaveBeenCalledWith('作品A/第01章.md', 'bbbbbbb2222', 'headsha')
  })

  it('does not revert when the confirmation is declined', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    render(<HistoryPanel path="作品A/第01章.md" canEdit />)
    await userEvent.click(screen.getByLabelText('novels.revertTo bbbbbbb'))
    expect(h.revertFile).not.toHaveBeenCalled()
  })
})
