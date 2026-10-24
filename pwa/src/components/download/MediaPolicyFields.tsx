'use client'

import { useState } from 'react'
import { t } from '@/lib/i18n'
import { parseMaxFiles } from '@/lib/mediaPolicy'
import type { MediaPolicy } from '@/lib/types'

/**
 * "Newest N files" + "include videos" selection shared by the manual download
 * form, the subscription create form and the subscription card editor.
 *
 * The number input keeps its own text so partial input can be typed; an
 * invalid value shows an inline error and is never propagated.
 */
export function MediaPolicyFields({
  value,
  onChange,
  disabled = false,
}: {
  value: MediaPolicy
  onChange: (policy: MediaPolicy) => void
  disabled?: boolean
}) {
  const [text, setText] = useState(value.max_files === null ? '' : String(value.max_files))
  const [prevMax, setPrevMax] = useState(value.max_files)
  const invalid = parseMaxFiles(text) === undefined

  // Re-sync the text when the parent changes the value (e.g. reset after enqueue),
  // but not while the text already parses to that value.
  if (prevMax !== value.max_files) {
    setPrevMax(value.max_files)
    const parsed = parseMaxFiles(text)
    if (parsed !== value.max_files) setText(value.max_files === null ? '' : String(value.max_files))
  }

  return (
    <div className="mt-3 text-xs text-vault-text-muted">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="font-medium">{t('mediaPolicy.title')}</span>
        <input
          type="number"
          inputMode="numeric"
          min={1}
          max={100000}
          step={1}
          value={text}
          disabled={disabled}
          onChange={(e) => {
            const next = e.target.value
            setText(next)
            const parsed = parseMaxFiles(next)
            if (parsed !== undefined) onChange({ ...value, max_files: parsed })
          }}
          placeholder={t('mediaPolicy.allPlaceholder')}
          aria-label={t('mediaPolicy.maxFiles')}
          aria-invalid={invalid}
          className={`w-24 bg-vault-input border rounded px-2 py-1 text-vault-text disabled:opacity-50 ${
            invalid ? 'border-red-500' : 'border-vault-border'
          }`}
        />
        <label className="inline-flex items-center gap-1.5 text-vault-text">
          <input
            type="checkbox"
            checked={value.include_videos}
            disabled={disabled}
            onChange={(e) => onChange({ ...value, include_videos: e.target.checked })}
            aria-label={t('mediaPolicy.includeVideos')}
            className="accent-vault-accent"
          />
          {t('mediaPolicy.includeVideos')}
        </label>
      </div>
      {invalid ? (
        <p role="alert" className="mt-1 text-red-400">
          {t('mediaPolicy.invalidMaxFiles')}
        </p>
      ) : (
        <p className="mt-1">{t('mediaPolicy.maxFilesHint')}</p>
      )}
    </div>
  )
}
