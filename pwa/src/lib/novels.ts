import type { NovelNoteSummary } from '@/lib/api/novels'

/**
 * Repo-relative path for a chapter/canon file, optionally inside a standard
 * canon subfolder (e.g. '草稿'). Shared by api.novels.createFile and callers
 * that need to know the resulting path before/without a round trip (e.g. to
 * navigate to the newly created file).
 */
export function novelFilePath(work: string, name: string, subdir?: string): string {
  return subdir ? `${work}/${subdir}/${name}.md` : `${work}/${name}.md`
}

/** URL for a chapter reader page. `path` is the repo-relative `.md` path. */
export function novelChapterHref(work: string, chapter: string, path: string): string {
  return `/novels/${encodeURIComponent(work)}/${encodeURIComponent(chapter)}?path=${encodeURIComponent(path)}`
}

/** URL for an entity card page. `path` is the repo-relative note `.md` path. */
export function novelNoteHref(path: string): string {
  return `/novels/note/${path.split('/').map(encodeURIComponent).join('/')}`
}

/** name → note path for one work's entity notes. Names come from the
 * server-derived `aliases` (canonical `設定-` name + `aliases:` frontmatter);
 * titles are not names. First note wins a shared name. */
export function buildEntityIndex(notes: NovelNoteSummary[], work: string): Map<string, string> {
  const map = new Map<string, string>()
  for (const n of notes) {
    if (n.path.split('/')[0] !== work) continue
    for (const name of n.aliases ?? []) {
      if (name && !map.has(name)) map.set(name, n.path)
    }
  }
  return map
}
