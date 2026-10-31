'use client'

import {
  createContext,
  Suspense,
  use,
  useContext,
  useState,
  useEffect,
  useCallback,
  useRef,
} from 'react'
import {
  detectBrowserLocale,
  getLocale,
  loadLocale,
  LOCALE_COOKIE,
  prepareInitialLocale,
  setLocale as setI18nLocale,
  SUPPORTED_LOCALES,
  type Locale,
} from '@/lib/i18n'
import { SsrLocaleContext } from '@/lib/i18n/ssrLocale'
import { api } from '@/lib/api'
import { useProfile } from '@/hooks/useProfile'

type LocaleContextType = {
  locale: Locale
  setLocale: (locale: Locale | null) => void
  isAutomatic: boolean
  /**
   * Bumped when a lazily-loaded dictionary becomes active after the state locale
   * changed. It MUST stay in the context value: React Compiler memoizes the value
   * object on its fields, so without a changing field the post-load re-render is
   * elided and every useLocale() consumer keeps rendering the previous strings.
   * LayoutShell remounts the app on this value, so it must not change on a plain
   * page load.
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

function persistLocaleOverride(locale: Locale | null) {
  if (locale) {
    localStorage.setItem(OVERRIDE_STORAGE_KEY, locale)
    document.cookie = `${LOCALE_COOKIE}=${locale}; Path=/; Max-Age=31536000; SameSite=Lax`
  } else {
    localStorage.removeItem(OVERRIDE_STORAGE_KEY)
    document.cookie = `${LOCALE_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax`
  }
}

/** English is itself lazy; if it cannot load either, the active dictionary stays. */
function fallBackToEnglish(setLocaleState: (locale: Locale) => void) {
  void loadLocale('en')
    .then(() => {
      setI18nLocale('en')
      setLocaleState('en')
    })
    .catch(() => {})
}

export function LocaleProvider({
  children,
  initialLocale,
}: {
  children: React.ReactNode
  initialLocale?: Locale
}) {
  const [seedLocale] = useState<Locale>(() => initialLocale ?? detectLocale())
  // While the dictionary loads, this boundary keeps the server HTML in place and
  // hydrates afterwards. Nothing above it may hold locale state: an update reaching
  // a boundary that is still waiting would discard that HTML for the empty fallback.
  return (
    <SsrLocaleContext value={seedLocale}>
      <Suspense fallback={null}>
        <LocaleStateProvider seedLocale={seedLocale}>{children}</LocaleStateProvider>
      </Suspense>
    </SsrLocaleContext>
  )
}

function LocaleStateProvider({
  children,
  seedLocale,
}: {
  children: React.ReactNode
  seedLocale: Locale
}) {
  const preparing = prepareInitialLocale(seedLocale)
  if (preparing) use(preparing)

  const [locale, setLocaleState] = useState<Locale>(seedLocale)
  const [isAutomatic, setIsAutomatic] = useState(true)
  const [dictionaryVersion, setDictionaryVersion] = useState(0)
  const { data: profile } = useProfile()
  const profileSyncedRef = useRef(false)

  // The server seeds the locale from the cookie or Accept-Language. Reconcile
  // that seed with the browser-side override immediately after hydration so a
  // hard refresh still honours a saved manual choice even when the profile
  // request is slow or unavailable, and refresh the cookie for the next server
  // render. A profile that has already arrived remains the authority for
  // cross-device sync.
  useEffect(() => {
    const override = localStorage.getItem(OVERRIDE_STORAGE_KEY)
    const hasValidOverride = override !== null && SUPPORTED_LOCALES.includes(override as Locale)
    persistLocaleOverride(hasValidOverride ? (override as Locale) : null)
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
        fallBackToEnglish(setLocaleState)
      })
  }, [])

  useEffect(() => {
    let active = true
    void loadLocale(locale)
      .then(() => {
        if (!active || getLocale() === locale) return
        setI18nLocale(locale)
        setDictionaryVersion((version) => version + 1)
      })
      .catch(() => {
        if (!active) return
        fallBackToEnglish(setLocaleState)
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
      .catch(() => fallBackToEnglish(setLocaleState))
    setIsAutomatic(automatic)
    persistLocaleOverride(newLocale)
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
        .catch(() => fallBackToEnglish(setLocaleState))
      setIsAutomatic(false)
      persistLocaleOverride(serverLocale)
    } else {
      const automaticLocale = detectBrowserLocale()
      void loadLocale(automaticLocale)
        .then(() => {
          setI18nLocale(automaticLocale)
          setLocaleState(automaticLocale)
        })
        .catch(() => fallBackToEnglish(setLocaleState))
      setIsAutomatic(true)
      persistLocaleOverride(null)
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
