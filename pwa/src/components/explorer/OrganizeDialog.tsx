'use client'

import { useState } from 'react'
import useSWR from 'swr'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import { Button } from '@/components/ui/button'
import { Modal } from './Modal'

export function OrganizeDialog({
  kind,
  selectionBody,
  onClose,
  onDone,
}: {
  kind: 'tags' | 'collections'
  selectionBody: { gallery_ids?: number[]; selection_token?: string; excluded_ids?: number[] }
  onClose: () => void
  onDone: () => void
}) {
  const [operation, setOperation] = useState<'add' | 'remove'>('add')
  const [tagsValue, setTagsValue] = useState('')
  const [collectionId, setCollectionId] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)
  const { data: collectionData } = useSWR(
    kind === 'collections' ? 'explorer-action-collections' : null,
    api.collections.list,
  )

  const submit = async () => {
    setSaving(true)
    try {
      if (kind === 'tags') {
        const tags = tagsValue
          .split(/[\n,]+/)
          .map((value) => value.trim())
          .filter(Boolean)
        await api.explorer.bulkAction({
          ...selectionBody,
          action: operation === 'add' ? 'add_tags' : 'remove_tags',
          tags,
        })
      } else {
        if (collectionId === null) return
        await api.explorer.bulkAction({
          ...selectionBody,
          action: operation === 'add' ? 'add_collection' : 'remove_collection',
          collection_id: collectionId,
        })
      }
      toast.success(t('explorer.bulkActionComplete'))
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
      title={kind === 'tags' ? t('explorer.manageTags') : t('explorer.manageCollections')}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            {t('common.cancel')}
          </Button>
          <Button variant="primary" disabled={saving} onClick={submit}>
            {saving ? t('common.loading') : t('common.save')}
          </Button>
        </>
      }
    >
      <div className="space-y-4 p-5">
        <div className="flex rounded-md border border-vault-border p-1">
          <button
            type="button"
            onClick={() => setOperation('add')}
            className={`flex-1 rounded px-3 py-2 text-sm ${operation === 'add' ? 'bg-vault-accent text-white' : 'text-vault-text-muted'}`}
          >
            {t('explorer.add')}
          </button>
          <button
            type="button"
            onClick={() => setOperation('remove')}
            className={`flex-1 rounded px-3 py-2 text-sm ${operation === 'remove' ? 'bg-vault-accent text-white' : 'text-vault-text-muted'}`}
          >
            {t('explorer.remove')}
          </button>
        </div>
        {kind === 'tags' ? (
          <textarea
            value={tagsValue}
            onChange={(event) => setTagsValue(event.target.value)}
            placeholder="artist:name, language:english"
            rows={5}
            className="w-full rounded-md border border-vault-border bg-vault-bg p-3 text-sm text-vault-text"
          />
        ) : (
          <select
            value={collectionId ?? ''}
            onChange={(event) => setCollectionId(Number(event.target.value))}
            className="w-full rounded-md border border-vault-border bg-vault-bg px-3 py-2 text-sm text-vault-text"
          >
            <option value="">{t('explorer.chooseCollection')}</option>
            {(collectionData?.collections || []).map((collection) => (
              <option key={collection.id} value={collection.id}>
                {collection.name}
              </option>
            ))}
          </select>
        )}
      </div>
    </Modal>
  )
}
