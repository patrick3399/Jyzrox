import type { Metadata, Viewport } from 'next'
import Link from 'next/link'
import Script from 'next/script'
import './globals.css'

export const metadata: Metadata = {
  title: 'Doujin Vault',
  description: 'Personal doujin gallery manager',
  appleWebApp: {
    capable: true,
    statusBarStyle: 'black-translucent',
  },
}

export const viewport: Viewport = {
  themeColor: '#6366f1',
}

const navLinks = [
  { href: '/', label: 'Dashboard' },
  { href: '/browse', label: 'Browse' },
  { href: '/library', label: 'Library' },
  { href: '/queue', label: 'Queue' },
  { href: '/tags', label: 'Tags' },
  { href: '/settings', label: 'Settings' },
]

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="zh-TW" className="dark">
      <head>
        <link rel="manifest" href="/manifest.json" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
      </head>
      <body className="bg-vault-bg text-neutral-200 min-h-screen">
        <Script
          id="sw-register"
          strategy="afterInteractive"
          dangerouslySetInnerHTML={{
            __html: `
              if ('serviceWorker' in navigator) {
                window.addEventListener('load', function() {
                  navigator.serviceWorker.register('/sw.js').catch(function(err) {
                    console.warn('SW registration failed:', err);
                  });
                });
              }
            `,
          }}
        />
        <nav className="fixed top-0 left-0 right-0 z-50 bg-vault-card border-b border-vault-border h-14 flex items-center px-4">
          <span className="text-vault-accent font-bold text-lg tracking-wide mr-8">
            Vault
          </span>
          <div className="flex items-center gap-1 overflow-x-auto">
            {navLinks.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="px-3 py-1.5 rounded text-sm text-neutral-400 hover:text-neutral-100 hover:bg-white/5 transition-colors whitespace-nowrap"
              >
                {link.label}
              </Link>
            ))}
          </div>
        </nav>
        <main className="pt-14 min-h-screen bg-vault-bg">
          {children}
        </main>
      </body>
    </html>
  )
}
