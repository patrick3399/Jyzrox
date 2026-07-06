/** URL for a chapter reader page. `path` is the repo-relative `.md` path. */
export function novelChapterHref(work: string, chapter: string, path: string): string {
  return `/novels/${encodeURIComponent(work)}/${encodeURIComponent(chapter)}?path=${encodeURIComponent(path)}`
}
