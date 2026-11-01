'use client'
import type { CSSProperties } from 'react'
import { AppImage } from '@/components/AppImage'
import { getSpriteThumbnailStyle } from './thumbnailSprite'
import type { ReaderImage } from './types'

export interface SpriteNaturalSizes {
  [proxyUrl: string]: { w: number; h: number }
}

export interface ThumbnailCellProps {
  image: ReaderImage
  isActive: boolean
  /** Preview thumb from EH CDN: "url" (plain) or "url|ox|w|h" (sprite cell). */
  previewRaw: string | undefined
  spriteNaturalSizes: SpriteNaturalSizes
  frameWidth: number
  frameHeight: number
  onSelect: (page: number) => void
}

/**
 * Renders one thumbnail: EH sprite cell, plain EH/local thumb, or a bare
 * page-number placeholder when no thumb source is available yet.
 *
 * Shared by `ThumbnailStrip` and `ThumbnailGridOverlay` so the sprite crop
 * math (FE-T7 — fixed 6 times because it kept getting reimplemented) lives
 * in exactly one place. Callers own sizing/positioning; this component fills
 * its parent (`h-full w-full`).
 */
export function ThumbnailCell({
  image,
  isActive,
  previewRaw,
  spriteNaturalSizes,
  frameWidth,
  frameHeight,
  onSelect,
}: ThumbnailCellProps) {
  let thumbSrc: string | null = null
  let spriteStyle: CSSProperties | null = null

  if (previewRaw) {
    if (previewRaw.includes('|')) {
      const parts = previewRaw.split('|')
      const spriteUrl = parts[0]
      const ox = Number(parts[1])
      const cellW = Number(parts[2]) || 200
      const cellH = Number(parts[3]) || 300
      const proxyUrl = `/api/eh/thumb-proxy?url=${encodeURIComponent(spriteUrl)}`
      const naturalSize = spriteNaturalSizes[proxyUrl]
      if (naturalSize) {
        const geometry = getSpriteThumbnailStyle({
          offsetX: ox,
          cellWidth: cellW,
          cellHeight: cellH,
          spriteWidth: naturalSize.w,
          spriteHeight: naturalSize.h,
          frameWidth,
          frameHeight,
        })
        if (geometry) {
          spriteStyle = {
            backgroundImage: `url(${proxyUrl})`,
            backgroundPosition: geometry.backgroundPosition,
            backgroundSize: geometry.backgroundSize,
            backgroundRepeat: 'no-repeat',
            width: '100%',
            height: '100%',
          }
        }
      }
    } else {
      thumbSrc = `/api/eh/thumb-proxy?url=${encodeURIComponent(previewRaw)}`
    }
  } else if (image.isLocal) {
    // A video has no usable <img> source other than its generated thumbnail;
    // a pending video (not hashed yet) has none, so it keeps the placeholder.
    thumbSrc = image.thumbUrl || (image.mediaType !== 'video' ? image.url : null)
  }

  return (
    <button
      onClick={() => onSelect(image.pageNum)}
      className={`relative block h-full w-full overflow-hidden rounded ${
        isActive ? 'ring-2 ring-white opacity-100' : 'opacity-50 hover:opacity-80'
      }`}
      title={`Page ${image.pageNum}`}
    >
      {spriteStyle ? (
        <div style={spriteStyle} />
      ) : thumbSrc ? (
        <AppImage
          src={thumbSrc}
          alt={`Thumb ${image.pageNum}`}
          className="h-full w-full object-cover"
          sizes={`${frameWidth}px`}
        />
      ) : (
        <div className="h-full w-full bg-neutral-800 flex items-center justify-center">
          <span className="text-[11px] text-gray-500">{image.pageNum}</span>
        </div>
      )}
      <span className="absolute bottom-0 left-0 right-0 bg-black/60 text-center text-[10px] text-white leading-tight py-px">
        {image.pageNum}
      </span>
    </button>
  )
}
