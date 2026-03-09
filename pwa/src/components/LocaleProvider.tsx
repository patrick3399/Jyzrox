'use client'

import { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { setLocale as setI18nLocale, getLocale, SUPPORTED_LOCALES, type Locale } from '@/lib/i18n'

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
  const lang = navigator.language || ''
  return lang.startsWith('zh') ? 'zh-TW' : 'en'
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
  }, [])

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
