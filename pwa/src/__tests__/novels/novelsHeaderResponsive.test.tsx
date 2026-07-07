import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('@/lib/i18n', () => ({
  t: (key: string, vars?: Record<string, string | number>) =>
    vars ? `${key} ${Object.values(vars).join(' ')}` : key,
}))

vi.mock('@/components/LocaleProvider', () => ({ useLocale: () => 'en' }))
vi.mock('@/components/LoadingSpinner', () => ({ LoadingSpinner: () => <span /> }))
vi.mock('@/components/novels/RepoStatusBar', () => ({ RepoStatusBar: () => null }))
vi.mock('@/components/novels/NovelCreateDialog', () => ({ NovelCreateDialog: () => null }))
vi.mock('next/navigation', () => ({ useRouter: () => ({ push: vi.fn() }) }))
// member role → the "new work" action also renders (4 toolbar actions total).
vi.mock('@/hooks/useProfile', () => ({ useProfile: () => ({ data: { role: 'admin' } }) }))

vi.mock('swr', () => ({
  default: () => ({ data: { works: [] }, isLoading: false }),
  mutate: vi.fn(),
}))

vi.mock('@/lib/api', () => ({ api: { novels: { listWorks: vi.fn() } } }))

import NovelsPage from '@/app/novels/page'

// The header toolbar has title + 4 actions; on a phone the full-width text
// labels overflow the viewport. The fix keeps each action reachable by giving
// it an accessible name and collapsing its visible label on narrow screens.
const ACTIONS = ['novels.newWork', 'novels.graph', 'novels.notes', 'novels.search']

describe('NovelsPage header on mobile', () => {
  it('keeps every toolbar action accessible with a collapsible label', () => {
    render(<NovelsPage />)
    for (const key of ACTIONS) {
      const el = screen.getByLabelText(key)
      expect(el).toBeInTheDocument()
      const label = Array.from(el.querySelectorAll('span')).find((s) => s.textContent === key)
      expect(label, `label span for ${key}`).toBeTruthy()
      // Visible text collapses on mobile so the toolbar fits narrow screens.
      expect(label!.className).toContain('hidden')
    }
  })
})
