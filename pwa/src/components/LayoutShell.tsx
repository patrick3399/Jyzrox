'use client'

import { useState, useCallback } from 'react'
import { usePathname } from 'next/navigation'
import { Sidebar } from './Sidebar'
import { MobileNav } from './MobileNav'
import { BottomTabBar } from './BottomTabBar'
import { Toaster } from 'sonner'
import { SWUpdatePrompt } from './SWUpdatePrompt'
import { WsProvider } from '@/lib/ws'
import { useSwipeBack } from '@/hooks/useSwipeBack'

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
      {/* Desktop sidebar — hidden on mobile */}
      <Sidebar />

      {/* Mobile drawer nav — controlled by BottomTabBar More button */}
      <MobileNav open={drawerOpen} onClose={handleDrawerClose} />

      {/* Mobile bottom tab bar — hidden on desktop */}
      <BottomTabBar onMoreClick={handleDrawerOpen} />

      {/* Main content */}
      <main className="lg:pl-56 pb-[calc(4rem+var(--sab))] lg:pb-0 min-h-screen bg-vault-bg text-vault-text">
        <div className="px-4 lg:px-6 xl:px-8 py-6 pt-[calc(1.5rem+var(--sat))] lg:pt-6">
          {children}
        </div>
      </main>

      <Toaster position="bottom-right" richColors />
      <SWUpdatePrompt />
    </WsProvider>
  )
}
