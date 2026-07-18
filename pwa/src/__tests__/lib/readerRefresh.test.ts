import { describe, expect, it } from 'vitest'
import {
  numberSetsEqual,
  readerGalleryStateEqual,
  readerImagesEqual,
  READER_DOWNLOAD_REFRESH_INTERVAL_MS,
} from '@/lib/readerRefresh'
import type { Gallery, GalleryImage } from '@/lib/types'

const gallery = {
  id: 1,
  title: 'Gallery',
  pages: 10,
  download_status: 'downloading',
  cover_thumb: null,
} as Gallery

const image = {
  id: 1,
  page_num: 1,
  file_path: '/media/cas/a.jpg',
  thumb_path: '/media/thumbs/a/thumb_160.webp',
  media_type: 'image',
  visibility: 'active',
} as GalleryImage

describe('reader download refresh', () => {
  it('coalesces progress bursts to a multi-second interval', () => {
    expect(READER_DOWNLOAD_REFRESH_INTERVAL_MS).toBeGreaterThanOrEqual(3000)
  })

  it('keeps existing state when a progress event contains no reader-visible changes', () => {
    expect(readerGalleryStateEqual(gallery, { ...gallery })).toBe(true)
    expect(readerImagesEqual([image], [{ ...image }])).toBe(true)
    expect(numberSetsEqual([2, 1], [1, 2])).toBe(true)
  })

  it('detects newly imported pages and download completion', () => {
    expect(readerImagesEqual([image], [image, { ...image, id: 2, page_num: 2 }])).toBe(false)
    expect(
      readerGalleryStateEqual(gallery, {
        ...gallery,
        download_status: 'complete',
      }),
    ).toBe(false)
  })
})
