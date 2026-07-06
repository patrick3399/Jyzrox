'use client'

import {
  createElement,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Pencil } from 'lucide-react'
import { remarkWikilink } from './remarkWikilink'
import { useLongPress } from '@/hooks/useLongPress'
import { t } from '@/lib/i18n'
import type { NovelAct } from '@/lib/api'

export type BlockRange = { start: number; end: number }

/** Minimal shape of the hast node react-markdown passes to custom components. */
type MdNode = {
  position?: { start: { line: number }; end: { line: number } }
}
type BlockProps = { node?: MdNode; children?: ReactNode }

function rangeOf(node?: MdNode): BlockRange | null {
  const pos = node?.position
  return pos ? { start: pos.start.line, end: pos.end.line } : null
}

const draftKey = (path: string, baseSha: string, r: BlockRange) =>
  `novel:blockdraft:${path}:${baseSha}:${r.start}-${r.end}`

/** In-place raw editor for a single block; seeded from the block's source lines. */
function BlockEditor({
  path,
  baseSha,
  range,
  initialText,
  saving,
  onSave,
  onCancel,
}: {
  path: string
  baseSha: string
  range: BlockRange
  initialText: string
  saving: boolean
  onSave: (range: BlockRange, text: string) => void
  onCancel: () => void
}) {
  const key = draftKey(path, baseSha, range)
  const [text, setText] = useState(() => {
    try {
      const draft = window.localStorage.getItem(key)
      if (draft !== null && draft !== initialText) return draft
    } catch {
      // ignore
    }
    return initialText
  })
  const draftTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  const onChange = useCallback(
    (value: string) => {
      setText(value)
      if (draftTimer.current) clearTimeout(draftTimer.current)
      draftTimer.current = setTimeout(() => {
        try {
          window.localStorage.setItem(key, value)
        } catch {
          // ignore quota
        }
      }, 500)
    },
    [key],
  )

  useEffect(() => {
    return () => {
      if (draftTimer.current) clearTimeout(draftTimer.current)
    }
  }, [])

  const clearDraft = useCallback(() => {
    try {
      window.localStorage.removeItem(key)
    } catch {
      // ignore
    }
  }, [key])

  return (
    <div className="my-2 rounded-lg border border-vault-accent bg-vault-card p-2">
      <textarea
        autoFocus
        aria-label={t('novels.editThisBlock')}
        className="min-h-24 w-full resize-y rounded border border-vault-border bg-vault-input p-2 font-mono text-sm text-vault-text"
        value={text}
        onChange={(e) => onChange(e.target.value)}
      />
      <div className="mt-2 flex justify-end gap-2">
        <button
          type="button"
          className="rounded border border-vault-border px-3 py-1 text-xs text-vault-text-muted hover:text-vault-text"
          onClick={() => {
            clearDraft()
            onCancel()
          }}
        >
          {t('novels.cancel')}
        </button>
        <button
          type="button"
          disabled={saving}
          className="rounded bg-vault-accent px-3 py-1 text-xs font-medium text-white disabled:opacity-50"
          onClick={() => {
            clearDraft()
            onSave(range, text)
          }}
        >
          {t('novels.save')}
        </button>
      </div>
    </div>
  )
}

/**
 * Full-Markdown renderer for novel chapters (replaces the hand-rolled per-line
 * renderer). Contracts preserved from the old reader:
 *   1. `### 幕` headings keep `id="act-{index}"` so the TOC + progress restore
 *      (Reader's getElementById('act-N')) keep working. Mapped via the backend's
 *      0-based `acts[].line` against each heading node's 1-based source line.
 *   2. `[[wikilink]]` renders as a highlighted span (via remarkWikilink).
 *
 * Every top-level block carries `data-line-start`/`data-line-end` (1-based source
 * lines). When `editable`, right-click (desktop) / long-press (touch) on a block
 * opens an in-place raw editor for exactly that source range.
 */
