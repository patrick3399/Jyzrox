import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

vi.mock('@/lib/i18n', () => ({
  t: (key: string, vars?: Record<string, string | number>) =>
    vars ? `${key} ${Object.values(vars).join(' ')}` : key,
}))

import { AppearanceTimeline } from '@/components/novels/AppearanceTimeline'

describe('AppearanceTimeline', () => {
  it('renders one ordered row per appearance with chapter name + mention count', () => {
    render(
      <AppearanceTimeline
        appearances={[
          { chapter_path: '作品A/01.md', mention_count: 3, first_offset: 0 },
          { chapter_path: '作品A/02.md', mention_count: 1, first_offset: 5 },
        ]}
      />,
    )
    expect(screen.getByText('01.md')).toBeTruthy()
    expect(screen.getByText('02.md')).toBeTruthy()
    expect(screen.getByText('novels.mentionCount 3')).toBeTruthy()
    // Only the first (earliest) chapter is flagged as the first appearance.
    expect(screen.getAllByText('novels.firstAppearance')).toHaveLength(1)
  })

  it('shows an empty state when there are no appearances', () => {
    render(<AppearanceTimeline appearances={[]} />)
    expect(screen.getByText('novels.noAppearances')).toBeTruthy()
  })
})
