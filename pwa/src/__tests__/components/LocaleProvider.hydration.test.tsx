/**
 * Hydration must keep the server's translated HTML: it waits for the dictionary
 * instead of rendering English over it, and never remounts the app on load.
 */

import { act, waitFor } from '@testing-library/react'
import { useEffect } from 'react'
import { hydrateRoot } from 'react-dom/client'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/api', () => ({ api: { auth: { updateProfile: vi.fn() } } }))
vi.mock('@/hooks/useProfile', () => ({ useProfile: () => ({ data: undefined }) }))

import { LocaleProvider, useLocale } from '@/components/LocaleProvider'
import { t } from '@/lib/i18n'
import zhTW from '@/lib/i18n/zh-TW'

const KEY = 'nav.dashboard'
let mountCount = 0

function Label() {
  return <span>{t(KEY)}</span>
}

function KeyedShell({ children }: { children: React.ReactNode }) {
  const { locale, dictionaryVersion } = useLocale()
  return <Counted key={`${locale}:${dictionaryVersion}`}>{children}</Counted>
}

function Counted({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    mountCount += 1
  }, [])
  return <div>{children}</div>
}

describe('LocaleProvider hydration', () => {
  it('hydrates translated server HTML without a mismatch or a remount', async () => {
    Object.defineProperty(navigator, 'languages', { value: ['zh-TW'], configurable: true })
    const container = document.createElement('div')
    container.innerHTML = `<!--$--><div><span>${zhTW[KEY]}</span></div><!--/$-->`
    document.body.appendChild(container)
    const serverSpan = container.querySelector('span')
    const onRecoverableError = vi.fn()

    await act(async () => {
      hydrateRoot(
        container,
        <LocaleProvider initialLocale="zh-TW">
          <KeyedShell>
            <Label />
          </KeyedShell>
        </LocaleProvider>,
        { onRecoverableError },
      )
    })

    await waitFor(() => expect(mountCount).toBeGreaterThan(0))
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0))
    })

    expect(onRecoverableError).not.toHaveBeenCalled()
    expect(container.querySelector('span')).toBe(serverSpan)
    expect(serverSpan).toHaveTextContent(zhTW[KEY])
    expect(mountCount).toBe(1)
  })
})
