import type { Metadata, Viewport } from 'next'
import Script from 'next/script'
import { NavBar } from '@/components/NavBar'
import './globals.css'

export const metadata: Metadata = {
  title: 'Jyzrox',
  description: 'Personal gallery manager',
  appleWebApp: {
    capable: true,
    statusBarStyle: 'black-translucent',
  },
}

export const viewport: Viewport = {
  themeColor: '#6366f1',
}

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
        <NavBar />
        <main className="pt-14 min-h-screen bg-vault-bg">
          {children}
        </main>
      </body>
    </html>
  )
}
