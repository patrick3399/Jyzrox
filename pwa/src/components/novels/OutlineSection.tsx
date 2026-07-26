'use client'

import { useState } from 'react'
import Link from 'next/link'
import useSWR from 'swr'
import { ChevronDown, ChevronRight, ListTree } from 'lucide-react'
import { api } from '@/lib/api'
import { novelChapterHref } from '@/lib/novels'
import { t } from '@/lib/i18n'

/**
 * A work's plot outline (參考/大綱.md) as structured nodes. Nodes whose chapter
 * exists link to it; the rest are the part of the plan not written yet, which is
 * the whole point of showing the outline next to the chapter list.
 */
export function OutlineSection({ work }: { work: string }) {
  const [open, setOpen] = useState(false)
  const { data } = useSWR(open && work ? ['novel-outline', work] : null, ([, w]) =>
    api.novels.outline(w as string),
  )
  const nodes = data?.nodes ?? []

  return (
    <section className="mt-6">
      <button
        type="button"
        aria-expanded={open}
        className="flex w-full items-center gap-2 rounded-lg border border-vault-border px-4 py-3 text-left text-sm font-medium text-vault-text hover:border-vault-accent"
        onClick={() => setOpen((v) => !v)}
      >
        {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
        <ListTree className="size-4" />
        {t('novels.outline')}
      </button>

      {open && (
        <div className="mt-2">
          {data && data.path === null ? (
            <p className="rounded-lg border border-dashed border-vault-border px-4 py-6 text-center text-sm text-vault-text-muted">
              {t('novels.outlineMissing', { path: data.canonical_path })}
            </p>
          ) : nodes.length === 0 ? (
            <p className="py-4 text-center text-sm text-vault-text-muted">
              {t('novels.outlineEmpty')}
            </p>
          ) : (
            <ol data-testid="outline-nodes" className="flex flex-col gap-1">
              {nodes.map((n) => (
                <li
                  key={`${n.order}-${n.line}`}
                  className="rounded-lg border border-vault-border bg-vault-card px-4 py-3"
                >
                  <div className="flex items-center justify-between gap-2">
                    {n.chapter_path ? (
                      <Link
                        href={novelChapterHref(
                          work,
                          n.chapter_path.split('/').pop()?.replace(/\.md$/, '') ?? '',
                          n.chapter_path,
                        )}
                        className="min-w-0 flex-1 truncate font-medium text-vault-text hover:text-vault-accent"
                      >
                        {n.title}
                      </Link>
                    ) : (
                      <span className="min-w-0 flex-1 truncate font-medium text-vault-text">
                        {n.title}
                      </span>
                    )}
                    <span
                      data-testid={`outline-state-${n.order}`}
                      className={`shrink-0 rounded px-1.5 py-0.5 text-xs ${
                        n.chapter_path
                          ? 'bg-green-500/15 text-green-500'
                          : 'bg-vault-border/40 text-vault-text-muted'
                      }`}
                    >
                      {n.chapter_path ? t('novels.outlineWritten') : t('novels.outlinePlanned')}
                    </span>
                  </div>
                  {n.preview && (
                    <p className="mt-1 line-clamp-2 text-xs text-vault-text-muted">{n.preview}</p>
                  )}
                  {n.beats.length > 0 && (
                    <ul className="mt-2 flex flex-wrap gap-1">
                      {n.beats.map((b) => (
                        <li
                          key={b.line}
                          className="rounded border border-vault-border px-1.5 py-0.5 text-xs text-vault-text-muted"
                        >
                          {b.title}
                        </li>
                      ))}
                    </ul>
                  )}
                </li>
              ))}
            </ol>
          )}
        </div>
      )}
    </section>
  )
}
