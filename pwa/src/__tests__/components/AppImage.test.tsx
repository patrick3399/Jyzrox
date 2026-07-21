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
    expect(sources[0]).toHaveAttribute('sizes', '50vw')
    expect(sources[1]).toHaveAttribute('type', 'image/webp')

    const avifSrcSet = sources[0].getAttribute('srcset') ?? ''
    expect(avifSrcSet).toContain('/media/image/insecure/rs:fit:320:0:0/')
    expect(avifSrcSet).toContain('.avif 320w')
    // Regression: the imgproxy source must be base64-encoded so it carries no
    // `local:///` (or any `//`) that nginx merge_slashes would collapse + 308.
    expect(avifSrcSet).not.toContain('local:')
    expect(avifSrcSet).not.toContain('://')
    expect(avifSrcSet).not.toContain('//')

    // The encoded source round-trips back to the local imgproxy path.
    const firstVariant = avifSrcSet.split(',')[0].trim().split(' ')[0]
    const encoded = firstVariant
      .replace('/media/image/insecure/rs:fit:320:0:0/', '')
      .replace(/\.avif$/, '')
    const decoded = atob(encoded.replace(/-/g, '+').replace(/_/g, '/'))
    expect(decoded).toBe('local:///cas/aa/bb/hash.jpg')
  })

  // imgproxy can be cold, misconfigured, or unable to encode a given original.
  // A failed <source> must degrade to the untransformed image before the shared
  // fallback takes over, so a transcode failure never hides an image that exists.
  it('falls back to the original source before showing the shared fallback', () => {
    const { container } = render(
      <AppImage
        src="/media/cas/aa/bb/hash.jpg"
        alt="Thumbnail"
        fallback={<span>Unavailable</span>}
      />,
    )

    fireEvent.error(screen.getByRole('img', { name: 'Thumbnail' }))
    expect(container.querySelector('picture')).toBeNull()
    expect(screen.getByRole('img', { name: 'Thumbnail' })).toHaveAttribute(
      'src',
      '/media/cas/aa/bb/hash.jpg',
    )

    fireEvent.error(screen.getByRole('img', { name: 'Thumbnail' }))
    expect(screen.getByText('Unavailable')).toBeInTheDocument()
  })

  it('leaves remote images unchanged', () => {
    const { container } = render(<AppImage src="https://example.test/image.jpg" alt="Remote" />)
    expect(container.querySelector('picture')).toBeNull()
  })

  it('uses static responsive variants without routing thumbnails through imgproxy', () => {
    const { container } = render(
      <AppImage src="/media/thumbs/aa/bb/hash/thumb_160.webp" alt="Thumb" sizes="50vw" />,
    )
    expect(container.querySelector('picture')).toBeNull()
    expect(container.querySelector('source')).toBeNull()
    const img = container.querySelector('img')
    expect(img).not.toBeNull()
    expect(img).toHaveAttribute('src', '/media/thumbs/aa/bb/hash/thumb_160.webp')
    expect(img).toHaveAttribute(
      'srcset',
      '/media/thumbs/aa/bb/hash/thumb_160.webp 160w, /media/thumbs/aa/bb/hash/thumb_360.webp 360w, /media/thumbs/aa/bb/hash/thumb_720.webp 720w',
    )
    expect(img).toHaveAttribute('sizes', '50vw')
  })

  it('falls back to the 160px thumbnail when a responsive candidate fails', () => {
    render(
      <AppImage
        src="/media/thumbs/aa/bb/hash/thumb_160.webp"
        alt="Thumb"
        fallback={<span>Unavailable</span>}
      />,
    )

    const image = screen.getByRole('img', { name: 'Thumb' })
    fireEvent.error(image)
    expect(screen.getByRole('img', { name: 'Thumb' })).not.toHaveAttribute('srcset')
    fireEvent.error(screen.getByRole('img', { name: 'Thumb' }))
    expect(screen.getByText('Unavailable')).toBeInTheDocument()
  })
})
