import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  mutate: vi.fn(),
  setFeature: vi.fn(),
}))

vi.mock('swr', () => ({ mutate: mocks.mutate }))
vi.mock('@/lib/api', () => ({
  api: {
    settings: {
      getFeatures: vi.fn(),
      setFeature: mocks.setFeature,
    },
  },
}))

import { FEATURE_SETTINGS_SWR_KEY, setFeatureAndSyncCache } from '@/lib/featureSettings'

beforeEach(() => {
  vi.clearAllMocks()
  mocks.setFeature.mockResolvedValue({ feature: 'novel_enabled', enabled: true })
  mocks.mutate.mockResolvedValue(undefined)
})

describe('feature settings cache', () => {
  it('updates the shared feature cache after the server accepts a toggle', async () => {
    await setFeatureAndSyncCache('novel_enabled', true)

    expect(mocks.setFeature).toHaveBeenCalledWith('novel_enabled', true)
    expect(mocks.mutate).toHaveBeenCalledWith(
      FEATURE_SETTINGS_SWR_KEY,
      expect.any(Function),
      { revalidate: false },
    )

    const updater = mocks.mutate.mock.calls[0][1]
    expect(updater({ novel_enabled: false, trash_enabled: true })).toEqual({
      novel_enabled: true,
      trash_enabled: true,
    })
  })

  it('does not publish a cache update when the server mutation fails', async () => {
    mocks.setFeature.mockRejectedValueOnce(new Error('failed'))

    await expect(setFeatureAndSyncCache('novel_enabled', true)).rejects.toThrow('failed')
    expect(mocks.mutate).not.toHaveBeenCalled()
  })
})
