'use client'

import Link from 'next/link'
import useSWR from 'swr'
import { api } from '@/lib/api'
import { galleryHref } from '@/lib/galleryRoutes'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { useLocale } from '@/components/LocaleProvider'
import { t } from '@/lib/i18n'

export default function ReadingStatsPage() {
  useLocale()
  const { data, isLoading } = useSWR('library/reading-stats', () => api.library.readingStats(30))
  if (isLoading) return <LoadingSpinner />
  const maxEvents = Math.max(1, ...(data?.trend.map((item) => item.events) ?? []))
  return (
    <main className="mx-auto max-w-6xl space-y-6 p-4 md:p-8">
      <div>
        <h1 className="text-2xl font-bold text-vault-text">{t('stats.title')}</h1>
        <p className="text-sm text-vault-text-muted">{t('stats.description')}</p>
      </div>
      <section className="rounded-xl border border-vault-border bg-vault-card p-4">
        <h2 className="mb-4 font-semibold">{t('stats.trend')}</h2>
        <div
          className="flex h-48 items-end gap-1 overflow-x-auto"
          aria-label={t('stats.trendAria')}
        >
          {(data?.trend ?? []).map((item) => (
            <div
              key={item.date}
              className="flex min-w-6 flex-1 flex-col items-center justify-end gap-1"
              title={`${item.date}: ${t('stats.events', { count: item.events })}`}
            >
              <div
                className="w-full rounded-t bg-vault-accent"
                style={{ height: `${Math.max(4, (item.events / maxEvents) * 160)}px` }}
              />
              <span className="text-[9px] text-vault-text-muted [writing-mode:vertical-rl]">
                {item.date.slice(5)}
              </span>
            </div>
          ))}
          {!data?.trend.length && (
            <p className="self-center text-sm text-vault-text-muted">{t('stats.noEvents')}</p>
          )}
        </div>
      </section>
      <div className="grid gap-6 lg:grid-cols-2">
        <section className="rounded-xl border border-vault-border bg-vault-card p-4">
          <h2 className="mb-3 font-semibold">{t('stats.frequentTags')}</h2>
          <div className="flex flex-wrap gap-2">
            {(data?.top_tags ?? []).map((tag) => (
              <span
                key={`${tag.namespace}:${tag.name}`}
                className="rounded-full bg-vault-accent/10 px-3 py-1 text-sm text-vault-accent"
              >
                {tag.namespace}:{tag.name} · {tag.reads}
              </span>
            ))}
          </div>
        </section>
        <section className="rounded-xl border border-vault-border bg-vault-card p-4">
          <h2 className="mb-3 font-semibold">{t('stats.continueReading')}</h2>
          <div className="space-y-2">
            {(data?.unfinished ?? []).map((item) => (
              <Link
                key={item.gallery_id}
                href={galleryHref(item.source, item.source_id)}
                className="block rounded border border-vault-border p-3 hover:border-vault-accent"
              >
                <p className="truncate font-medium">
                  {item.title || t('stats.galleryFallback', { id: item.gallery_id })}
                </p>
                <p className="text-xs text-vault-text-muted">
                  {t('stats.pageProgress', { page: item.last_page, pages: item.pages })}
                </p>
              </Link>
            ))}
          </div>
        </section>
      </div>
    </main>
  )
}
