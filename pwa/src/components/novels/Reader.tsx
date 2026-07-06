'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import useSWR, { mutate } from 'swr'
import { toast } from 'sonner'
import { Code, Eye } from 'lucide-react'
import { api, type NovelFile } from '@/lib/api'
import { t } from '@/lib/i18n'
import { LoadingSpinner } from '@/components/LoadingSpinner'
import { MarkdownView, type BlockRange } from './MarkdownView'
import {
  ReaderSettings,
  DEFAULT_READER_PREFS,
  type ReaderPrefs,
  type ReaderTheme,
} from './ReaderSettings'

const PREFS_CACHE_KEY = 'novel:prefs'
const VIEWMODE_CACHE_KEY = 'novel:viewmode'

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

function loadCachedViewMode(): 'render' | 'raw' {
  if (typeof window === 'undefined') return 'render'
  try {
    return window.localStorage.getItem(VIEWMODE_CACHE_KEY) === 'raw' ? 'raw' : 'render'
  } catch {
    return 'render'
  }
}

export function Reader({ path, canEdit = false }: { path: string; canEdit?: boolean }) {
  const { data, isLoading } = useSWR<NovelFile>(path ? ['novel-file', path] : null, ([, p]) =>
    api.novels.readFile(p as string),
  )
  const [prefs, setPrefs] = useState<ReaderPrefs>(loadCachedPrefs)
  const [viewMode, setViewMode] = useState<'render' | 'raw'>(loadCachedViewMode)
  const [editingRange, setEditingRange] = useState<BlockRange | null>(null)
  const [saving, setSaving] = useState(false)
  const scrollTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

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

  const toggleViewMode = useCallback(() => {
    setViewMode((prev) => {
      const next = prev === 'render' ? 'raw' : 'render'
      try {
        window.localStorage.setItem(VIEWMODE_CACHE_KEY, next)
      } catch {
        // ignore quota
      }
      return next
    })
    setEditingRange(null)
  }, [])

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

  const handleSaveBlock = useCallback(
    async (range: BlockRange, text: string) => {
      if (!data) return
      setSaving(true)
      try {
        const lines = data.content.split('\n')
        const before = lines.slice(0, range.start - 1)
        const after = lines.slice(range.end)
        const nextContent = [...before, ...text.split('\n'), ...after].join('\n')
        const result = await api.novels.writeFile({
          path,
          content: nextContent,
          base_sha: data.base_sha,
          message: `edit: ${path}`,
        })
        if (result.ok || result.conflict) {
          // Both close the editor and refetch; a conflict just also warns.
          toast[result.ok ? 'success' : 'error'](
            result.ok ? t('novels.saved') : t('novels.staleConflict'),
          )
          setEditingRange(null)
          mutate(['novel-file', path])
        } else {
          toast.error(result.message || t('novels.saveFailed'))
        }
      } catch {
        toast.error(t('novels.saveFailed'))
      } finally {
        setSaving(false)
      }
    },
    [data, path],
  )

  if (isLoading) return <LoadingSpinner />
  if (!data) return <p className="py-10 text-center text-vault-text-muted">{t('novels.loadFailed')}</p>

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
        <div className="mb-4 flex items-center justify-between gap-2">
          <ReaderSettings prefs={prefs} onChange={persistPrefs} />
          <button
            type="button"
            aria-pressed={viewMode === 'raw'}
            className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-vault-border px-2 py-1 text-xs text-vault-text-muted hover:border-vault-accent hover:text-vault-text"
            onClick={toggleViewMode}
          >
            {viewMode === 'raw' ? <Eye className="size-3" /> : <Code className="size-3" />}
            {viewMode === 'raw' ? t('novels.viewRendered') : t('novels.viewRaw')}
          </button>
        </div>
        <article
          data-theme={prefs.theme}
          data-testid="reader-content"
          className="rounded-lg px-5 py-6"
          style={{
            background: themeStyle.background,
            color: themeStyle.color,
            fontSize: `${prefs.fontSize}px`,
          }}
        >
          {viewMode === 'raw' ? (
            <pre className="overflow-x-auto whitespace-pre-wrap font-mono text-sm">
              {data.content}
            </pre>
          ) : (
            <MarkdownView
              content={data.content}
              acts={data.acts}
              editable={canEdit}
              path={path}
              baseSha={data.base_sha}
              editingRange={editingRange}
              saving={saving}
              onRequestEdit={setEditingRange}
              onSaveBlock={handleSaveBlock}
              onCancelEdit={() => setEditingRange(null)}
            />
          )}
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
