import { describe, expect, it } from 'vitest'

import { getSpriteThumbnailStyle } from '@/components/Reader/thumbnailSprite'

describe('Reader EH sprite thumbnail geometry', () => {
  it('center-crops a short landscape cell into the full portrait frame', () => {
    const style = getSpriteThumbnailStyle({
      offsetX: -400,
      cellWidth: 200,
      cellHeight: 57,
      spriteWidth: 1000,
      spriteHeight: 300,
      frameWidth: 60,
      frameHeight: 80,
    })

    expect(style).not.toBeNull()
    expect(style?.backgroundSize).toBe('1403.5087719298244px 421.05263157894734px')
    expect(style?.backgroundPosition).toBe('-671.7543859649122px -0px')
  })

  it('center-crops a portrait cell vertically without changing its sprite offset sign', () => {
    const style = getSpriteThumbnailStyle({
      offsetX: -200,
      cellWidth: 200,
      cellHeight: 300,
      spriteWidth: 1000,
      spriteHeight: 300,
      frameWidth: 60,
      frameHeight: 80,
    })

    expect(style).toEqual({
      backgroundPosition: '-60px -5px',
      backgroundSize: '300px 90px',
    })
  })

  it('rejects incomplete sprite dimensions instead of rendering with wrong geometry', () => {
    expect(
      getSpriteThumbnailStyle({
        offsetX: 0,
        cellWidth: 200,
        cellHeight: 57,
        spriteWidth: 0,
        spriteHeight: 0,
        frameWidth: 60,
        frameHeight: 80,
      }),
    ).toBeNull()
  })
})
