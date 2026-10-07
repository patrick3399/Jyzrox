import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ThumbnailCell } from '@/components/Reader/ThumbnailCell'
import type { ReaderImage } from '@/components/Reader/types'

vi.mock('@/components/AppImage', () => ({
  AppImage: ({ src, alt }: { src: string; alt: string }) => <img src={src} alt={alt} />,
}))

function renderCell(image: ReaderImage) {
  return render(
    <ThumbnailCell
      image={image}
      isActive={false}
      previewRaw={undefined}
      spriteNaturalSizes={{}}
      frameWidth={60}
      frameHeight={80}
      onSelect={vi.fn()}
    />,
  )
}

describe('ThumbnailCell pending media', () => {
  it('does not use a pending video file as an <img> source', () => {
    const { container } = renderCell({
      pageNum: 2,
      url: '/media/libraries/a/clip.mp4',
      isLocal: true,
      mediaType: 'video',
      thumbUrl: null,
    })

    expect(container.querySelector('img')).toBeNull()
    expect(container.innerHTML).not.toContain('.mp4')
    // Falls back to the existing page-number placeholder.
    expect(screen.getAllByText('2')).toHaveLength(2)
  })

  it('still uses the thumbnail of a video that has one', () => {
    renderCell({
      pageNum: 2,
      url: '/media/cas/ab/clip.mp4',
      isLocal: true,
      mediaType: 'video',
      thumbUrl: '/media/thumbs/ab/thumb_160.webp',
    })

    expect(screen.getByAltText('Thumb 2')).toHaveAttribute('src', '/media/thumbs/ab/thumb_160.webp')
  })

  it('falls back to the original file for a pending still image with no thumbnail', () => {
    renderCell({
      pageNum: 4,
      url: '/media/libraries/a/p4.jpg',
      isLocal: true,
      mediaType: 'image',
      thumbUrl: null,
    })

    expect(screen.getByAltText('Thumb 4')).toHaveAttribute('src', '/media/libraries/a/p4.jpg')
  })
})
