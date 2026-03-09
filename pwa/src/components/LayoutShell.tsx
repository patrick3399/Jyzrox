'use client'

import { usePathname } from 'next/navigation'
import { Sidebar } from './Sidebar'
import { MobileNav } from './MobileNav'
import { Toaster } from 'sonner'
import { SWUpdatePrompt } from './SWUpdatePrompt'

const AUTH_PATHS = ['/login', '/setup']

export function LayoutShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const isAuth = AUTH_PATHS.includes(pathname)

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
    <>
      {/* Desktop sidebar — hidden on mobile */}
      <Sidebar />

      {/* Mobile top nav — hidden on desktop */}
      <MobileNav />

      {/* Main content — safe-main-pt handles iOS safe area on mobile, reset on desktop */}
      <main className="safe-main-pt lg:pl-56 min-h-screen bg-vault-bg text-vault-text">
        {children}
      </main>

      <Toaster position="bottom-right" richColors />
      <SWUpdatePrompt />
    </>
  )
}
