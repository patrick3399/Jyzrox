'use client'

import { useState, useCallback } from 'react'
import { usePathname } from 'next/navigation'
import { Sidebar } from './Sidebar'
import { MobileNav } from './MobileNav'
import { BottomTabBar } from './BottomTabBar'
import { Toaster } from 'sonner'
import { SWUpdatePrompt } from './SWUpdatePrompt'
import { FloatingActions } from './FloatingActions'
import { WsProvider } from '@/lib/ws'
import { useSwipeBack } from '@/hooks/useSwipeBack'
import { useDownloadStats } from '@/hooks/useDownloadQueue'

const AUTH_PATHS = ['/login', '/setup']

export function LayoutShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const isAuth = AUTH_PATHS.includes(pathname)
  const isReader = pathname.startsWith('/reader/')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const handleDrawerClose = useCallback(() => setDrawerOpen(false), [])
  const handleDrawerOpen = useCallback(() => setDrawerOpen(true), [])

  useSwipeBack({ enabled: !isReader && !isAuth })

  if (isAuth) {
    return (
      <>
        {children}
        <Toaster position="bottom-right" theme="dark" richColors />
        <SWUpdatePrompt />
      </>
    )
  }

  return (
    <WsProvider>
      <LayoutShellInner
        isReader={isReader}
        drawerOpen={drawerOpen}
        onDrawerClose={handleDrawerClose}
        onDrawerOpen={handleDrawerOpen}
      >
        {children}
      </LayoutShellInner>
    </WsProvider>
  )
}

/** Inner component lives inside WsProvider so it can call useDownloadStats */
function LayoutShellInner({
  children,
  isReader,
  drawerOpen,
  onDrawerClose,
  onDrawerOpen,
}: {
  children: React.ReactNode
  isReader: boolean
  drawerOpen: boolean
  onDrawerClose: () => void
  onDrawerOpen: () => void
}) {
  const { data: downloadStats } = useDownloadStats()

  return (
    <>
      {/* Desktop sidebar — hidden on mobile */}
      <Sidebar downloadStats={downloadStats} />

      {/* Mobile drawer nav — controlled by BottomTabBar More button */}
      <MobileNav open={drawerOpen} onClose={onDrawerClose} downloadStats={downloadStats} />

      {/* Mobile bottom tab bar — hidden on desktop, skip on reader pages */}
      {!isReader && <BottomTabBar onMoreClick={onDrawerOpen} downloadStats={downloadStats} />}

      {/* Main content */}
      <main className="lg:pl-56 pb-[calc(4rem+var(--sab))] lg:pb-0 min-h-screen bg-vault-bg text-vault-text">
        <div className="px-4 lg:px-6 xl:px-8 py-6 pt-[calc(1.5rem+var(--sat)/2)] lg:pt-6">
          {children}
        </div>
      </main>

      <Toaster position="bottom-right" richColors />
      <SWUpdatePrompt />
      {!isReader && <FloatingActions />}
    </>
  )
}
