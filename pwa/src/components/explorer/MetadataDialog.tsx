'use client'

import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { useCategoryRegistry } from '@/hooks/useCategoryRegistry'
import { api } from '@/lib/api'
import type { ExplorerGalleryItem } from '@/lib/api'
import { t } from '@/lib/i18n'
import { Button } from '@/components/ui/button'
import { type QuerySelection } from './shared'
import { Modal } from './Modal'

const METADATA_FIELDS = [
  'title',
  'title_jpn',
  'category',
  'language',
  'artist_id',
  'uploader',
  'visibility',
] as const

export function MetadataDialog({
  selection,
  querySelection,
  onClose,
  onDone,
}: {
  selection: ExplorerGalleryItem[]
  querySelection: QuerySelection | null
  onClose: () => void
  onDone: () => void
}) {
  const [modes, setModes] = useState<Record<string, 'keep' | 'set' | 'clear'>>({})
  const [values, setValues] = useState<Record<string, string>>({})
  const [saving, setSaving] = useState(false)
  const { data: categoryRegistry } = useCategoryRegistry()
  const categoryNames = useMemo(
    () =>
      [...(categoryRegistry?.categories ?? [])]
        .sort((a, b) => a.sort_order - b.sort_order)
        .map((item) => item.name),
    [categoryRegistry],
  )
  const commonValues = useMemo(
    () =>
      Object.fromEntries(
        METADATA_FIELDS.map((field) => [
          field,
          selection.length > 0 &&
          selection.every((item) => String(item[field] ?? '') === String(selection[0][field] ?? ''))
            ? String(selection[0][field] ?? '')
            : '',
        ]),
      ),
    [selection],
  )

  const categoryMixed =
    selection.length > 0 &&
    !selection.every((item) => (item.category ?? '') === (selection[0].category ?? ''))
  const categoryValue =
    values.category ?? (categoryNames.includes(commonValues.category) ? commonValues.category : '')
  const categoryInvalid =
    (modes.category || 'keep') === 'set' && !categoryNames.includes(categoryValue)

  const submit = async () => {
    if (categoryInvalid) return
    const fields: Record<string, { mode: 'set' | 'clear'; value?: string }> = {}
    for (const field of METADATA_FIELDS) {
      const mode = modes[field] || 'keep'
      if (mode === 'set')
        fields[field] = {
          mode,
          value: field === 'category' ? categoryValue : (values[field] ?? commonValues[field]),
        }
      if (mode === 'clear') fields[field] = { mode }
    }
    if (Object.keys(fields).length === 0) return
    setSaving(true)
    try {
      await api.explorer.bulkMetadata({
        ...(querySelection
          ? { selection_token: querySelection.token, excluded_ids: [...querySelection.excluded] }
          : { gallery_ids: selection.map((item) => item.id) }),
        fields,
        lock_fields: true,
      })
      toast.success(t('explorer.metadataUpdated'))
      onDone()
      onClose()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t('common.errorOccurred'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      title={t('explorer.editMetadata')}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button variant="primary" disabled={saving || categoryInvalid} onClick={submit}>
            {saving ? t('common.loading') : t('common.save')}
          </Button>
        </>
      }
    >
      <div className="space-y-4 p-5">
        <p className="text-sm text-vault-text-muted">{t('explorer.manualFieldsLocked')}</p>
        {METADATA_FIELDS.map((field) => {
          const common = commonValues[field]
          return (
            <div key={field} className="grid grid-cols-[110px_minmax(0,1fr)] gap-3">
              <select
                aria-label={`${field} mode`}
                value={modes[field] || 'keep'}
                onChange={(event) =>
                  setModes((current) => ({
                    ...current,
                    [field]: event.target.value as 'keep' | 'set' | 'clear',
                  }))
                }
                className="rounded-md border border-vault-border bg-vault-bg px-2 py-2 text-sm text-vault-text"
              >
                <option value="keep">{t('explorer.keep')}</option>
                <option value="set">{t('explorer.set')}</option>
                {field !== 'visibility' && <option value="clear">{t('explorer.clear')}</option>}
              </select>
              {field === 'visibility' ? (
                <select
                  aria-label={field}
                  disabled={(modes[field] || 'keep') !== 'set'}
                  value={values[field] || common || 'public'}
                  onChange={(event) =>
                    setValues((current) => ({ ...current, [field]: event.target.value }))
                  }
                  className="rounded-md border border-vault-border bg-vault-bg px-3 py-2 text-sm text-vault-text disabled:opacity-50"
                >
                  <option value="public">{t('explorer.visibilityPublic')}</option>
                  <option value="private">{t('explorer.visibilityPrivate')}</option>
                </select>
              ) : field === 'category' ? (
                <select
                  aria-label={field}
                  disabled={(modes[field] || 'keep') !== 'set'}
                  value={categoryValue}
                  onChange={(event) =>
                    setValues((current) => ({ ...current, [field]: event.target.value }))
                  }
                  className="rounded-md border border-vault-border bg-vault-bg px-3 py-2 text-sm text-vault-text disabled:opacity-50"
                >
                  {!categoryNames.includes(categoryValue) && (
                    <option value="" disabled>
                      {categoryMixed ? t('explorer.mixedValues') : t('explorer.chooseCategory')}
                    </option>
                  )}
                  {categoryNames.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  aria-label={field}
                  disabled={(modes[field] || 'keep') !== 'set'}
                  defaultValue={common}
                  placeholder={common ? undefined : t('explorer.mixedValues')}
                  onChange={(event) =>
                    setValues((current) => ({ ...current, [field]: event.target.value }))
                  }
                  className="rounded-md border border-vault-border bg-vault-bg px-3 py-2 text-sm text-vault-text disabled:opacity-50"
                />
              )}
            </div>
          )
        })}
      </div>
    </Modal>
  )
}
