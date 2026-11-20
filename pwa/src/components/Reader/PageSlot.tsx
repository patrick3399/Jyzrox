'use client'
import { useEffect, useState } from 'react'
import type { ReaderImage } from './types'
import { MediaElement } from './MediaElement'

// Inline rather than a class: the scale classes carry `block`, and an inline
// declaration is the only one guaranteed to win over it.
const RETAINED_SLOT_STYLE: React.CSSProperties = { display: 'none' }

interface PageSlotProps {
  image: ReaderImage
  isCurrent: boolean
  className: string
  onCurrentLoaded: () => void
  onCurrentError: () => void
  onSlotLoaded: (pageNum: number) => void
  onToggleOverlay: () => void
  overlayVisible: boolean
}

/**
 * One page of the single-page view. The view keeps the previous and next page
 * mounted next to the current one, hidden, so turning back reuses an element
 * that already holds its image instead of requesting it again.
 */
export function PageSlot({
  image,
  isCurrent,
  className,
  onCurrentLoaded,
  onCurrentError,
  onSlotLoaded,
  onToggleOverlay,
  overlayVisible,
}: PageSlotProps) {
  // Load outcome of the element this slot holds, tagged with the URL so a page
  // that gains or changes its URL starts over as pending.
  const [settled, setSettled] = useState<{
    url: string | null
    status: 'loaded' | 'error'
  } | null>(null)
  const status = settled && settled.url === image.url ? settled.status : 'pending'

  // A retained slot has usually finished loading while hidden, and its element
  // will not fire `load` again. Replaying the outcome when the slot becomes
  // current keeps the parent spinner from waiting on an event that already
  // happened.
  useEffect(() => {
    if (!isCurrent) return
    if (status === 'loaded') onCurrentLoaded()
    else if (status === 'error') onCurrentError()
  }, [isCurrent, status, onCurrentLoaded, onCurrentError])

  return (
    <MediaElement
      image={image}
      className={className}
      style={isCurrent ? undefined : RETAINED_SLOT_STYLE}
      draggable={false}
      onLoad={() => {
        setSettled({ url: image.url, status: 'loaded' })
        onSlotLoaded(image.pageNum)
      }}
      onError={() => setSettled({ url: image.url, status: 'error' })}
      onToggleOverlay={onToggleOverlay}
      overlayVisible={overlayVisible}
    />
  )
}
