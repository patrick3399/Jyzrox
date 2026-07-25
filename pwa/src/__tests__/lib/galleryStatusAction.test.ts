import { describe, expect, it } from 'vitest'

import { galleryStatusAction } from '@/lib/galleryUtils'

/**
 * Regression: a `partial` gallery offered no way to trigger a repair.
 *
 * The detail page gated its "update" button on
 * `pagesOutdated && download_status === 'complete'`, so the one status that by
 * definition is missing content was the only status excluded from the action.
 * Galleries sat at `partial` for months with nothing clickable in the UI.
 */
describe('galleryStatusAction', () => {
  const base = { hasSourceUrl: true, pagesOutdated: false } as const

  it('offers repair for a partial gallery even when no page diff was detected', () => {
    // The bug: pagesOutdated is false here, and the old gate additionally
    // required status === 'complete'. Both conditions excluded partial.
    expect(galleryStatusAction({ ...base, downloadStatus: 'partial' })).toEqual({ kind: 'repair' })
  })

  it('offers repair for a partial gallery that also reports a page diff', () => {
    expect(
      galleryStatusAction({ ...base, downloadStatus: 'partial', pagesOutdated: true }),
    ).toEqual({ kind: 'repair' })
  })

  it('does not offer any action while a download is already running', () => {
    // Enqueuing a second run for a live download would race the active job.
    expect(galleryStatusAction({ ...base, downloadStatus: 'downloading' })).toEqual({ kind: 'none' })
    expect(
      galleryStatusAction({ ...base, downloadStatus: 'downloading', pagesOutdated: true }),
    ).toEqual({ kind: 'none' })
  })

  it('does not offer any action when the gallery has no source_url to re-enqueue', () => {
    expect(
      galleryStatusAction({ downloadStatus: 'partial', hasSourceUrl: false, pagesOutdated: false }),
    ).toEqual({ kind: 'none' })
    expect(
      galleryStatusAction({ downloadStatus: 'complete', hasSourceUrl: false, pagesOutdated: true }),
    ).toEqual({ kind: 'none' })
  })

  it('keeps the existing outdated flow for a complete gallery with a page diff', () => {
    expect(
      galleryStatusAction({ ...base, downloadStatus: 'complete', pagesOutdated: true }),
    ).toEqual({ kind: 'outdated' })
  })

  it('offers nothing for a complete gallery with no page diff', () => {
    expect(galleryStatusAction({ ...base, downloadStatus: 'complete' })).toEqual({ kind: 'none' })
  })

  it('offers nothing for proxy_only, which has no local content to repair', () => {
    expect(galleryStatusAction({ ...base, downloadStatus: 'proxy_only' })).toEqual({ kind: 'none' })
  })
})
