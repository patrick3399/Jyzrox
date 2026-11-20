'use client'
import type { ReaderImage } from './types'
import { t } from '@/lib/i18n'
import VideoPlayer from './VideoPlayer'
import { ReaderImg } from './ReaderImg'

export function MediaElement({
  image,
  className,
  style,
  draggable = false,
  loading,
  dataPage,
  innerRef,
  onLoad,
  onError,
  onToggleOverlay,
  overlayVisible,
}: {
  image: ReaderImage
  className?: string
  style?: React.CSSProperties
  draggable?: boolean
  loading?: 'lazy' | 'eager'
  dataPage?: number
  innerRef?: React.Ref<HTMLImageElement | HTMLVideoElement>
  onLoad?: () => void
  onError?: () => void
  onToggleOverlay?: () => void
  overlayVisible?: boolean
}) {
  if (!image.url) {
    return (
      <div
        className={`flex items-center justify-center bg-black/50 ${className ?? ''}`}
        style={{ minHeight: '200px', minWidth: '200px', ...style }}
      >
        <div className="text-center text-white/50">
          <div className="mx-auto mb-2 h-6 w-6 animate-spin rounded-full border-2 border-white/20 border-t-white/60" />
          <p className="text-xs">{t('reader.downloading')}</p>
        </div>
      </div>
    )
  }

  if (image.mediaType === 'video') {
    // VideoPlayer must fill its parent entirely so that the controls overlay anchors
    // to the viewport bottom, not to the middle of a shrink-wrapped box.
    // The image scale class (pointer-events-none, max-h-full, …) is designed for
    // <img> elements and must NOT be forwarded to VideoPlayer.
    return (
      <VideoPlayer
        image={image}
        className="w-full h-full"
        style={style}
        innerRef={innerRef as React.Ref<HTMLVideoElement>}
        onLoad={onLoad}
        onToggleOverlay={onToggleOverlay}
        overlayVisible={overlayVisible}
      />
    )
  }

  return (
    <ReaderImg
      image={image}
      className={className}
      style={style}
      draggable={draggable}
      loading={loading}
      dataPage={dataPage}
      innerRef={innerRef as React.Ref<HTMLImageElement>}
      onLoad={onLoad}
      onError={onError}
    />
  )
}
