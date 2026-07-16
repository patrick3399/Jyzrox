import type { Metadata, Viewport } from 'next'
import { headers } from 'next/headers'
import Script from 'next/script'
import { ThemeProvider } from '@/components/ThemeProvider'
import { LocaleProvider } from '@/components/LocaleProvider'
import { LayoutShell } from '@/components/LayoutShell'
import { ErrorBoundary } from '@/components/ErrorBoundary'
import { resolveLocale } from '@/lib/i18n'
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
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
}

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const initialLocale = resolveLocale((await headers()).get('accept-language'))
  return (
    <html lang={initialLocale} suppressHydrationWarning>
      <head>
        <link rel="icon" href="/favicon.ico" sizes="any" />
        <link rel="icon" href="/favicon-32x32.png" type="image/png" sizes="32x32" />
        <link rel="icon" href="/favicon-16x16.png" type="image/png" sizes="16x16" />
        <link rel="apple-touch-icon" href="/apple-touch-icon.png" />
        <link rel="manifest" href="/manifest.json" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
        {/* Apply theme overrides (accent + custom palette) before first paint.
            Keep in sync with lib/themeOverrides.ts. */}
        <script
          dangerouslySetInnerHTML={{
            __html: `(function(){try{
var ok=function(x){return typeof x==='string'&&/^#[0-9a-fA-F]{6}$/.test(x)};
var a=localStorage.getItem('vault-accent');
if(ok(a))document.documentElement.style.setProperty('--color-accent',a);
var fs=Number(localStorage.getItem('vault_font_scale'));
if(Number.isFinite(fs)&&fs>=0.8&&fs<=1.3)document.documentElement.style.fontSize=(fs*100)+'%';
var raw=localStorage.getItem('vault-custom-theme');
if(raw){var p=JSON.parse(raw);
if(p&&ok(p.bg)&&ok(p.card)&&ok(p.text)){
var s=document.createElement('style');s.id='vault-custom-theme-style';
s.textContent='.custom{--color-bg:'+p.bg+';--color-card:'+p.card+';--color-card-hover:color-mix(in srgb, '+p.card+' 92%, '+p.text+');--color-border:color-mix(in srgb, '+p.bg+' 86%, '+p.text+');--color-border-hover:color-mix(in srgb, '+p.bg+' 72%, '+p.text+');--color-text:'+p.text+';--color-text-secondary:color-mix(in srgb, '+p.text+' 70%, '+p.bg+');--color-text-muted:color-mix(in srgb, '+p.text+' 55%, '+p.bg+');--color-input:'+p.card+';}';
document.head.appendChild(s);}}
}catch(e){}})();`,
          }}
        />
      </head>
      <body className="bg-vault-bg text-vault-text min-h-screen">
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
        <ThemeProvider>
          <LocaleProvider initialLocale={initialLocale}>
            <LayoutShell>
              <ErrorBoundary>{children}</ErrorBoundary>
            </LayoutShell>
          </LocaleProvider>
        </ThemeProvider>
      </body>
    </html>
  )
}
