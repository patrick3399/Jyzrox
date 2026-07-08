'use client'

import { useState } from 'react'
import Link from 'next/link'
import { ChevronDown, ChevronRight } from 'lucide-react'
import useSWR from 'swr'
import { api } from '@/lib/api'
import { novelChapterHref } from '@/lib/novels'
import { t } from '@/lib/i18n'

export type WorkCategory = 'extra' | 'draft' | 'reference' | 'scrap'

export const CATEGORY_LABEL_KEYS: Record<WorkCategory, string> = {
  extra: 'novels.categoryExtra',
  draft: 'novels.categoryDraft',
  reference: 'novels.categoryReference',
  scrap: 'novels.categoryScrap',
}

export function WorkCategorySection({
  work,
  category,
  count,
}: {
  work: string
  category: WorkCategory
  count: number
}) {
  const [open, setOpen] = useState(false)
  // Lazy: only fetch once the section has been expanded.
  const { data } = useSWR(open ? ['novel-files', work, category] : null, ([, w, c]) =>
    api.novels.listWorkFiles(w, c),
  )
  if (count === 0) return null
  const files = data?.files ?? []
  return (
    <section className="mt-4">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 rounded-lg border border-vault-border px-4 py-2 text-sm text-vault-text-muted hover:border-vault-accent hover:text-vault-text"
      >
        {open ? <ChevronDown className="size-4" /> : <ChevronRight className="size-4" />}
        <span className="font-medium">{t(CATEGORY_LABEL_KEYS[category])}</span>
        <span className="ml-auto text-xs">{count}</span>
      </button>
      {open && (
        <ul className="mt-1 flex flex-col gap-1">
          {files.map((f) => (
            <li key={f.path}>
              <Link
                href={novelChapterHref(work, f.name, f.path)}
                className="flex items-center justify-between rounded-lg border border-vault-border bg-vault-card px-4 py-2 text-sm transition-colors hover:border-vault-accent"
              >
                <span className="truncate text-vault-text">{f.name}</span>
                <span className="ml-2 shrink-0 text-xs text-vault-text-muted">
                  {f.chars.toLocaleString()}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
