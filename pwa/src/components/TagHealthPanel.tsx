'use client'
import { useCallback } from 'react'
import useSWR from 'swr'
import { toast } from 'sonner'
import { Trash2, EyeOff, RotateCcw, Link2Off } from 'lucide-react'
import { api } from '@/lib/api'
import { t } from '@/lib/i18n'
import type { TagItem } from '@/lib/types'

/**
 * Tag Health Report panel (admin-only).
 *
 * Surfaces orphaned tags, suspected duplicates, and implication cycles so an
 * admin can clean them up with one-click delete / set-alias / break-link /
 * ignore actions. See docs/superpowers/specs/2026-07-12-tag-health-report-design.md.
 */
export default function TagHealthPanel() {
  const { data: report, mutate: mutateReport } = useSWR('tags/health', () => api.tags.health())
  const { data: ignoredData, mutate: mutateIgnored } = useSWR('tags/health/ignored', () =>
    api.tags.healthIgnored(),
  )

  const refresh = useCallback(() => {
    mutateReport()
    mutateIgnored()
  }, [mutateReport, mutateIgnored])

  const handleDeleteOrphan = useCallback(
    async (tag: TagItem) => {
      try {
        await api.tags.deleteTag(tag.id)
        toast.success(t('tags.health.deleteSuccess'))
        refresh()
      } catch (e: unknown) {
        toast.error(e instanceof Error ? e.message : t('tags.health.deleteFailed'))
      }
    },
    [refresh],
  )

  const handleIgnore = useCallback(
    async (key: string) => {
      try {
        await api.tags.healthIgnore(key)
        toast.success(t('tags.health.ignoreSuccess'))
        refresh()
      } catch (e: unknown) {
        toast.error(e instanceof Error ? e.message : t('tags.health.ignoreFailed'))
      }
    },
    [refresh],
  )

  const handleUnignore = useCallback(
    async (key: string) => {
      try {
        await api.tags.healthUnignore(key)
        toast.success(t('tags.health.unignoreSuccess'))
        refresh()
      } catch (e: unknown) {
        toast.error(e instanceof Error ? e.message : t('tags.health.unignoreFailed'))
      }
    },
    [refresh],
  )

  const handleSetAlias = useCallback(
    async (tag: TagItem, canonical: TagItem) => {
      try {
        await api.tags.createAlias(tag.namespace, tag.name, canonical.id)
        toast.success(t('tags.health.aliasSuccess'))
        refresh()
      } catch (e: unknown) {
        toast.error(e instanceof Error ? e.message : t('tags.health.aliasFailed'))
      }
    },
    [refresh],
  )

  const handleBreakImplication = useCallback(
    async (antecedentId: number, consequentId: number) => {
      try {
        await api.tags.deleteImplication(antecedentId, consequentId)
        toast.success(t('tags.health.cycleBreakSuccess'))
        refresh()
      } catch (e: unknown) {
        toast.error(e instanceof Error ? e.message : t('tags.health.cycleBreakFailed'))
      }
    },
    [refresh],
  )

  const ignoredKeys = ignoredData?.keys ?? []

  return (
    <div className="space-y-6">
      {/* Orphans */}
      <section className="bg-vault-card border border-vault-border rounded-xl p-4">
        <h2 className="text-lg font-semibold mb-1">{t('tags.health.orphans')}</h2>
        <p className="text-sm text-vault-text-muted mb-3">
          {t('tags.health.orphansTotal', { total: String(report?.orphans_total ?? 0) })}
        </p>
        {report && report.orphans.length === 0 ? (
          <p className="text-sm text-vault-text-muted">{t('tags.health.orphansEmpty')}</p>
        ) : (
          <ul className="space-y-1">
            {report?.orphans.map((tag) => (
              <li
                key={tag.id}
                className="flex items-center justify-between text-sm py-1 border-t border-vault-border first:border-t-0"
              >
                <span className="font-mono">
                  <span className="text-vault-text-muted">{tag.namespace}:</span>
                  {tag.name}
                  <span className="text-vault-text-muted ml-2">({tag.count})</span>
                </span>
                <div className="flex gap-1">
                  <button
                    type="button"
                    onClick={() => handleDeleteOrphan(tag)}
                    aria-label={t('tags.health.delete')}
                    title={t('tags.health.delete')}
                    className="p-1 text-red-400 hover:bg-red-500/10 rounded transition-colors"
                  >
                    <Trash2 size={14} />
                  </button>
                  <button
                    type="button"
                    onClick={() => handleIgnore(`orphan:${tag.id}`)}
                    aria-label={t('tags.health.ignore')}
                    title={t('tags.health.ignore')}
                    className="p-1 text-vault-text-muted hover:bg-vault-card-hover rounded transition-colors"
                  >
                    <EyeOff size={14} />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Duplicates */}
      <section className="bg-vault-card border border-vault-border rounded-xl p-4">
        <h2 className="text-lg font-semibold mb-3">{t('tags.health.duplicates')}</h2>
        {report && report.duplicates.length === 0 ? (
          <p className="text-sm text-vault-text-muted">{t('tags.health.duplicatesEmpty')}</p>
        ) : (
          <div className="space-y-4">
            {report?.duplicates.map((group) => {
              const sorted = [...group.tags].sort((a, b) => b.count - a.count)
              const canonical = sorted[0]
              return (
                <div key={group.key} className="border border-vault-border rounded-lg p-3">
                  <ul className="space-y-1 mb-2">
                    {sorted.map((tag) => (
                      <li key={tag.id} className="flex items-center justify-between text-sm">
                        <span className="font-mono">
                          <span className="text-vault-text-muted">{tag.namespace}:</span>
                          {tag.name}
                          <span className="text-vault-text-muted ml-2">({tag.count})</span>
                          {canonical?.id === tag.id && (
                            <span className="ml-2 text-xs text-vault-accent">
                              {t('tags.health.canonical')}
                            </span>
                          )}
                        </span>
                        {canonical && canonical.id !== tag.id && (
                          <button
                            type="button"
                            onClick={() => handleSetAlias(tag, canonical)}
                            className="px-2 py-1 text-xs bg-vault-accent/10 text-vault-accent hover:bg-vault-accent/20 rounded transition-colors"
                          >
                            {t('tags.health.setAlias')}
                          </button>
                        )}
                      </li>
                    ))}
                  </ul>
                  <button
                    type="button"
                    onClick={() => handleIgnore(`dup:${group.key}`)}
                    className="flex items-center gap-1 text-xs text-vault-text-muted hover:text-vault-text transition-colors"
                  >
                    <EyeOff size={12} /> {t('tags.health.ignore')}
                  </button>
                </div>
              )
            })}
          </div>
        )}
      </section>

      {/* Implication cycles */}
      <section className="bg-vault-card border border-vault-border rounded-xl p-4">
        <h2 className="text-lg font-semibold mb-3">{t('tags.health.cycles')}</h2>
        {report && report.implication_cycles.length === 0 ? (
          <p className="text-sm text-vault-text-muted">{t('tags.health.cyclesEmpty')}</p>
        ) : (
          <div className="space-y-4">
            {report?.implication_cycles.map((cycle) => (
              <div key={cycle.key} className="border border-vault-border rounded-lg p-3">
                <div className="flex flex-wrap items-center gap-1 text-sm mb-2 font-mono">
                  {cycle.path.map((node, idx) => {
                    const next = cycle.path[(idx + 1) % cycle.path.length]
                    return (
                      <span
                        key={`${cycle.key}-${node.id}-${idx}`}
                        className="flex items-center gap-1"
                      >
                        <span>
                          {node.namespace}:{node.name}
                        </span>
                        {next && (
                          <button
                            type="button"
                            onClick={() => handleBreakImplication(node.id, next.id)}
                            aria-label={t('tags.health.breakLink')}
                            title={t('tags.health.breakLink')}
                            className="p-1 text-red-400 hover:bg-red-500/10 rounded transition-colors"
                          >
                            <Link2Off size={12} />
                          </button>
                        )}
                        <span aria-hidden="true" className="text-vault-text-muted">
                          &rarr;
                        </span>
                      </span>
                    )
                  })}
                  {cycle.path[0] && (
                    <span>
                      {cycle.path[0].namespace}:{cycle.path[0].name}
                    </span>
                  )}
                </div>
                <button
                  type="button"
                  onClick={() => handleIgnore(`cycle:${cycle.key}`)}
                  className="flex items-center gap-1 text-xs text-vault-text-muted hover:text-vault-text transition-colors"
                >
                  <EyeOff size={12} /> {t('tags.health.ignore')}
                </button>
              </div>
            ))}
          </div>
        )}
      </section>

      {/* Ignored */}
      <details className="bg-vault-card border border-vault-border rounded-xl p-4">
        <summary className="text-lg font-semibold cursor-pointer">
          {t('tags.health.ignored')} ({ignoredKeys.length})
        </summary>
        <div className="mt-3">
          {ignoredKeys.length === 0 ? (
            <p className="text-sm text-vault-text-muted">{t('tags.health.ignoredEmpty')}</p>
          ) : (
            <ul className="space-y-1">
              {ignoredKeys.map((key) => (
                <li key={key} className="flex items-center justify-between text-sm">
                  <span className="font-mono">{key}</span>
                  <button
                    type="button"
                    onClick={() => handleUnignore(key)}
                    aria-label={t('tags.health.unignore')}
                    title={t('tags.health.unignore')}
                    className="p-1 text-vault-text-muted hover:bg-vault-card-hover rounded transition-colors"
                  >
                    <RotateCcw size={14} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </details>
    </div>
  )
}
