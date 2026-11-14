/**
 * Walking a settled gallery's pages. page_num can have holes (see
 * backend/CLAUDE.md, download completion contract), so these work on the sorted
 * list of page numbers that exist rather than on page_num arithmetic.
 */

export function sortPageNums(pageNums: number[]): number[] {
  return [...pageNums].sort((a, b) => a - b)
}

/** Index of the first page numbered `page` or higher; `pages.length` when none is. */
function firstIndexFrom(pages: readonly number[], page: number): number {
  let low = 0
  let high = pages.length
  while (low < high) {
    const mid = (low + high) >> 1
    if (pages[mid] < page) low = mid + 1
    else high = mid
  }
  return low
}

/** The page itself if it exists, else the next one, else the last page. */
export function nearestPage(pages: readonly number[], page: number): number {
  const index = firstIndexFrom(pages, page)
  return index < pages.length ? pages[index] : pages[pages.length - 1]
}

/** The page `delta` steps from `page`, stopping at either end of the list. */
export function stepPage(pages: readonly number[], page: number, delta: number): number {
  const index = firstIndexFrom(pages, page)
  // From inside a hole, `index` is already one step forward.
  const target = pages[index] === page || delta < 0 ? index + delta : index + delta - 1
  return pages[Math.max(0, Math.min(pages.length - 1, target))]
}

/** 1-based position of a page in the list. */
export function pagePosition(pages: readonly number[], page: number): number {
  return Math.min(firstIndexFrom(pages, page), pages.length - 1) + 1
}

/** Up to `ahead` page numbers after `page` and `behind` before it, nearest first. */
export function neighbouringPages(
  pages: readonly number[],
  page: number,
  ahead: number,
  behind: number,
): { after: number[]; before: number[] } {
  const index = firstIndexFrom(pages, page)
  const start = pages[index] === page ? index + 1 : index
  return {
    after: pages.slice(start, start + ahead),
    before: pages.slice(Math.max(0, index - behind), index).reverse(),
  }
}
