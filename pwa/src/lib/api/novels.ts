import { apiFetch, getCookie, qs } from './client'
import { novelFilePath } from '@/lib/novels'

// ── Novel module ──────────────────────────────────────────────────────

export interface NovelWork {
  name: string
  chapter_count: number
}
export interface NovelChapter {
  path: string
  name: string
  /** Whitespace-excluded character count of the body (not the byte size). */
  chars: number
  /** Authored one-liner from the file's `summary:` frontmatter, if any. */
  summary?: string | null
  mtime: number
  category?: string
}
export interface NovelCategoryCounts {
  extra: number
  draft: number
  reference: number
  scrap: number
}
export interface NovelAct {
  index: number
  title: string
  line: number
}
export interface NovelFile {
  path: string
  content: string
  base_sha: string
  acts: NovelAct[]
  backlinks: string[]
}
export interface NovelSearchHit {
  path: string
  line: number
  text: string
  category?: string
}
export interface NovelCommit {
  hash: string
  date: string
  message: string
}
export interface NovelRepoStatus {
  head: string
  ahead: number
  behind: number
  clean: boolean
  locked: boolean
}
export type NovelWriteResult =
  | { ok: true; head: string; pushed: boolean }
  | {
      ok: false
      status: number
      conflict?: { current: string; current_sha: string }
      message?: string
    }

/** A plot node from a work's outline, lined up with the chapter it plans. */
export interface NovelOutlineNode {
  order: number
  level: number
  title: string
  line: number
  chapter_no: number | null
  preview: string
  beats: { title: string; line: number }[]
  chapter_path: string | null
}
export interface NovelOutline {
  /** null when the work has no outline file yet. */
  path: string | null
  /** Where an outline belongs, for the "create one" affordance. */
  canonical_path: string
  nodes: NovelOutlineNode[]
}

/** One FORMAT.md violation. `rule` is a stable id; its wording lives in i18n. */
export interface NovelFormatIssue {
  rule: string
  line: number
  text: string
}
export interface NovelFileIssues {
  path: string
  issues: NovelFormatIssue[]
}

export interface NovelGraphNode {
  id: string
  label: string
  type: 'note' | 'chapter'
}
export interface NovelGraphEdge {
  src: string
  dst: string
  kind: 'link' | 'mention'
}
export interface NovelGraph {
  nodes: NovelGraphNode[]
  edges: NovelGraphEdge[]
}
export interface NovelNoteSummary {
  path: string
  title: string
  note_type: string | null
  frontmatter: Record<string, unknown>
}
export interface NovelAppearance {
  chapter_path: string
  mention_count: number
  first_offset: number
}

