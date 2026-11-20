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
  aliases: string[]
  frontmatter: Record<string, unknown>
}
export interface NovelAppearance {
  chapter_path: string
  mention_count: number
  first_offset: number
}

export interface NovelRemoteInfo {
  url: string | null
  repo_exists: boolean
  has_key: boolean
  public_key: string | null
  key_fingerprint: string | null
  host_trusted: boolean
}
export interface NovelHostKey {
  type: string
  fingerprint: string
}
export type NovelRemoteSaveResult =
  | { ok: true; mode: 'cloned' | 'set_url' | 'recloned' }
  | {
      ok: false
      status: number
      message: string
      needsReclone?: { reason: string; unpushed: number; dirty: boolean }
    }
