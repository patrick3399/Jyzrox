'use client'

import { useEffect, useState, type ImgHTMLAttributes, type ReactNode } from 'react'

type AppImageProps = Omit<ImgHTMLAttributes<HTMLImageElement>, 'src' | 'alt'> & {
  src?: string | null
  alt: string
  fallback?: ReactNode
  fallbackClassName?: string
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

  return (
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
}
