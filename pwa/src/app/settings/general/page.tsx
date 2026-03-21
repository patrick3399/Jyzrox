'use client'

import { useState } from 'react'
import { useLocale } from '@/components/LocaleProvider'
import { BackButton } from '@/components/BackButton'
import { SUPPORTED_LOCALES, type Locale } from '@/lib/i18n'
import { t } from '@/lib/i18n'

function BrowseSettings() {
  const [historyEnabled, setHistoryEnabled] = useState(
    () =>
      typeof window !== 'undefined' &&
      localStorage.getItem('eh_search_history_enabled') !== 'false',
  )
  const [loadMode, setLoadMode] = useState(() =>
    typeof window !== 'undefined'
      ? localStorage.getItem('browse_load_mode') || 'pagination'
      : 'pagination',
  )
  const [perPage, setPerPage] = useState(() =>
    typeof window !== 'undefined' ? localStorage.getItem('browse_per_page') || '25' : '25',
  )
  const [browseHistoryEnabled, setBrowseHistoryEnabled] = useState(
    () => typeof window !== 'undefined' && localStorage.getItem('history_enabled') !== 'false',
  )

  return (
    <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
      <div className="px-5 pb-5 pt-5 space-y-5">
        {/* Search History toggle */}
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-vault-text">{t('settings.searchHistory')}</p>
            <p className="text-xs text-vault-text-muted mt-0.5">
              {t('settings.searchHistoryDesc')}
            </p>
          </div>
          <button
            onClick={() => {
              const next = !historyEnabled
              localStorage.setItem('eh_search_history_enabled', next ? 'true' : 'false')
              if (!next) localStorage.removeItem('eh_search_history')
              setHistoryEnabled(next)
            }}
            className={`relative w-11 h-6 rounded-full transition-colors ${historyEnabled ? 'bg-vault-accent' : 'bg-vault-border'}`}
          >
            <span
              className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform ${historyEnabled ? 'translate-x-5' : ''}`}
            />
          </button>
        </div>

        {/* Load mode: Pagination vs Infinite Scroll */}
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-vault-text">{t('settings.loadMode')}</p>
            <p className="text-xs text-vault-text-muted mt-0.5">{t('settings.loadModeDesc')}</p>
          </div>
          <div className="flex bg-vault-input border border-vault-border rounded overflow-hidden">
            <button
              onClick={() => {
                localStorage.setItem('browse_load_mode', 'pagination')
                setLoadMode('pagination')
              }}
              className={`px-3 py-1.5 text-xs transition-colors ${loadMode === 'pagination' ? 'bg-vault-accent text-white' : 'text-vault-text-muted hover:text-vault-text'}`}
            >
              {t('settings.pagination')}
            </button>
            <button
              onClick={() => {
                localStorage.setItem('browse_load_mode', 'scroll')
                setLoadMode('scroll')
              }}
              className={`px-3 py-1.5 text-xs transition-colors ${loadMode === 'scroll' ? 'bg-vault-accent text-white' : 'text-vault-text-muted hover:text-vault-text'}`}
            >
              {t('settings.infiniteScroll')}
            </button>
          </div>
        </div>

        {/* Per page (library) */}
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-vault-text">{t('settings.perPage')}</p>
            <p className="text-xs text-vault-text-muted mt-0.5">{t('settings.perPageDesc')}</p>
          </div>
          <select
            value={perPage}
            onChange={(e) => {
              localStorage.setItem('browse_per_page', e.target.value)
              setPerPage(e.target.value)
            }}
            className="bg-vault-input border border-vault-border rounded px-3 py-1.5 text-sm text-vault-text focus:outline-none"
          >
            <option value="25">25</option>
            <option value="50">50</option>
            <option value="100">100</option>
          </select>
        </div>

        {/* Browse History toggle */}
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm text-vault-text">{t('settings.browseHistory')}</p>
            <p className="text-xs text-vault-text-muted mt-0.5">
              {t('settings.browseHistoryDesc')}
            </p>
          </div>
          <button
            onClick={() => {
              const next = !browseHistoryEnabled
              localStorage.setItem('history_enabled', next ? 'true' : 'false')
              setBrowseHistoryEnabled(next)
            }}
            className={`relative w-11 h-6 rounded-full transition-colors ${browseHistoryEnabled ? 'bg-vault-accent' : 'bg-vault-border'}`}
          >
            <span
              className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform ${browseHistoryEnabled ? 'translate-x-5' : ''}`}
            />
          </button>
        </div>
      </div>
    </div>
  )
}

export default function GeneralSettingsPage() {
  const { locale, setLocale: changeLocale } = useLocale()

  return (
    <div className="max-w-2xl">
      <BackButton fallback="/settings" />
      <h1 className="text-2xl font-bold mb-6 text-vault-text">{t('settingsCategory.general')}</h1>

      <div className="space-y-3">
        {/* Language */}
        <div className="bg-vault-card rounded-xl border border-vault-border overflow-hidden">
          <div className="px-5 py-4">
            <h3 className="font-medium text-vault-text text-sm mb-3">{t('settings.language')}</h3>
            <select
              value={locale}
              onChange={(e) => changeLocale(e.target.value as Locale)}
              className="bg-vault-input text-vault-text text-sm rounded-lg px-3 py-2 border border-vault-border focus:outline-none focus:ring-1 focus:ring-vault-accent"
            >
              {SUPPORTED_LOCALES.map((loc: Locale) => (
                <option key={loc} value={loc}>
                  {t(`common.locale.${loc}`)}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Browse Settings */}
        <div>
          <h2 className="text-sm font-medium text-vault-text-muted uppercase tracking-wide px-1 mb-2">
            {t('settings.browse')}
          </h2>
          <BrowseSettings />
        </div>
      </div>
    </div>
  )
}
