'use client'

import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { setLocale as setI18nLocale, SUPPORTED_LOCALES, type Locale } from '@/lib/i18n'
import { api } from '@/lib/api'

type LocaleContextType = {
  locale: Locale
  setLocale: (locale: Locale) => void
}

const LocaleContext = createContext<LocaleContextType | undefined>(undefined)

const STORAGE_KEY = 'jyzrox-locale'

function detectLocale(): Locale {
  if (typeof window === 'undefined') return 'en'
  const stored = localStorage.getItem(STORAGE_KEY)
  if (stored && SUPPORTED_LOCALES.includes(stored as Locale)) return stored as Locale
  return 'en'
}

export function LocaleProvider({ children }: { children: React.ReactNode }) {
  const [locale, setLocaleState] = useState<Locale>(() => {
    const detected = detectLocale()
    setI18nLocale(detected)
    return detected
  })

  const setLocale = useCallback((newLocale: Locale) => {
    setI18nLocale(newLocale)
    setLocaleState(newLocale)
    // Save to server (fire-and-forget)
    api.auth.updateProfile({ locale: newLocale }).catch(() => {})
  }, [])

  // On mount: sync locale from server profile (server wins for cross-device sync)
  useEffect(() => {
    api.auth.getProfile()
      .then((profile) => {
        if (profile.locale && SUPPORTED_LOCALES.includes(profile.locale as Locale)) {
          const serverLocale = profile.locale as Locale
          if (serverLocale !== locale) {
            setI18nLocale(serverLocale)
            setLocaleState(serverLocale)
          }
        }
      })
      .catch(() => {}) // Not logged in or network error — use localStorage fallback
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    document.documentElement.lang = locale
    localStorage.setItem(STORAGE_KEY, locale)
  }, [locale])

  return (
    <LocaleContext.Provider value={{ locale, setLocale }}>
      {children}
    </LocaleContext.Provider>
  )
}

export function useLocale() {
  const ctx = useContext(LocaleContext)
  if (!ctx) throw new Error('useLocale must be used within LocaleProvider')
  return ctx
}
