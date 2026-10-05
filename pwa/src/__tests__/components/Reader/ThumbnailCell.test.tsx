import { describe, expect, it, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { ThumbnailCell } from '@/components/Reader/ThumbnailCell'
import type { ReaderImage } from '@/components/Reader/types'

vi.mock('@/components/AppImage', () => ({
  AppImage: ({ src, alt }: { src: string; alt: string }) => <img src={src} alt={alt} />,
}))

const baseImage: ReaderImage = {
  pageNum: 3,
  url: '/media/cas/a.jpg',
  isLocal: true,
  mediaType: 'image',
}

describe('ThumbnailCell', () => {
  it('renders a local thumb via AppImage when there is no EH preview', () => {
    render(
      <ThumbnailCell
        image={baseImage}
        isActive={false}
        previewRaw={undefined}
        spriteNaturalSizes={{}}
        frameWidth={60}
        frameHeight={80}
        onSelect={vi.fn()}
      />,
    )
    expect(screen.getByAltText('Thumb 3')).toHaveAttribute('src', '/media/cas/a.jpg')
    expect(screen.getByText('3')).toBeInTheDocument()
  })

  it('renders a placeholder page number when there is no thumb source at all', () => {
    render(
      <ThumbnailCell
        image={{ ...baseImage, isLocal: false, url: null }}
        isActive={false}
        previewRaw={undefined}
        spriteNaturalSizes={{}}
        frameWidth={60}
        frameHeight={80}
        onSelect={vi.fn()}
      />,
    )
    // Placeholder renders the page number twice: the badge label and the
    // centered placeholder digit. Both must be present, neither an <img>.
    expect(screen.getAllByText('3')).toHaveLength(2)
    expect(screen.queryByRole('img')).not.toBeInTheDocument()
  })

  it('renders sprite background-position/size once natural sprite size is known', () => {
    const previewRaw = 'https://example.com/sprite.jpg|100|200|300'
    const proxyUrl = `/api/eh/thumb-proxy?url=${encodeURIComponent('https://example.com/sprite.jpg')}`
    render(
      <ThumbnailCell
        image={baseImage}
        isActive={false}
        previewRaw={previewRaw}
        spriteNaturalSizes={{ [proxyUrl]: { w: 2000, h: 300 } }}
        frameWidth={60}
        frameHeight={80}
        onSelect={vi.fn()}
      />,
    )
    const sprite = document.querySelector('[style*="background-image"]') as HTMLElement | null
    expect(sprite).not.toBeNull()
    expect(sprite?.style.backgroundImage).toContain(proxyUrl)
  })

  it('calls onSelect with the page number when clicked', () => {
    const onSelect = vi.fn()
    render(
      <ThumbnailCell
        image={baseImage}
        isActive={false}
        previewRaw={undefined}
        spriteNaturalSizes={{}}
        frameWidth={60}
        frameHeight={80}
        onSelect={onSelect}
      />,
    )
    fireEvent.click(screen.getByRole('button'))
    expect(onSelect).toHaveBeenCalledWith(3)
  })

  it('applies the active ring class only when isActive is true', () => {
    const { rerender } = render(
      <ThumbnailCell
        image={baseImage}
        isActive={false}
        previewRaw={undefined}
        spriteNaturalSizes={{}}
        frameWidth={60}
        frameHeight={80}
        onSelect={vi.fn()}
      />,
    )
    expect(screen.getByRole('button').className).not.toContain('ring-2')

    rerender(
      <ThumbnailCell
        image={baseImage}
        isActive={true}
        previewRaw={undefined}
        spriteNaturalSizes={{}}
        frameWidth={60}
        frameHeight={80}
        onSelect={vi.fn()}
      />,
    )
    expect(screen.getByRole('button').className).toContain('ring-2')
  })
})
