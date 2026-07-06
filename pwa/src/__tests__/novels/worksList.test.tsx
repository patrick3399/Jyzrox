import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('@/lib/i18n', () => ({
  t: (key: string, vars?: Record<string, string | number>) =>
    vars ? `${key} ${Object.values(vars).join(' ')}` : key,
}))

vi.mock('@/components/LocaleProvider', () => ({
  useLocale: () => 'en',
}))

vi.mock('@/components/LoadingSpinner', () => ({
  LoadingSpinner: () => <span data-testid="loading-spinner" />,
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}))

let mockWorks: unknown = undefined
let mockLoading = false
vi.mock('swr', () => ({
  default: () => ({ data: mockWorks, isLoading: mockLoading }),
}))

vi.mock('@/lib/api', () => ({
  api: { novels: { listWorks: vi.fn() } },
}))

import NovelsPage from '@/app/novels/page'

describe('NovelsPage', () => {
  it('renders works with chapter counts', () => {
    mockWorks = { works: [{ name: '作品A', chapter_count: 12 }] }
    mockLoading = false
    render(<NovelsPage />)
    expect(screen.getByText('作品A')).toBeInTheDocument()
    expect(screen.getByText('novels.chapterCount 12')).toBeInTheDocument()
  })

  it('shows empty state when no works', () => {
    mockWorks = { works: [] }
    mockLoading = false
    render(<NovelsPage />)
    expect(screen.getByText('novels.noWorks')).toBeInTheDocument()
  })
})
