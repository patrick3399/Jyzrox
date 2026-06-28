'use client'

import { useEffect } from 'react'
import { usePathname, useSearchParams } from 'next/navigation'
import { rememberLocation } from '@/lib/navMemory'
import { ALL_TABS } from './BottomTabBar'

const TAB_ROOTS: string[] = ALL_TABS.map((tab) => tab.href).filter((href) => href !== '/')

/**
 * Records the current full URL against its owning bottom-tab root on every
 * navigation, so the tab bar can return the user to where they left off.
 * Renders nothing; must be mounted inside a <Suspense> boundary because it
 * reads useSearchParams.
 */
export function NavMemoryTracker() {
  const pathname = usePathname()
  const searchParams = useSearchParams()

  useEffect(() => {
    rememberLocation(TAB_ROOTS, pathname, searchParams.toString())
  }, [pathname, searchParams])

  return null
}
