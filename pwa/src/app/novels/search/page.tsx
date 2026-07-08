'use client'

import { useState } from 'react'
import Link from 'next/link'
import { ArrowLeft, Search } from 'lucide-react'
import useSWR from 'swr'
import { api } from '@/lib/api'
import { novelChapterHref } from '@/lib/novels'
import { t } from '@/lib/i18n'
import { useLocale } from '@/components/LocaleProvider'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { BackButton } from '@/components/BackButton'
import { CATEGORY_LABEL_KEYS, type WorkCategory } from '@/components/novels/WorkCategorySection'

function hitHref(path: string): string {
  const parts = path.split('/')
  const work = parts[0] ?? ''
  const chapter = (parts[parts.length - 1] ?? '').replace(/\.md$/, '')
  return novelChapterHref(work, chapter, path)
}

function isWorkCategoryKey(value: string): value is WorkCategory {
  return value in CATEGORY_LABEL_KEYS
}

export default function NovelSearchPage() {
  useLocale()
  const [input, setInput] = useState('')
  const [query, setQuery] = useState('')
  const { data, isLoading } = useSWR(query ? ['novel-search', query] : null, ([, q]) =>
    api.novels.search(q as string),
  )
  const hits = data?.hits ?? []

  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-6">
      <Link
        href="/novels"
        className="mb-4 inline-flex items-center gap-1 text-sm text-vault-text-muted hover:text-vault-text"
      >
        <ArrowLeft className="size-4" />
        {t('novels.works')}
      </Link>

      <form
        className="mb-4 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          setQuery(input.trim())
        }}
      >
        <input
          type="search"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={t('novels.searchPlaceholder')}
          className="flex-1 rounded-lg border border-vault-border bg-vault-input px-3 py-2 text-sm text-vault-text"
        />
        <button
          type="submit"
          className="inline-flex items-center gap-1 rounded-lg bg-vault-accent px-4 py-2 text-sm font-medium text-white"
        >
          <Search className="size-4" />
          {t('novels.search')}
        </button>
      </form>

      {isLoading ? (
        <LoadingSpinner />
      ) : query && hits.length === 0 ? (
        <p className="py-10 text-center text-vault-text-muted">{t('novels.noResults')}</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {hits.map((hit, i) => (
            <li key={`${hit.path}-${hit.line}-${i}`}>
              <Link
                href={hitHref(hit.path)}
                className="block rounded-lg border border-vault-border bg-vault-card px-3 py-2 hover:border-vault-accent"
              >
                <span className="flex items-center text-xs text-vault-text-muted">
                  {hit.path}:{hit.line + 1}
                  {hit.category && hit.category !== 'main' && isWorkCategoryKey(hit.category) && (
                    <span className="ml-2 shrink-0 rounded border border-vault-border px-1.5 py-0.5 text-[10px] text-vault-text-muted">
                      {t(CATEGORY_LABEL_KEYS[hit.category])}
                    </span>
                  )}
                </span>
                <span className="block truncate text-sm text-vault-text">{hit.text}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}

      <BackButton fallback="/novels" toParent />
    </div>
  )
}
