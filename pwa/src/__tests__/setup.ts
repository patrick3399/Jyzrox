import { expect, afterEach, vi } from 'vitest'
import { cleanup } from '@testing-library/react'
import * as matchers from '@testing-library/jest-dom/matchers'

expect.extend(matchers)

// The browser build starts with no dictionary until LocaleProvider loads one.
// Tests render without that provider and assert on the English strings.
vi.mock('@/lib/i18n/initialDictionaries', async () => ({
  initialDictionaries: { en: (await import('@/lib/i18n/en')).default },
}))

afterEach(() => {
  cleanup()
})
