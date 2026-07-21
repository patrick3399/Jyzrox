'use client'

import { useEffect, useLayoutEffect, useRef, useState, type ImgHTMLAttributes, type ReactNode } from 'react'

type AppImageProps = Omit<ImgHTMLAttributes<HTMLImageElement>, 'src' | 'alt'> & {
  src?: string | null
  alt: string
  fallback?: ReactNode
  fallbackClassName?: string
}

const RESPONSIVE_WIDTHS = [320, 640, 960]
const THUMBNAIL_WIDTHS = [160, 360, 720]
const THUMBNAIL_FILENAME_RE = /\/thumb_(?:160|360|720)\.webp(?:\?.*)?$/

// imgproxy's plain source form (`/plain/local:///path`) contains the `local:///`
// triple slash, which nginx (merge_slashes on, the default) collapses to
// `local:/` and 308-redirects — breaking imgproxy's source resolution. Encoding
// the source as URL-safe base64 removes every slash from the source segment, so
// the request survives nginx untouched.
function encodeImgproxySource(source: string): string {
  return btoa(source).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function imgproxyUrl(src: string, width: number, format: 'avif' | 'webp'): string | null {
  // Only full-size originals under /media/cas/ are worth routing through
  // imgproxy: they are large enough that on-the-fly AVIF/WebP + downscaling pays
  // for itself. /media/thumbs/ is deliberately excluded — those are already
  // pre-generated 160px WebP thumbnails, so transcoding them buys negligible
  // bytes while adding a cold-cache AVIF encode and an extra /media/image auth
  // subrequest per tile. That overhead is exactly what made the library grid
  // slower than serving the static thumb directly.
  if (!src.startsWith('/media/cas/')) return null
  const localPath = src.slice('/media/'.length)
  const source = encodeImgproxySource(`local:///${localPath}`)
  return `/media/image/insecure/rs:fit:${width}:0:0/${source}.${format}`
}

export function responsiveImageSrcSet(src: string, format: 'avif' | 'webp'): string | undefined {
  const variants = RESPONSIVE_WIDTHS.map((width) => {
    const url = imgproxyUrl(src, width, format)
    return url ? `${url} ${width}w` : null
  }).filter(Boolean)
  return variants.length ? variants.join(', ') : undefined
}

export function thumbnailImageSrcSet(src: string): string | undefined {
  if (!src.startsWith('/media/thumbs/') || !THUMBNAIL_FILENAME_RE.test(src)) return undefined
  return THUMBNAIL_WIDTHS.map(
    (width) => `${src.replace(THUMBNAIL_FILENAME_RE, `/thumb_${width}.webp`)} ${width}w`,
  ).join(', ')
}

export function AppImage({
  src,
  alt,
  fallback,
  fallbackClassName,
  className,
  onError,
  onLoad,
  ...props
}: AppImageProps) {
  const [failed, setFailed] = useState(false)
  const [optimizedFailed, setOptimizedFailed] = useState(false)
  const [measuredWidth, setMeasuredWidth] = useState<number | null>(null)
  const imageRef = useRef<HTMLImageElement>(null)

  useEffect(() => {
    setFailed(false)
    setOptimizedFailed(false)
    setMeasuredWidth(null)
  }, [src])

  useLayoutEffect(() => {
    const image = imageRef.current
    if (!image || typeof ResizeObserver === 'undefined') return
    const updateWidth = () => {
      const width = Math.ceil(image.getBoundingClientRect().width)
      if (width > 0) setMeasuredWidth((current) => (current === width ? current : width))
    }
    updateWidth()
    const observer = new ResizeObserver(updateWidth)
    observer.observe(image)
    return () => observer.disconnect()
  }, [src, failed, optimizedFailed])

  if (!src || failed) {
    return (
      <div
        className={fallbackClassName ?? className}
        role={alt ? 'img' : undefined}
        aria-label={alt || undefined}
        aria-hidden={alt ? undefined : true}
      >
        {fallback}
      </div>
    )
  }

  const avifSrcSet = responsiveImageSrcSet(src, 'avif')
  const webpSrcSet = responsiveImageSrcSet(src, 'webp')
  const thumbnailSrcSet = thumbnailImageSrcSet(src)
  const hasPictureSources = Boolean(avifSrcSet || webpSrcSet)
  const hasOptimizedSources = Boolean(hasPictureSources || thumbnailSrcSet)
  const responsiveSizes =
    props.sizes ??
    (measuredWidth ? `${measuredWidth}px` : props.loading === 'lazy' ? 'auto, 200px' : '200px')
  const image = (
    <img
      {...props}
      ref={imageRef}
      src={src}
      srcSet={!optimizedFailed ? (props.srcSet ?? thumbnailSrcSet) : undefined}
      sizes={props.sizes ?? (thumbnailSrcSet ? responsiveSizes : undefined)}
      alt={alt}
      className={className}
      decoding={props.decoding ?? 'async'}
      onLoad={(event) => {
        if (thumbnailSrcSet && !props.sizes) {
          const width = Math.ceil(event.currentTarget.getBoundingClientRect().width)
          if (width > 0) setMeasuredWidth((current) => (current === width ? current : width))
        }
        onLoad?.(event)
      }}
      onError={(event) => {
        if (hasOptimizedSources && !optimizedFailed) {
          setOptimizedFailed(true)
          return
        }
        setFailed(true)
        onError?.(event)
      }}
    />
  )

  if (!hasPictureSources || optimizedFailed) return image

  return (
    <picture>
      {avifSrcSet && (
        <source type="image/avif" srcSet={avifSrcSet} sizes={props.sizes ?? '100vw'} />
      )}
      {webpSrcSet && (
        <source type="image/webp" srcSet={webpSrcSet} sizes={props.sizes ?? '100vw'} />
      )}
      {image}
    </picture>
  )
}
