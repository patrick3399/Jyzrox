'use client'

import { useEffect, useState, type ImgHTMLAttributes, type ReactNode } from 'react'

type AppImageProps = Omit<ImgHTMLAttributes<HTMLImageElement>, 'src' | 'alt'> & {
  src?: string | null
  alt: string
  fallback?: ReactNode
  fallbackClassName?: string
}

const RESPONSIVE_WIDTHS = [320, 640, 960]

// imgproxy's plain source form (`/plain/local:///path`) contains the `local:///`
// triple slash, which nginx (merge_slashes on, the default) collapses to
// `local:/` and 308-redirects — breaking imgproxy's source resolution. Encoding
// the source as URL-safe base64 removes every slash from the source segment, so
// the request survives nginx untouched.
function encodeImgproxySource(source: string): string {
  return btoa(source).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function imgproxyUrl(src: string, width: number, format: 'avif' | 'webp'): string | null {
  if (!src.startsWith('/media/cas/') && !src.startsWith('/media/thumbs/')) return null
  const localPath = src.slice('/media/'.length)
  const source = encodeImgproxySource(`local:///${localPath}`)
  return `/media/image/insecure/rs:fit:${width}:0:0/${source}.${format}`
}

export function responsiveImageSrcSet(
  src: string,
  format: 'avif' | 'webp',
): string | undefined {
  const variants = RESPONSIVE_WIDTHS.map((width) => {
    const url = imgproxyUrl(src, width, format)
    return url ? `${url} ${width}w` : null
  }).filter(Boolean)
  return variants.length ? variants.join(', ') : undefined
}

export function AppImage({
  src,
  alt,
  fallback,
  fallbackClassName,
  className,
  onError,
  ...props
}: AppImageProps) {
  const [failed, setFailed] = useState(false)

  useEffect(() => setFailed(false), [src])

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
  const image = (
    <img
      {...props}
      src={src}
      alt={alt}
      className={className}
      decoding={props.decoding ?? 'async'}
      onError={(event) => {
        setFailed(true)
        onError?.(event)
      }}
    />
  )

  if (!avifSrcSet || !webpSrcSet) return image

  return (
    <picture>
      <source type="image/avif" srcSet={avifSrcSet} sizes={props.sizes ?? '100vw'} />
      <source type="image/webp" srcSet={webpSrcSet} sizes={props.sizes ?? '100vw'} />
      {image}
    </picture>
  )
}