export function MarkdownView({
  content,
  acts,
  editable = false,
  path = '',
  baseSha = '',
  editingRange = null,
  saving = false,
  onRequestEdit,
  onSaveBlock,
  onCancelEdit,
}: {
  content: string
  acts: NovelAct[]
  editable?: boolean
  path?: string
  baseSha?: string
  editingRange?: BlockRange | null
  saving?: boolean
  onRequestEdit?: (range: BlockRange) => void
  onSaveBlock?: (range: BlockRange, text: string) => void
  onCancelEdit?: () => void
}) {
  // backend acts[].line is 0-based; heading node position is 1-based.
  const lineToAct = useMemo(() => {
    const m = new Map<number, number>()
    for (const a of acts) m.set(a.line, a.index)
    return m
  }, [acts])

  const lines = useMemo(() => content.split('\n'), [content])
  const seedFor = useCallback(
    (r: BlockRange) => lines.slice(r.start - 1, r.end).join('\n'),
    [lines],
  )

  const components = useMemo<Components>(() => {
    const lineAttrs = (node?: MdNode): Record<string, number> => {
      const r = rangeOf(node)
      return r ? { 'data-line-start': r.start, 'data-line-end': r.end } : {}
    }

    const isEditing = (r: BlockRange | null) =>
      !!(r && editingRange && r.start === editingRange.start && r.end === editingRange.end)

    const editorFor = (r: BlockRange) => (
      <BlockEditor
        path={path}
        baseSha={baseSha}
        range={r}
        initialText={seedFor(r)}
        saving={saving}
        onSave={(rr, text) => onSaveBlock?.(rr, text)}
        onCancel={() => onCancelEdit?.()}
      />
    )

    const block = (tag: string) => {
      const Block = ({ node, children }: BlockProps) => {
        const r = rangeOf(node)
        if (editable && r && isEditing(r)) return editorFor(r)
        // hr is a void element — it can hold neither children nor the pencil.
        if (tag === 'hr') return createElement('hr', lineAttrs(node))
        return createElement(
          tag,
          lineAttrs(node),
          editable && r ? (
            <>
              {children}
              <button
                type="button"
                tabIndex={-1}
                aria-label={t('novels.editThisBlock')}
                title={t('novels.editThisBlock')}
                className="novel-block-pencil"
                onClick={(e) => {
                  e.preventDefault()
                  onRequestEdit?.(r)
                }}
              >
                <Pencil className="size-3" />
              </button>
            </>
          ) : (
            children
          ),
        )
      }
      Block.displayName = `MdBlock(${tag})`
      return Block
    }

    const heading = (tag: string) => {
      const Heading = ({ node, children }: BlockProps) => {
        const r = rangeOf(node)
        if (editable && r && isEditing(r)) return editorFor(r)
        const attrs: Record<string, string | number> = lineAttrs(node)
        if (r) {
          const actIndex = lineToAct.get(r.start - 1)
          if (actIndex !== undefined) attrs.id = `act-${actIndex}`
        }
        return createElement(tag, attrs, children)
      }
      Heading.displayName = `MdHeading(${tag})`
      return Heading
    }

    return {
      h1: heading('h1'),
      h2: heading('h2'),
      h3: heading('h3'),
      h4: heading('h4'),
      h5: heading('h5'),
      h6: heading('h6'),
      p: block('p'),
      ul: block('ul'),
      ol: block('ol'),
      blockquote: block('blockquote'),
      pre: block('pre'),
      table: block('table'),
      hr: block('hr'),
    } as Components
  }, [
    lineToAct,
    editable,
    editingRange,
    path,
    baseSha,
    saving,
    seedFor,
    onSaveBlock,
    onCancelEdit,
    onRequestEdit,
  ])

  // Right-click (desktop) + long-press (touch) on a block → request its edit.
  // Reuses the shared useLongPress hook (which also suppresses the synthetic
  // click that follows a long-press). Handlers are only wired when editable.
  const blockRangeFromEvent = useCallback((target: EventTarget | null): BlockRange | null => {
    if (!(target instanceof HTMLElement)) return null
    const el = target.closest('[data-line-start]')
    if (!(el instanceof HTMLElement)) return null
    const start = Number(el.dataset.lineStart)
    const end = Number(el.dataset.lineEnd)
    if (!start || !end) return null
    return { start, end }
  }, [])

  const longPress = useLongPress({
    onLongPress: (e) => {
      const r = blockRangeFromEvent(e.target)
      if (r) onRequestEdit?.(r)
    },
  })

  return (
    <div
      className={editable ? 'novel-markdown novel-editable' : 'novel-markdown'}
      {...(editable ? longPress : {})}
    >
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkWikilink]} components={components}>
        {content}
      </ReactMarkdown>
    </div>
  )
}