export const novels = {
  listWorks: () => apiFetch<{ works: NovelWork[] }>('/api/novels/works'),
  listChapters: (work: string) =>
    apiFetch<{ chapters: NovelChapter[]; categories: NovelCategoryCounts }>(
      `/api/novels/works/${encodeURIComponent(work)}/chapters`,
    ),
  listWorkFiles: (work: string, category: string) =>
    apiFetch<{ files: NovelChapter[] }>(
      `/api/novels/works/${encodeURIComponent(work)}/files${qs({ category })}`,
    ),
  readFile: (path: string) => apiFetch<NovelFile>(`/api/novels/file${qs({ path })}`),
  // Custom fetch: a 409 carries the server's current content, which apiFetch
  // would collapse into a generic Error — the editor needs it for the diff hint.
  writeFile: async (body: {
    path: string
    content: string
    base_sha?: string
    message?: string
    create?: boolean
  }): Promise<NovelWriteResult> => {
    const csrf = getCookie('csrf_token')
    const res = await fetch('/api/novels/file', {
      method: 'PUT',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        ...(csrf ? { 'X-CSRF-Token': csrf } : {}),
      },
      body: JSON.stringify(body),
    })
    if (res.ok) {
      const data = (await res.json()) as { head: string; pushed: boolean }
      return { ok: true, head: data.head, pushed: data.pushed }
    }
    const errBody = await res.json().catch(() => ({}))
    const detail = (errBody as { detail?: unknown })?.detail
    if (
      res.status === 409 &&
      typeof detail === 'object' &&
      detail !== null &&
      'current' in detail
    ) {
      const d = detail as { current: string; current_sha: string }
      return {
        ok: false,
        status: 409,
        conflict: { current: d.current, current_sha: d.current_sha },
      }
    }
    // create=true against an existing path → {error: "file exists"}.
    const detailError =
      typeof detail === 'object' && detail !== null && 'error' in detail
        ? (detail as { error: unknown }).error
        : undefined
    return {
      ok: false,
      status: res.status,
      message:
        typeof detail === 'string'
          ? detail
          : typeof detailError === 'string'
            ? detailError
            : `HTTP ${res.status}`,
    }
  },
  // Create a new chapter file (new work = new folder via its first chapter).
  // Reuses PUT /file with create:true; the backend refuses to clobber and needs
  // no base_sha (a new file has no base revision), so this is a single request.
  createFile: async (work: string, name: string, subdir?: string): Promise<NovelWriteResult> => {
    const path = novelFilePath(work, name, subdir)
    return novels.writeFile({
      path,
      content: `# ${name}\n\n`,
      create: true,
      message: `create: ${path}`,
    })
  },
  // Writes the `summary:` frontmatter key only; an empty string clears it.
  putSummary: (path: string, summary: string, base_sha: string) =>
    apiFetch<{ head: string; pushed: boolean }>('/api/novels/file/summary', {
      method: 'PUT',
      body: JSON.stringify({ path, summary, base_sha }),
    }),
  outline: (work: string) =>
    apiFetch<NovelOutline>(`/api/novels/works/${encodeURIComponent(work)}/outline`),
  // ── FORMAT.md lint / fix ──
  lintFile: (path: string) =>
    apiFetch<{ path: string; issues: NovelFormatIssue[] }>(`/api/novels/file/lint${qs({ path })}`),
  lintWork: (work: string) =>
    apiFetch<{ files: NovelFileIssues[]; total: number }>(
      `/api/novels/works/${encodeURIComponent(work)}/lint`,
    ),
  fixFile: (path: string, base_sha: string) =>
    apiFetch<{ changes: string[]; head: string; pushed: boolean }>('/api/novels/file/fix', {
      method: 'POST',
      body: JSON.stringify({ path, base_sha }),
    }),
  search: (q: string) => apiFetch<{ hits: NovelSearchHit[] }>(`/api/novels/search${qs({ q })}`),
  history: (path: string) =>
    apiFetch<{ commits: NovelCommit[] }>(`/api/novels/file/history${qs({ path })}`),
  // `base` compares two arbitrary revisions; omitted → rev against its parent.
  diff: (path: string, rev: string, base?: string) =>
    apiFetch<{ diff: string }>(`/api/novels/file/diff${qs({ path, rev, base })}`),
  // Restore a file to an older revision as a new commit (never rewrites history).
  // base_sha is the caller's view of HEAD — the same lost-update guard as writeFile.
  revertFile: (path: string, rev: string, base_sha: string) =>
    apiFetch<{ head: string; pushed: boolean; reverted_to: string }>('/api/novels/file/revert', {
      method: 'POST',
      body: JSON.stringify({ path, rev, base_sha }),
    }),
  status: () => apiFetch<NovelRepoStatus>('/api/novels/status'),
  sync: () => apiFetch<{ pulled: boolean }>('/api/novels/sync', { method: 'POST' }),
  reset: () => apiFetch<{ ok: boolean }>('/api/novels/reset', { method: 'POST' }),
  getProgress: (path: string) =>
    apiFetch<{ path: string; position: string | null }>(`/api/novels/progress${qs({ path })}`),
  putProgress: (path: string, position: string) =>
    apiFetch<{ ok: boolean }>(`/api/novels/progress${qs({ path })}`, {
      method: 'PUT',
      body: JSON.stringify({ position }),
    }),
  getPrefs: () => apiFetch<{ preferences: Record<string, unknown> }>('/api/novels/preferences'),
  putPrefs: (prefs: Record<string, unknown>) =>
    apiFetch<{ ok: boolean }>('/api/novels/preferences', {
      method: 'PUT',
      body: JSON.stringify(prefs),
    }),
  // ── Knowledge index (Phase 1 Track A) ──
  graph: () => apiFetch<NovelGraph>('/api/novels/graph'),
  notes: (params: { type?: string; tag?: string; sort?: string } = {}) =>
    apiFetch<{ notes: NovelNoteSummary[] }>(`/api/novels/notes${qs(params)}`),
  appearances: (path: string) =>
    apiFetch<{ appearances: NovelAppearance[] }>(`/api/novels/notes/appearances${qs({ path })}`),
  reindex: () =>
    apiFetch<{ stats: Record<string, number> }>('/api/novels/reindex', { method: 'POST' }),
}
