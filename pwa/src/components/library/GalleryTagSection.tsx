'use client'

import { useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Pencil } from 'lucide-react'
import { TagAutocomplete } from '@/components/TagAutocomplete'
import { TagSearchPopover } from '@/components/TagSearchPopover'
import { t } from '@/lib/i18n'

type TagPrediction = { namespace: string; name: string; confidence: number; source: string }

type GalleryTagSectionProps = {
  source: string
  tags: string[]
  translations?: Record<string, string>
  tagData: TagPrediction[]
  onUpdateTag: (tag: string, action: 'add' | 'remove') => void
}

const TAG_NAMESPACE_COLORS: Record<string, string> = {
  character: 'bg-purple-900/40 border-purple-700/50 text-purple-300',
  artist: 'bg-orange-900/40 border-orange-700/50 text-orange-300',
  parody: 'bg-blue-900/40 border-blue-700/50 text-blue-300',
  group: 'bg-yellow-900/40 border-yellow-700/50 text-yellow-300',
  language: 'bg-teal-900/40 border-teal-700/50 text-teal-300',
  male: 'bg-cyan-900/40 border-cyan-700/50 text-cyan-300',
  female: 'bg-pink-900/40 border-pink-700/50 text-pink-300',
  general: 'bg-vault-input border-vault-border text-vault-text-secondary',
}

function getTagColor(tag: string): string {
  const ns = tag.split(':')[0]
  return TAG_NAMESPACE_COLORS[ns] ?? TAG_NAMESPACE_COLORS.general
}

function groupTagsByNamespace(tags: string[]): Record<string, string[]> {
  const groups: Record<string, string[]> = {}
  for (const tag of tags) {
    const [ns, ...rest] = tag.split(':')
    const namespace = rest.length > 0 ? ns : 'general'
    const value = rest.length > 0 ? rest.join(':') : tag
    if (!groups[namespace]) groups[namespace] = []
    groups[namespace].push(value)
  }
  return groups
}

