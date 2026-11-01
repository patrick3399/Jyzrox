'use client'

import { useEffect, useRef } from 'react'
import { usePathname, useSearchParams } from 'next/navigation'
import { isTabRestoreTarget, releaseTabRestore, rememberLocation } from '@/lib/navMemory'
import { ALL_TABS } from './BottomTabBar'

const TAB_ROOTS: string[] = ALL_TABS.map((tab) => tab.href).filter((href) => href !== '/')

/**
 * Records the current full URL against its owning bottom-tab root on every
 * navigation, so the tab bar can return the user to where they left off.
 * Also disarms the tab-restore flag once the user moves off the restored page:
 * only smartBack consumes it, so any other way out would leave it armed for a
 * later, ordinary arrival at the same URL. Renders nothing; must be mounted
 * inside a <Suspense> boundary because it reads useSearchParams.
 */
export function NavMemoryTracker() {
  const pathname = usePathname()
  const searchParams = useSearchParams()
  // The flagged URL this tracker has seen commit. The flag is set in a click
  // handler before the navigation commits, so a URL that merely differs from the
  // flag is not proof the user left — only leaving a URL we arrived at is.
  const restoredUrlRef = useRef<string | null>(null)

  useEffect(() => {
    const search = searchParams.toString()
    rememberLocation(TAB_ROOTS, pathname, search)

    const url = search ? `${pathname}?${search}` : pathname
    const left = restoredUrlRef.current
    if (left !== null && left !== url) {
      releaseTabRestore(left)
      restoredUrlRef.current = null
    }
    if (isTabRestoreTarget(url)) restoredUrlRef.current = url
  }, [pathname, searchParams])

  return null
}
