'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import useSWR from 'swr'
import { api, type NovelFile } from '@/lib/api'
import { t } from '@/lib/i18n'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import {
  ReaderSettings,
  DEFAULT_READER_PREFS,
  type ReaderPrefs,
  type ReaderTheme,
} from './ReaderSettings'

const PREFS_CACHE_KEY = 'novel:prefs'

const THEME_STYLES: Record<ReaderTheme, { background: string; color: string }> = {
  light: { background: '#ffffff', color: '#1a1a1a' },
  dark: { background: '#16161a', color: '#e4e4e7' },
  sepia: { background: '#f4ecd8', color: '#433422' },
}

function loadCachedPrefs(): ReaderPrefs {
  if (typeof window === 'undefined') return DEFAULT_READER_PREFS
  try {
    const raw = window.localStorage.getItem(PREFS_CACHE_KEY)
    if (raw) return { ...DEFAULT_READER_PREFS, ...JSON.parse(raw) }
  } catch {
    // ignore malformed cache
  }
  return DEFAULT_READER_PREFS
}

/** Render one line of novel markdown into a React node with a stable key. */
function renderLine(line: string, index: number, actLineToIndex: Map<number, number>) {
  const heading = /^(#{1,3})\s+(.*)$/.exec(line)
  if (heading) {
    const level = heading[1].length
    const text = heading[2]
    const actIndex = actLineToIndex.get(index)
    const id = actIndex !== undefined ? `act-${actIndex}` : undefined
    const cls =
      level === 1
        ? 'mt-6 mb-4 text-2xl font-bold'
        : level === 2
          ? 'mt-5 mb-3 text-xl font-semibold'
          : 'mt-4 mb-2 text-lg font-semibold'
    return (
      <h3 key={index} id={id} className={cls}>
        {text}
      </h3>
    )
  }
  if (line.trim() === '') return <div key={index} className="h-3" />
  return (
    <p key={index} className="my-2 leading-relaxed">
      {renderInline(line)}
    </p>
  )
}

/** Turn [[wikilinks]] into highlighted spans (clickable entity cards land in Phase 1). */
function renderInline(line: string): React.ReactNode {
  const parts: React.ReactNode[] = []
  const regex = /\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]/g
  let last = 0
  let m: RegExpExecArray | null
  let i = 0
  while ((m = regex.exec(line)) !== null) {
    if (m.index > last) parts.push(line.slice(last, m.index))
    parts.push(
      <span key={`wl-${i++}`} className="text-vault-accent underline decoration-dotted">
        {m[1].trim()}
      </span>,
    )
    last = m.index + m[0].length
  }
  if (last < line.length) parts.push(line.slice(last))
  return parts
}

export function Reader({ path }: { path: string }) {
  const { data, isLoading } = useSWR<NovelFile>(path ? ['novel-file', path] : null, ([, p]) =>
    api.novels.readFile(p as string),
  )
  const [prefs, setPrefs] = useState<ReaderPrefs>(loadCachedPrefs)
  const scrollTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const containerRef = useRef<HTMLDivElement | null>(null)

  // Load server prefs once (localStorage acts as the fast first paint).
  useEffect(() => {
    let alive = true
    api.novels
      .getPrefs()
      .then((res) => {
        if (!alive) return
        const p = res.preferences as Partial<ReaderPrefs>
        if (p && (p.fontSize || p.theme)) {
          setPrefs((prev) => ({ ...prev, ...p }))
        }
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [])

  const persistPrefs = useCallback((next: ReaderPrefs) => {
    setPrefs(next)
    try {
      window.localStorage.setItem(PREFS_CACHE_KEY, JSON.stringify(next))
    } catch {
      // ignore quota errors
    }
    api.novels.putPrefs(next as unknown as Record<string, unknown>).catch(() => {})
  }, [])

  const actLineToIndex = useMemo(() => {
    const map = new Map<number, number>()
    for (const act of data?.acts ?? []) map.set(act.line, act.index)
    return map
  }, [data?.acts])

  // Restore saved progress once content is available.
  useEffect(() => {
    if (!data) return
    let alive = true
    api.novels
      .getProgress(path)
      .then((res) => {
        if (!alive || !res.position) return
        const m = /act:(\d+)/.exec(res.position)
        if (m) {
          const el = document.getElementById(`act-${m[1]}`)
          if (el) el.scrollIntoView({ block: 'start' })
        }
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [data, path])

  const handleScroll = useCallback(() => {
    if (scrollTimer.current) clearTimeout(scrollTimer.current)
    scrollTimer.current = setTimeout(() => {
      // Find the last act heading scrolled past the top.
      const acts = data?.acts ?? []
      let current = 0
      for (const act of acts) {
        const el = document.getElementById(`act-${act.index}`)
        if (el && el.getBoundingClientRect().top < 120) current = act.index
      }
      const offset = Math.round(window.scrollY)
      api.novels.putProgress(path, `act:${current}|offset:${offset}`).catch(() => {})
    }, 1000)
  }, [data?.acts, path])

  useEffect(() => {
    window.addEventListener('scroll', handleScroll, { passive: true })
    return () => {
      window.removeEventListener('scroll', handleScroll)
      if (scrollTimer.current) clearTimeout(scrollTimer.current)
    }
  }, [handleScroll])

  if (isLoading) return <LoadingSpinner />
  if (!data) return <p className="py-10 text-center text-vault-text-muted">{t('novels.loadFailed')}</p>

  const lines = data.content.split('\n')
  const themeStyle = THEME_STYLES[prefs.theme]

  return (
    <div className="flex flex-col gap-4 lg:flex-row">
      {/* Act TOC */}
      {data.acts.length > 0 && (
        <nav
          aria-label={t('novels.tableOfContents')}
          className="order-2 shrink-0 lg:order-1 lg:w-48"
        >
          <p className="mb-2 text-xs font-semibold text-vault-text-muted">
            {t('novels.tableOfContents')}
          </p>
          <ul className="flex flex-col gap-1">
            {data.acts.map((act) => (
              <li key={act.index}>
                <a
                  href={`#act-${act.index}`}
                  className="block truncate text-sm text-vault-text-muted hover:text-vault-accent"
                >
                  {act.title}
                </a>
              </li>
            ))}
          </ul>
        </nav>
      )}

      <div className="order-1 min-w-0 flex-1 lg:order-2">
        <div className="mb-4">
          <ReaderSettings prefs={prefs} onChange={persistPrefs} />
        </div>
        <article
          ref={containerRef}
          data-theme={prefs.theme}
          data-testid="reader-content"
          className="rounded-lg px-5 py-6"
          style={{
            background: themeStyle.background,
            color: themeStyle.color,
            fontSize: `${prefs.fontSize}px`,
          }}
        >
          {lines.map((line, i) => renderLine(line, i, actLineToIndex))}
        </article>

        {data.backlinks.length > 0 && (
          <div className="mt-4">
            <p className="mb-1 text-xs font-semibold text-vault-text-muted">
              {t('novels.backlinks')}
            </p>
            <div className="flex flex-wrap gap-2">
              {data.backlinks.map((name) => (
                <span
                  key={name}
                  className="rounded border border-vault-border px-2 py-0.5 text-xs text-vault-text-muted"
                >
                  {name}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