export function GalleryTagSection({
  source,
  tags,
  translations: tagTranslations,
  tagData,
  onUpdateTag,
}: GalleryTagSectionProps) {
  const router = useRouter()
  const [confidenceThreshold, setConfidenceThreshold] = useState(0.35)
  const [editingTags, setEditingTags] = useState(false)
  const [tagPopover, setTagPopover] = useState<{
    anchor: HTMLElement
    tag: string
    source: string
  } | null>(null)
  const manualTagSet = useMemo(
    () =>
      new Set(
        tagData
          .filter((tag) => tag.source === 'manual')
          .map((tag) => (tag.namespace === 'general' ? tag.name : tag.namespace + ':' + tag.name)),
      ),
    [tagData],
  )
  const tagGroups = groupTagsByNamespace(tags)
  const aiTags = tagData.filter(
    (tag) => tag.source === 'ai' && tag.confidence >= confidenceThreshold,
  )

  return (
    <div className="bg-vault-card border border-vault-border rounded-xl p-5 mb-5">
      <div className="flex items-center justify-between mb-3">
        <h2 className="text-sm font-semibold text-vault-text-secondary uppercase tracking-wide">
          {t('common.tags')}
        </h2>
        <button
          onClick={() => setEditingTags(!editingTags)}
          className={`flex items-center gap-1 px-2 py-1 rounded text-xs font-medium border transition-colors ${
            editingTags
              ? 'bg-vault-accent/20 border-vault-accent text-vault-accent'
              : 'bg-vault-input border-vault-border text-vault-text-secondary hover:text-vault-text'
          }`}
        >
          <Pencil size={12} />
          {editingTags ? t('library.doneEditingTags') : t('library.editTags')}
        </button>
      </div>
      {editingTags && (
        <div className="mb-3">
          <TagAutocomplete
            onSelect={(tag) => onUpdateTag(tag, 'add')}
            clearOnSelect={true}
            placeholder={t('library.addTagPlaceholder')}
          />
        </div>
      )}
      {Object.keys(tagGroups).length === 0 ? (
        <p className="text-sm text-vault-text-muted">{t('library.noTags')}</p>
      ) : (
        <div className="space-y-2">
          {Object.entries(tagGroups).map(([namespace, values]) => (
            <div key={namespace} className="flex flex-wrap gap-1 items-start">
              <span className="text-xs text-vault-text-muted w-20 shrink-0 pt-0.5 capitalize">
                {namespace}:
              </span>
              <div className="flex flex-wrap gap-1">
                {values.map((value) => {
                  const fullTag = namespace === 'general' ? value : `${namespace}:${value}`
                  const translation = tagTranslations?.[fullTag]
                  const isManual = manualTagSet.has(fullTag)
                  return (
                    <span
                      key={value}
                      className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs ${getTagColor(fullTag)}`}
                      title={translation ? `${namespace}:${value}` : undefined}
                    >
                      <button
                        type="button"
                        disabled={editingTags}
                        className="cursor-pointer hover:brightness-125 disabled:cursor-default"
                        onClick={(e) => {
                          const src = source
                          if (src === 'local' || (src !== 'ehentai' && src !== 'pixiv')) {
                            const bare = fullTag.includes(':')
                              ? fullTag.split(':').slice(1).join(':')
                              : fullTag
                            router.push(`/library?q=${encodeURIComponent(bare)}`)
                          } else {
                            setTagPopover({
                              anchor: e.currentTarget,
                              tag: fullTag,
                              source: src,
                            })
                          }
                        }}
                      >
                        {translation || value}
                      </button>
                      {editingTags && isManual && (
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation()
                            onUpdateTag(fullTag, 'remove')
                          }}
                          className="ml-0.5 opacity-60 hover:opacity-100 leading-none"
                          aria-label={t('common.removeTag', { tag: fullTag })}
                        >
                          ×
                        </button>
                      )}
                    </span>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* AI Tags (if any) */}
      {tagData.some((t) => t.source === 'ai') && (
        <div className="mt-4 pt-4 border-t border-vault-border">
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-xs font-semibold text-vault-text-secondary uppercase tracking-wide">
              {t('library.aiTags')}
            </h3>
            <div className="flex items-center gap-2">
              <label className="text-xs text-vault-text-muted">
                {t('library.confidence')}: {Math.round(confidenceThreshold * 100)}%
              </label>
              <input
                type="range"
                min="0"
                max="100"
                value={Math.round(confidenceThreshold * 100)}
                onChange={(e) => setConfidenceThreshold(Number(e.target.value) / 100)}
                className="w-24 h-1.5 accent-purple-500"
              />
            </div>
          </div>
          {aiTags.length > 0 ? (
            <div className="flex flex-wrap gap-1">
              {aiTags.map((tag) => {
                const aiFullTag =
                  tag.namespace === 'general' ? tag.name : `${tag.namespace}:${tag.name}`
                return (
                  <button
                    type="button"
                    key={`${tag.namespace}:${tag.name}`}
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded border bg-purple-900/30 border-purple-700/40 text-purple-300 text-xs cursor-pointer hover:brightness-125"
                    title={`${Math.round(tag.confidence * 100)}% confidence`}
                    onClick={(e) => {
                      const src = source
                      if (src === 'local' || (src !== 'ehentai' && src !== 'pixiv')) {
                        router.push(`/library?q=${encodeURIComponent(tag.name)}`)
                      } else {
                        setTagPopover({ anchor: e.currentTarget, tag: aiFullTag, source: src })
                      }
                    }}
                  >
                    {tag.namespace !== 'general' && (
                      <span className="text-purple-400/60">{tag.namespace}:</span>
                    )}
                    {tag.name}
                    <span className="text-purple-400/50 text-[10px]">
                      {Math.round(tag.confidence * 100)}%
                    </span>
                  </button>
                )
              })}
            </div>
          ) : (
            <p className="text-xs text-vault-text-muted">{t('library.noAiTagsAboveThreshold')}</p>
          )}
        </div>
      )}
      {tagPopover && (
        <TagSearchPopover
          tag={tagPopover.tag}
          gallerySource={tagPopover.source}
          anchorEl={tagPopover.anchor}
          onClose={() => setTagPopover(null)}
        />
      )}
    </div>
  )
}
