import { describe, it, expect } from 'vitest'
import { PAGE_REGISTRY, passesFeatureFlag } from '@/lib/pageRegistry'

describe('pageRegistry — feature-flag gating', () => {
  const novel = PAGE_REGISTRY.find((p) => p.href === '/novels')!

  it('novels page declares the novel_enabled feature flag', () => {
    expect(novel.featureFlag).toBe('novel_enabled')
  })

  it('hides a flagged page when its feature is disabled', () => {
    expect(passesFeatureFlag(novel, { novel_enabled: false })).toBe(false)
  })

  it('hides a flagged page while features are still loading (undefined)', () => {
    // Default-off: never flash a link that would 404 until we know it is on.
    expect(passesFeatureFlag(novel, undefined)).toBe(false)
  })

  it('shows a flagged page only when its feature is explicitly enabled', () => {
    expect(passesFeatureFlag(novel, { novel_enabled: true })).toBe(true)
  })

  it('always shows pages that declare no feature flag', () => {
    const dashboard = PAGE_REGISTRY.find((p) => p.href === '/')!
    expect(passesFeatureFlag(dashboard, undefined)).toBe(true)
    expect(passesFeatureFlag(dashboard, { novel_enabled: false })).toBe(true)
  })
})

describe('pageRegistry — training datasets', () => {
  it('exposes datasets to members through the sidebar and dashboard', () => {
    const datasets = PAGE_REGISTRY.find((page) => page.href === '/datasets')
    expect(datasets).toMatchObject({
      labelKey: 'nav.datasets',
      sidebar: true,
      dashboard: true,
      minRole: 'member',
    })
  })
})
