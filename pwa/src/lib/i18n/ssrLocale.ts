import { createContext } from 'react'
import type { Locale } from './locales'

/** The locale of the server render in progress; unused in the browser. */
export const SsrLocaleContext = createContext<Locale | null>(null)
