'use client'

import { useState, useEffect, useCallback } from 'react'
import { useLocale } from '@/components/LocaleProvider'
import { BackButton } from '@/components/BackButton'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { t } from '@/lib/i18n'
import { toast } from 'sonner'
import { api } from '@/lib/api'
import { X, Plus, Tag } from 'lucide-react'
import type { BlockedTag } from '@/lib/types'
import { inputClass, btnPrimary } from '@/components/settings/SettingsShared'

export default function BlockedTagsSettingsPage() {
  useLocale()

  const [blockedTags, setBlockedTags] = useState<BlockedTag[]>([])
  const [blockedTagsLoaded, setBlockedTagsLoaded] = useState(false)
  const [blockedTagsLoading, setBlockedTagsLoading] = useState(false)
  const [newBlockedTag, setNewBlockedTag] = useState('')
  const [blockingTag, setBlockingTag] = useState(false)
  const [removingBlockedTagId, setRemovingBlockedTagId] = useState<number | null>(null)

  const handleLoadBlockedTags = useCallback(async () => {
    setBlockedTagsLoading(true)
    try {
      const items = await api.tags.listBlocked()
      setBlockedTags(items)
      setBlockedTagsLoaded(true)
    } catch {
      toast.error(t('common.failedToLoad'))
      setBlockedTagsLoaded(true)
    } finally {
      setBlockedTagsLoading(false)
    }
  }, [])

  const handleAddBlockedTag = useCallback(async () => {
    const raw = newBlockedTag.trim()
    if (!raw) return
    // accept "namespace:name" or fall back to "tag:name"
    const colonIdx = raw.indexOf(':')
    let namespace: string
    let name: string
    if (colonIdx > 0) {
      namespace = raw.slice(0, colonIdx).trim()
      name = raw.slice(colonIdx + 1).trim()
    } else {
      namespace = 'tag'
      name = raw
    }
    if (!name) return
    setBlockingTag(true)
    try {
      await api.tags.addBlocked(namespace, name)
      toast.success(t('settings.tagBlockAdded'))
      setNewBlockedTag('')
      await handleLoadBlockedTags()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.tagBlockAddFailed'))
    } finally {
      setBlockingTag(false)
    }
  }, [newBlockedTag, handleLoadBlockedTags])

  const handleRemoveBlockedTag = useCallback(async (id: number) => {
    setRemovingBlockedTagId(id)
    try {
      await api.tags.removeBlocked(id)
      toast.success(t('settings.tagBlockRemoved'))
      setBlockedTags((prev) => prev.filter((bt) => bt.id !== id))
    } catch (err) {
      toast.error(err instanceof Error ? err.message : t('settings.tagBlockRemoveFailed'))
    } finally {
      setRemovingBlockedTagId(null)
    }
  }, [])

  useEffect(() => {
    if (!blockedTagsLoaded && !blockedTagsLoading) {
      handleLoadBlockedTags()
    }
  }, [blockedTagsLoaded, blockedTagsLoading, handleLoadBlockedTags])

  return (
    <div className="max-w-2xl">
      <BackButton fallback="/settings" />
      <div className="flex items-center gap-3 mb-6">
        <h1 className="text-2xl font-bold text-vault-text">{t('settingsCategory.blockedTags')}</h1>
        {blockedTags.length > 0 && (
          <span className="inline-flex items-center gap-1 text-sm text-vault-text-muted">
            <Tag size={14} />
            {blockedTags.length}
          </span>
        )}
      </div>

      <div className="bg-vault-card border border-vault-border rounded-xl overflow-hidden">
        <div className="px-5 pb-5">
          <p className="text-xs text-vault-text-muted mt-4 mb-3">{t('settings.tagBlockingDesc')}</p>

          {/* Add new blocked tag */}
          <div className="flex gap-2">
            <input
              type="text"
              value={newBlockedTag}
              onChange={(e) => setNewBlockedTag(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleAddBlockedTag()}
              placeholder={t('settings.blockedTagPlaceholder')}
              className={inputClass + ' flex-1'}
            />
            <button
              onClick={handleAddBlockedTag}
              disabled={blockingTag || !newBlockedTag.trim()}
              className={btnPrimary + ' flex items-center gap-1.5 shrink-0'}
            >
              <Plus size={14} />
              {blockingTag ? t('settings.saving') : t('settings.addBlockedTag')}
            </button>
          </div>

          {/* Blocked tag list */}
          <div className="mt-4">
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs text-vault-text-muted uppercase tracking-wide">
                {t('settings.blockedTags')}
              </p>
              <button
                onClick={handleLoadBlockedTags}
                disabled={blockedTagsLoading}
                className="text-xs text-vault-text-muted hover:text-vault-text-secondary transition-colors"
              >
                {blockedTagsLoading ? t('settings.loading') : t('settings.refresh')}
              </button>
            </div>

            {blockedTagsLoading && blockedTags.length === 0 ? (
              <div className="flex justify-center py-4">
                <LoadingSpinner />
              </div>
            ) : blockedTags.length === 0 ? (
              <p className="text-xs text-vault-text-muted py-2">{t('settings.noBlockedTags')}</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {blockedTags.map((bt) => (
                  <div
                    key={bt.id}
                    className="inline-flex items-center gap-1.5 bg-vault-input border border-vault-border rounded-full px-3 py-1 text-sm text-vault-text"
                  >
                    <span className="text-vault-text-muted text-xs">{bt.namespace}:</span>
                    <span>{bt.name}</span>
                    <button
                      onClick={() => handleRemoveBlockedTag(bt.id)}
                      disabled={removingBlockedTagId === bt.id}
                      className="ml-0.5 text-vault-text-muted hover:text-red-400 transition-colors disabled:opacity-40"
                      title={t('settings.unblock')}
                    >
                      {removingBlockedTagId === bt.id ? (
                        <span className="text-[10px]">...</span>
                      ) : (
                        <X size={12} />
                      )}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
