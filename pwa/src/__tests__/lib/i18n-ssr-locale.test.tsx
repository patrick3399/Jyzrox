// @vitest-environment node
/**
 * Server HTML must already be in the request's language, and concurrent renders
 * in one Node process must not read each other's locale.
 */

import { Suspense, use } from 'react'
import { renderToPipeableStream } from 'react-dom/server'
import { PassThrough } from 'node:stream'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/i18n/initialDictionaries', async () => ({
  initialDictionaries: {
    en: (await import('@/lib/i18n/en')).default,
    'zh-TW': (await import('@/lib/i18n/zh-TW')).default,
    ja: (await import('@/lib/i18n/ja')).default,
  },
}))
vi.mock('@/lib/api', () => ({ api: { auth: { updateProfile: vi.fn() } } }))
vi.mock('@/hooks/useProfile', () => ({ useProfile: () => ({ data: undefined }) }))

import { LocaleProvider } from '@/components/LocaleProvider'
import { t, type Locale } from '@/lib/i18n'
import en from '@/lib/i18n/en'
import ja from '@/lib/i18n/ja'
import zhTW from '@/lib/i18n/zh-TW'

const KEY = 'nav.dashboard'

function renderHtml(locale: Locale, children: React.ReactNode): Promise<string> {
  return new Promise((resolve, reject) => {
    const sink = new PassThrough()
    let html = ''
    sink.on('data', (chunk) => (html += chunk.toString()))
    sink.on('end', () => resolve(html))
    const { pipe } = renderToPipeableStream(
      <LocaleProvider initialLocale={locale}>{children}</LocaleProvider>,
      { onAllReady: () => pipe(sink), onError: reject },
    )
  })
}

function SuspendedLabel({ gate }: { gate: Promise<void> }) {
  use(gate)
  return <span>{t(KEY)}</span>
}

describe('server render locale', () => {
  it('renders the request locale in the server HTML, not the English fallback', async () => {
    const html = await renderHtml('zh-TW', <span>{t(KEY)}</span>)
    // `t(KEY)` above runs outside the render: it must not pick up the locale.
    expect(html).toContain(en[KEY])

    function Label() {
      return <span>{t(KEY)}</span>
    }
    const rendered = await renderHtml('zh-TW', <Label />)
    expect(rendered).toContain(zhTW[KEY])
    expect(rendered).not.toContain(en[KEY])
  })

  it('keeps each locale when two suspended renders interleave', async () => {
    let releaseZh = () => {}
    let releaseJa = () => {}
    const zhGate = new Promise<void>((resolve) => (releaseZh = resolve))
    const jaGate = new Promise<void>((resolve) => (releaseJa = resolve))

    const zhRender = renderHtml(
      'zh-TW',
      <Suspense fallback={null}>
        <SuspendedLabel gate={zhGate} />
      </Suspense>,
    )
    const jaRender = renderHtml(
      'ja',
      <Suspense fallback={null}>
        <SuspendedLabel gate={jaGate} />
      </Suspense>,
    )
    // The zh-TW task resumes after the ja render has started and finished.
    releaseJa()
    const jaHtml = await jaRender
    releaseZh()
    const zhHtml = await zhRender

    expect(zhHtml).toContain(zhTW[KEY])
    expect(jaHtml).toContain(ja[KEY])
  })
})
