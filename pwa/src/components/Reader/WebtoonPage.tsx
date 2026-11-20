'use client'
import { useCallback, useState } from 'react'
import type { ReaderImage, ScaleMode } from './types'
import { Spinner } from './Spinner'
import { MediaElement } from './MediaElement'
import type { ImageLongPressHandlers } from './viewTypes'

/**
 * Space an unloaded webtoon image takes. Lazy loading only works when pages
 * below the fold have a height: as 0px boxes they all sit in the viewport and
 * the browser fetches every original in the gallery.
 */
function webtoonPlaceholderStyle(image: ReaderImage, scaleMode: ScaleMode): React.CSSProperties {
  const { width, height } = image
  if (!width || !height) return { width: '100%', height: '100vh' }
  switch (scaleMode) {
    case 'fit-height':
      return { width: '100%', height: '100vh' }
    case 'original':
      return { width: '100%', height: `${height}px` }
    case 'fit-width':
      return { width: '100%', aspectRatio: `${width} / ${height}` }
    case 'fit-both':
    default:
      return { width: '100%', aspectRatio: `${width} / ${height}`, maxHeight: '100vh' }
  }
}

interface WebtoonPageProps {
  image: ReaderImage
  isLast: boolean
  scaleMode: ScaleMode
  scaleClass: string
  register: (pageNum: number, el: HTMLElement | null) => void
  imageLongPress?: (pageNum: number, imageUrl: string) => ImageLongPressHandlers
}

/**
 * One webtoon page. Its load state is its own, so a settling image re-renders
 * this page only, not the whole list.
 */
export function WebtoonPage({
  image,
  isLast,
  scaleMode,
  scaleClass,
  register,
  imageLongPress,
}: WebtoonPageProps) {
  const [settled, setSettled] = useState(false)
  const settle = useCallback(() => setSettled(true), [])
  const lpHandlers =
    imageLongPress && image.url ? imageLongPress(image.pageNum, image.url) : undefined
  // Still-downloading pages size themselves. A video settles on its metadata,
  // which it only fetches near the screen, and keeps its box afterwards: away
  // from the screen it drops its source and would shrink to its poster, or to
  // 300x150 before the poster decodes. iOS Safari has no scroll anchoring, so
  // each shrink above the viewport jumped the page during a fast scroll.
  const reserve = image.url != null && (!settled || image.mediaType === 'video')
  return (
    <>
      <div
        ref={(el) => register(image.pageNum, el)}
        data-page={image.pageNum}
        style={reserve ? webtoonPlaceholderStyle(image, scaleMode) : undefined}
        onTouchStart={lpHandlers?.onTouchStart}
        onTouchMove={lpHandlers?.onTouchMove}
        onTouchEnd={lpHandlers?.onTouchEnd}
        onContextMenu={lpHandlers?.onContextMenu}
      >
        <MediaElement
          image={image}
          className={scaleClass}
          loading="lazy"
          onLoad={settle}
          onError={settle}
        />
      </div>
      {/* Spinner if the last page hasn't loaded yet */}
      {isLast && !settled && (
        <div className="flex justify-center py-8">
          <Spinner />
        </div>
      )}
    </>
  )
}
