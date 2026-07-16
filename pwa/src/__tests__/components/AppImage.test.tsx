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

  it('adds AVIF and WebP responsive sources for local media', () => {
    const { container } = render(
      <AppImage src="/media/cas/aa/bb/hash.jpg" alt="Cover" sizes="50vw" />,
    )

    const sources = container.querySelectorAll('source')
    expect(sources).toHaveLength(2)
    expect(sources[0]).toHaveAttribute('type', 'image/avif')
    expect(sources[0].getAttribute('srcset')).toContain('local:///cas/aa/bb/hash.jpg@avif 320w')
    expect(sources[0]).toHaveAttribute('sizes', '50vw')
    expect(sources[1]).toHaveAttribute('type', 'image/webp')
  })

  it('leaves remote images unchanged', () => {
    const { container } = render(<AppImage src="https://example.test/image.jpg" alt="Remote" />)
    expect(container.querySelector('picture')).toBeNull()
  })
})
