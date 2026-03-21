'use client'

import { useReducer } from 'react'
import { useLocale } from '@/components/LocaleProvider'
import { BackButton } from '@/components/BackButton'
import { t } from '@/lib/i18n'
import { loadReaderSettings, saveReaderSettings } from '@/components/Reader/hooks'
import type { ViewMode, ScaleMode, ReadingDirection } from '@/components/Reader/types'

function ReaderToggle({ value, onToggle }: { value: boolean; onToggle: () => void }) {
  return (
    <button
      onClick={onToggle}
      className={`relative w-11 h-6 rounded-full transition-colors shrink-0 ${value ? 'bg-vault-accent' : 'bg-vault-border'}`}
    >
      <span
        className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform ${value ? 'translate-x-5' : ''}`}
      />
    </button>
  )
}

function ReaderSettingRow({
  label,
  desc,
  children,
}: {
  label: string
  desc?: string
  children: React.ReactNode
}) {
  return (
    <div className="flex items-center justify-between py-1">
      <div>
        <p className="text-sm text-vault-text">{label}</p>
        {desc && <p className="text-xs text-vault-text-muted mt-0.5">{desc}</p>}
      </div>
      {children}
    </div>
  )
}

function ReaderSettingsSection({ onForceRerender }: { onForceRerender: () => void }) {
  const s = loadReaderSettings()

  const selectClass =
    'bg-vault-input border border-vault-border rounded px-3 py-2 text-vault-text focus:outline-none focus:border-vault-accent text-sm'

  return (
    <div className="space-y-4">
      {/* Auto Advance */}
      <div>
        <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">
          {t('reader.autoAdvance')}
        </p>
        <div className="bg-vault-input border border-vault-border rounded-lg px-3 py-3 space-y-3">
          <ReaderSettingRow label={t('reader.autoAdvance')} desc={t('reader.autoAdvanceDesc')}>
            <ReaderToggle
              value={s.autoAdvanceEnabled}
              onToggle={() => {
                saveReaderSettings({ autoAdvanceEnabled: !s.autoAdvanceEnabled })
                onForceRerender()
              }}
            />
          </ReaderSettingRow>
          {s.autoAdvanceEnabled && (
            <ReaderSettingRow label={t('reader.autoAdvanceInterval')}>
              <div className="flex items-center gap-2">
                <input
                  type="range"
                  min={2}
                  max={30}
                  step={1}
                  value={s.autoAdvanceSeconds}
                  onChange={(e) => {
                    saveReaderSettings({ autoAdvanceSeconds: Number(e.target.value) })
                    onForceRerender()
                  }}
                  className="w-28 accent-vault-accent"
                />
                <span className="text-xs tabular-nums text-vault-text-secondary w-8 text-right">
                  {s.autoAdvanceSeconds}s
                </span>
              </div>
            </ReaderSettingRow>
          )}
        </div>
      </div>

      {/* Status Bar */}
      <div>
        <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">
          {t('reader.statusBar')}
        </p>
        <div className="bg-vault-input border border-vault-border rounded-lg px-3 py-3 space-y-3">
          <ReaderSettingRow label={t('reader.statusBar')} desc={t('reader.statusBarDesc')}>
            <ReaderToggle
              value={s.statusBarEnabled}
              onToggle={() => {
                saveReaderSettings({ statusBarEnabled: !s.statusBarEnabled })
                onForceRerender()
              }}
            />
          </ReaderSettingRow>
          {s.statusBarEnabled && (
            <>
              <ReaderSettingRow label={t('reader.statusBarClock')}>
                <ReaderToggle
                  value={s.statusBarShowClock}
                  onToggle={() => {
                    saveReaderSettings({ statusBarShowClock: !s.statusBarShowClock })
                    onForceRerender()
                  }}
                />
              </ReaderSettingRow>
              <ReaderSettingRow label={t('reader.statusBarProgress')}>
                <ReaderToggle
                  value={s.statusBarShowProgress}
                  onToggle={() => {
                    saveReaderSettings({ statusBarShowProgress: !s.statusBarShowProgress })
                    onForceRerender()
                  }}
                />
              </ReaderSettingRow>
              <ReaderSettingRow label={t('reader.statusBarPageCount')}>
                <ReaderToggle
                  value={s.statusBarShowPageCount}
                  onToggle={() => {
                    saveReaderSettings({ statusBarShowPageCount: !s.statusBarShowPageCount })
                    onForceRerender()
                  }}
                />
              </ReaderSettingRow>
            </>
          )}
        </div>
      </div>

      {/* Defaults */}
      <div>
        <p className="text-xs text-vault-text-muted uppercase tracking-wide mb-2">Defaults</p>
        <div className="bg-vault-input border border-vault-border rounded-lg px-3 py-3 space-y-3">
          <ReaderSettingRow label={t('reader.defaultViewMode')}>
            <select
              value={s.defaultViewMode}
              onChange={(e) => {
                saveReaderSettings({ defaultViewMode: e.target.value as ViewMode })
                onForceRerender()
              }}
              className={selectClass}
            >
              <option value="single">{t('reader.viewModeSingle')}</option>
              <option value="webtoon">{t('reader.viewModeWebtoon')}</option>
              <option value="double">{t('reader.viewModeDouble')}</option>
            </select>
          </ReaderSettingRow>
          <ReaderSettingRow label={t('reader.defaultDirection')}>
            <select
              value={s.defaultReadingDirection}
              onChange={(e) => {
                saveReaderSettings({ defaultReadingDirection: e.target.value as ReadingDirection })
                onForceRerender()
              }}
              className={selectClass}
            >
              <option value="ltr">{t('reader.dirLtr')}</option>
              <option value="rtl">{t('reader.dirRtl')}</option>
              <option value="vertical">{t('reader.dirVertical')}</option>
            </select>
          </ReaderSettingRow>
          <ReaderSettingRow label={t('reader.defaultScaleMode')}>
            <select
              value={s.defaultScaleMode}
              onChange={(e) => {
                saveReaderSettings({ defaultScaleMode: e.target.value as ScaleMode })
                onForceRerender()
              }}
              className={selectClass}
            >
              <option value="fit-both">{t('reader.scaleFitBoth')}</option>
              <option value="fit-width">{t('reader.scaleFitWidth')}</option>
              <option value="fit-height">{t('reader.scaleFitHeight')}</option>
              <option value="original">{t('reader.scaleOriginal')}</option>
            </select>
          </ReaderSettingRow>
        </div>
      </div>
    </div>
  )
}

export default function ReaderSettingsPage() {
  useLocale()
  // useReducer as a simple force-rerender mechanism (same pattern as original)
  const [, forceRerender] = useReducer((x: number) => x + 1, 0)

  return (
    <div className="max-w-2xl">
      <BackButton fallback="/settings" />
      <h1 className="text-2xl font-bold mb-6 text-vault-text">{t('settingsCategory.reader')}</h1>

      <div className="bg-vault-card border border-vault-border rounded-xl px-5 pb-5 pt-5">
        <ReaderSettingsSection onForceRerender={forceRerender} />
      </div>
    </div>
  )
}
