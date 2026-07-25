import { describe, expect, it } from 'vitest'

import { galleryStatusAction } from '@/lib/galleryUtils'

/**
 * Regression: a `partial` gallery offered no way to trigger a repair.
 *
 * The detail page gated its "update" button on
 * `pagesOutdated && download_status === 'complete'`, so the one status that by
 * definition is missing content was the only status excluded from the action.
 * Galleries sat at `partial` for months with nothing clickable in the UI.
 *
 * Second regression, from the fix itself: folding "which badge" and "can we
 * enqueue" into one verdict dropped the badge whenever `source_url` was absent.
 * The two questions are independent — the badge reports what the gallery is,
 * the button reports what we can do about it.
 */
describe('galleryStatusAction', () => {
  const base = { hasSourceUrl: true, pagesOutdated: false } as const

  it('offers repair for a partial gallery even when no page diff was detected', () => {
    // The bug: pagesOutdated is false here, and the old gate additionally
    // required status === 'complete'. Both conditions excluded partial.
    expect(galleryStatusAction({ ...base, downloadStatus: 'partial' })).toEqual({
      kind: 'repair',
      canEnqueue: true,
    })
  })

  it('offers repair for a partial gallery that also reports a page diff', () => {
    expect(
      galleryStatusAction({ ...base, downloadStatus: 'partial', pagesOutdated: true }),
    ).toEqual({ kind: 'repair', canEnqueue: true })
  })

  it('does not offer any action while a download is already running', () => {
    // Enqueuing a second run for a live download would race the active job.
    expect(galleryStatusAction({ ...base, downloadStatus: 'downloading' })).toEqual({
      kind: 'none',
      canEnqueue: false,
    })
    expect(
      galleryStatusAction({ ...base, downloadStatus: 'downloading', pagesOutdated: true }),
    ).toEqual({ kind: 'none', canEnqueue: false })
  })

  it('still reports outdated without a source_url, but cannot enqueue', () => {
    // pagesOutdated comes from checkUpdate(source, source_id), which never
    // consults source_url — so this state is reachable, and collapsing it to
    // `none` silently hid the one signal telling the user pages are missing.
    expect(
      galleryStatusAction({ downloadStatus: 'complete', hasSourceUrl: false, pagesOutdated: true }),
    ).toEqual({ kind: 'outdated', canEnqueue: false })
  })

  it('still reports partial without a source_url, but cannot enqueue', () => {
    expect(
      galleryStatusAction({ downloadStatus: 'partial', hasSourceUrl: false, pagesOutdated: false }),
    ).toEqual({ kind: 'repair', canEnqueue: false })
  })

  it('keeps the existing outdated flow for a complete gallery with a page diff', () => {
    expect(
      galleryStatusAction({ ...base, downloadStatus: 'complete', pagesOutdated: true }),
    ).toEqual({ kind: 'outdated', canEnqueue: true })
  })

  it('offers nothing for a complete gallery with no page diff', () => {
    expect(galleryStatusAction({ ...base, downloadStatus: 'complete' })).toEqual({
      kind: 'none',
      canEnqueue: false,
    })
  })

  it('offers nothing for proxy_only, which has no local content to repair', () => {
    expect(galleryStatusAction({ ...base, downloadStatus: 'proxy_only' })).toEqual({
      kind: 'none',
      canEnqueue: false,
    })
  })
})
