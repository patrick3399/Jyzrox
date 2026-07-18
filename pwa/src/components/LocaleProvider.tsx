'use client'

import { createContext, useContext, useState, useEffect, useCallback, useRef } from 'react'
import {
  detectBrowserLocale,
  loadLocale,
  setLocale as setI18nLocale,
  SUPPORTED_LOCALES,
  type Locale,
} from '@/lib/i18n'
import { api } from '@/lib/api'
import { useProfile } from '@/hooks/useProfile'

type LocaleContextType = {
  locale: Locale
  setLocale: (locale: Locale | null) => void
  isAutomatic: boolean
  /**
   * Bumped whenever a lazily-loaded dictionary finishes loading. It MUST stay in
   * the context value: React Compiler memoizes the value object on its fields,
   * so without a changing field the post-load re-render is elided and every
   * useLocale() consumer keeps rendering the pre-load (English fallback) strings.
   */
  dictionaryVersion: number
}

const LocaleContext = createContext<LocaleContextType | undefined>(undefined)

const OVERRIDE_STORAGE_KEY = 'jyzrox-locale-override'

function detectLocale(): Locale {
  if (typeof window === 'undefined') return 'en'
  const override = localStorage.getItem(OVERRIDE_STORAGE_KEY)
  if (override && SUPPORTED_LOCALES.includes(override as Locale)) return override as Locale
  return detectBrowserLocale()
}

export function LocaleProvider({
  children,
  initialLocale,
}: {
  children: React.ReactNode
  initialLocale?: Locale
}) {
  const [locale, setLocaleState] = useState<Locale>(() => initialLocale ?? detectLocale())
  const [isAutomatic, setIsAutomatic] = useState(true)
  const [dictionaryVersion, setDictionaryVersion] = useState(0)
  const { data: profile } = useProfile()
  const profileSyncedRef = useRef(false)

  // The server can only seed the locale from Accept-Language. Reconcile that
  // seed with the browser-side override immediately after hydration so a hard
  // refresh still honours a saved manual choice even when the profile request
  // is slow or unavailable. A profile that has already arrived remains the
  // authority for cross-device sync.
  useEffect(() => {
    const override = localStorage.getItem(OVERRIDE_STORAGE_KEY)
    const hasValidOverride = override !== null && SUPPORTED_LOCALES.includes(override as Locale)
    if (override !== null && !hasValidOverride) {
      localStorage.removeItem(OVERRIDE_STORAGE_KEY)
    }
    setIsAutomatic(!hasValidOverride)

    const detectedLocale = hasValidOverride ? (override as Locale) : detectBrowserLocale()
    void loadLocale(detectedLocale)
      .then(() => {
        if (profileSyncedRef.current) return
        setI18nLocale(detectedLocale)
        setLocaleState(detectedLocale)
      })
      .catch(() => {
        if (profileSyncedRef.current) return
        setI18nLocale('en')
        setLocaleState('en')
      })
  }, [])

  useEffect(() => {
    let active = true
    void loadLocale(locale)
      .then(() => {
        if (!active) return
        setI18nLocale(locale)
        setDictionaryVersion((version) => version + 1)
      })
      .catch(() => {
        if (!active) return
        setI18nLocale('en')
        setLocaleState('en')
      })
    return () => {
      active = false
    }
  }, [locale])

  const setLocale = useCallback((newLocale: Locale | null) => {
    const automatic = newLocale === null
    const nextLocale = newLocale ?? detectBrowserLocale()
    void loadLocale(nextLocale)
      .then(() => {
        setI18nLocale(nextLocale)
        setLocaleState(nextLocale)
      })
      .catch(() => {
        setI18nLocale('en')
        setLocaleState('en')
      })
    setIsAutomatic(automatic)
    if (automatic) localStorage.removeItem(OVERRIDE_STORAGE_KEY)
    else localStorage.setItem(OVERRIDE_STORAGE_KEY, newLocale)
    // Save to server (fire-and-forget)
    api.auth.updateProfile({ locale: newLocale }).catch(() => {})
  }, [])

  // Sync once from the shared profile request. Navigation and other consumers
  // use the same SWR key, so a hard navigation no longer fetches the profile twice.
  useEffect(() => {
    if (!profile || profileSyncedRef.current) return
    profileSyncedRef.current = true
    if (profile.locale && SUPPORTED_LOCALES.includes(profile.locale as Locale)) {
      const serverLocale = profile.locale as Locale
      void loadLocale(serverLocale)
        .then(() => {
          setI18nLocale(serverLocale)
          setLocaleState(serverLocale)
        })
        .catch(() => {
          setI18nLocale('en')
          setLocaleState('en')
        })
      setIsAutomatic(false)
      localStorage.setItem(OVERRIDE_STORAGE_KEY, serverLocale)
    } else {
      const automaticLocale = detectBrowserLocale()
      void loadLocale(automaticLocale)
        .then(() => {
          setI18nLocale(automaticLocale)
          setLocaleState(automaticLocale)
        })
        .catch(() => {
          setI18nLocale('en')
          setLocaleState('en')
        })
      setIsAutomatic(true)
      localStorage.removeItem(OVERRIDE_STORAGE_KEY)
    }
  }, [profile])

  useEffect(() => {
    document.documentElement.lang = locale
  }, [locale])

  return (
    <LocaleContext value={{ locale, setLocale, isAutomatic, dictionaryVersion }}>
      {children}
    </LocaleContext>
  )
}

export function useLocale() {
  const ctx = useContext(LocaleContext)
  if (!ctx) throw new Error('useLocale must be used within LocaleProvider')
  return ctx
}
