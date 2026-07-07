import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

vi.mock('@/lib/i18n', () => ({
  t: (key: string, vars?: Record<string, string | number>) =>
    vars ? `${key} ${Object.values(vars).join(' ')}` : key,
}))
vi.mock('@/components/LocaleProvider', () => ({ useLocale: () => 'en' }))
vi.mock('@/components/LoadingSpinner', () => ({ LoadingSpinner: () => <span data-testid="spin" /> }))
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn() }),
}))

const h = vi.hoisted(() => ({
  keys: [] as unknown[],
  data: {
    notes: [{ path: '作品A/Setting/角色-張三.md', title: '張三', note_type: 'character', frontmatter: {} }],
  },
}))

vi.mock('swr', () => ({
  default: (key: unknown) => {
    h.keys.push(key)
    return { data: h.data, isLoading: false }
  },
}))

import NovelNotesPage from '@/app/novels/notes/page'

describe('NovelNotesPage', () => {
  beforeEach(() => {
    h.keys.length = 0
  })

  it('renders notes from the API', () => {
    render(<NovelNotesPage />)
    expect(screen.getByText('張三')).toBeTruthy()
  })

  it('selecting the event type requests the story_order sort (plot timeline)', () => {
    render(<NovelNotesPage />)
    fireEvent.change(screen.getByLabelText('novels.filterByType'), { target: { value: 'event' } })
    const last = h.keys[h.keys.length - 1] as unknown[]
    expect(last).toContain('event')
    expect(last).toContain('story_order')
  })
})
