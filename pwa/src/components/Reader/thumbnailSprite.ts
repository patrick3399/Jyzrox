export interface SpriteThumbnailGeometry {
  offsetX: number
  cellWidth: number
  cellHeight: number
  spriteWidth: number
  spriteHeight: number
  frameWidth: number
  frameHeight: number
}

export interface SpriteThumbnailStyle {
  backgroundPosition: string
  backgroundSize: string
}

/**
 * Scale and center-crop one cell from an EH preview sprite into a fixed frame.
 *
 * EH places cells of different aspect ratios side by side at the top of one
 * sprite sheet. The cell dimensions describe the visible preview; the sprite
 * dimensions are only needed to size the full background without offset drift.
 */
export function getSpriteThumbnailStyle({
  offsetX,
  cellWidth,
  cellHeight,
  spriteWidth,
  spriteHeight,
  frameWidth,
  frameHeight,
}: SpriteThumbnailGeometry): SpriteThumbnailStyle | null {
  const dimensions = [cellWidth, cellHeight, spriteWidth, spriteHeight, frameWidth, frameHeight]
  if (!dimensions.every((value) => Number.isFinite(value) && value > 0)) return null
  if (!Number.isFinite(offsetX)) return null

  const scale = Math.max(frameWidth / cellWidth, frameHeight / cellHeight)
  const cropX = Math.max(0, (cellWidth * scale - frameWidth) / 2)
  const cropY = Math.max(0, (cellHeight * scale - frameHeight) / 2)
  const spriteX = Math.abs(offsetX) * scale

  return {
    backgroundPosition: `-${spriteX + cropX}px -${cropY}px`,
    backgroundSize: `${spriteWidth * scale}px ${spriteHeight * scale}px`,
  }
}
