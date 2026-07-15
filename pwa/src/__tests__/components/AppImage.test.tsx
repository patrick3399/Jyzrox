import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AppImage } from '@/components/AppImage'

describe('AppImage', () => {
  it('renders a shared fallback after an image error', () => {
    render(
      <AppImage src="/media/missing.jpg" alt="Gallery cover" fallback={<span>Unavailable</span>} />,
    )

    fireEvent.error(screen.getByRole('img', { name: 'Gallery cover' }))

    expect(screen.getByText('Unavailable')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Gallery cover' }).tagName).toBe('DIV')
  })

  it('resets the error state when the source changes', () => {
    const { rerender } = render(<AppImage src="/first.jpg" alt="Cover" />)
    fireEvent.error(screen.getByRole('img', { name: 'Cover' }))

    rerender(<AppImage src="/second.jpg" alt="Cover" />)

    expect(screen.getByRole('img', { name: 'Cover' }).tagName).toBe('IMG')
  })
})
