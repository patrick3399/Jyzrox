import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { RefreshCw } from 'lucide-react'
import { GalleryActionsSheet } from '@/components/library/GalleryActionsSheet'

vi.mock('next/link', () => ({
  default: ({ children, href, ...rest }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}))

describe('GalleryActionsSheet', () => {
  it('renders an action description as a second line inside the same control', () => {
    render(
      <GalleryActionsSheet
        open
        onClose={vi.fn()}
        groups={[
          [
            {
              id: 'a',
              label: 'Check now',
              description: 'Checked 3d ago',
              icon: RefreshCw,
              onSelect: vi.fn(),
            },
          ],
        ]}
      />,
    )
    const button = screen.getByRole('button', { name: /Check now/ })
    expect(button).toHaveTextContent('Checked 3d ago')
  })

  it('renders no second line when an action has no description', () => {
    render(
      <GalleryActionsSheet
        open
        onClose={vi.fn()}
        groups={[[{ id: 'a', label: 'Share', icon: RefreshCw, onSelect: vi.fn() }]]}
      />,
    )
    expect(screen.getByRole('button', { name: 'Share' })).toHaveTextContent(/^Share$/)
  })
})
