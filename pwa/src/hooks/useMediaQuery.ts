'use client'

import { useCallback, useSyncExternalStore } from 'react'

/** Tailwind `lg` breakpoint (64rem): the sidebar layout. */
export const DESKTOP_MEDIA_QUERY = '(min-width: 64rem)'

function hasMatchMedia(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
}

/**
 * Live `matchMedia` result. False on the server and where `matchMedia` is
 * missing, so pair it with a CSS breakpoint when the first paint must match.
 */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      if (!hasMatchMedia()) return () => {}
      const media = window.matchMedia(query)
      media.addEventListener('change', onChange)
      return () => media.removeEventListener('change', onChange)
    },
    [query],
  )
  return useSyncExternalStore(
    subscribe,
    () => hasMatchMedia() && window.matchMedia(query).matches,
    () => false,
  )
}
