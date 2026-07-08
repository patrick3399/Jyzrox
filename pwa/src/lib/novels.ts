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
