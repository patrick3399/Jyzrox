'use client'

import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import {
  detectBrowserLocale,
  setLocale as setI18nLocale,
  SUPPORTED_LOCALES,
  type Locale,
} from '@/lib/i18n'
import { api } from '@/lib/api'

type LocaleContextType = {
  locale: Locale
  setLocale: (locale: Locale | null) => void
  isAutomatic: boolean
}

const LocaleContext = createContext<LocaleContextType | undefined>(undefined)

const OVERRIDE_STORAGE_KEY = 'jyzrox-locale-override'

function detectLocale(): Locale {
  if (typeof window === 'undefined') return 'en'
  const override = localStorage.getItem(OVERRIDE_STORAGE_KEY)
  if (override && SUPPORTED_LOCALES.includes(override as Locale)) return override as Locale
  return detectBrowserLocale()
}

export function LocaleProvider({ children, initialLocale }: { children: React.ReactNode; initialLocale?: Locale }) {
  const [locale, setLocaleState] = useState<Locale>(() => initialLocale ?? detectLocale())
  const [isAutomatic, setIsAutomatic] = useState(true)

  useEffect(() => {
    setI18nLocale(locale)
  }, [locale])

  const setLocale = useCallback((newLocale: Locale | null) => {
    const automatic = newLocale === null
    const nextLocale = newLocale ?? detectBrowserLocale()
    setI18nLocale(nextLocale)
    setLocaleState(nextLocale)
    setIsAutomatic(automatic)
    if (automatic) localStorage.removeItem(OVERRIDE_STORAGE_KEY)
    else localStorage.setItem(OVERRIDE_STORAGE_KEY, newLocale)
    // Save to server (fire-and-forget)
    api.auth.updateProfile({ locale: newLocale }).catch(() => {})
  }, [])

  // On mount: sync locale from server profile (server wins for cross-device sync)
  useEffect(() => {
    api.auth
      .getProfile()
      .then((profile) => {
        if (profile.locale && SUPPORTED_LOCALES.includes(profile.locale as Locale)) {
          const serverLocale = profile.locale as Locale
          if (serverLocale !== locale) {
            setI18nLocale(serverLocale)
            setLocaleState(serverLocale)
          }
          setIsAutomatic(false)
          localStorage.setItem(OVERRIDE_STORAGE_KEY, serverLocale)
        } else {
          const automaticLocale = detectBrowserLocale()
          setI18nLocale(automaticLocale)
          setLocaleState(automaticLocale)
          setIsAutomatic(true)
          localStorage.removeItem(OVERRIDE_STORAGE_KEY)
        }
      })
      .catch(() => {}) // Not logged in or network error — use localStorage fallback
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    document.documentElement.lang = locale
  }, [locale])

  return <LocaleContext value={{ locale, setLocale, isAutomatic }}>{children}</LocaleContext>
}

export function useLocale() {
  const ctx = useContext(LocaleContext)
  if (!ctx) throw new Error('useLocale must be used within LocaleProvider')
  return ctx
}
