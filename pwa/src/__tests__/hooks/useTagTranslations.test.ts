/**
 * useTagTranslations — Vitest test suite
 *
 * Covers:
 *   key derivation  — null key when tags array is empty (no fetch issued)
 *   key derivation  — non-empty input produces array key ['tags/translations', sorted-csv]
 *   key derivation  — tags are sorted before joining (cache hits are order-independent)
 *   fetcher         — calls api.tags.getTranslations with the original tags array
 *   fetcher         — not called when tags array is empty
 *   SWR config      — revalidateOnFocus is false
 *   SWR config      — revalidateOnReconnect is false
 *   SWR config      — dedupingInterval is 86400000 (24 h)
 *   return value    — passes through SWR data unchanged
 *
 * Note on vi.hoisted():
 *   vi.mock() factories are hoisted before const declarations. Variables used
 *   inside a factory must be created with vi.hoisted() to be available at hoist-time.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// ── Hoisted mock helpers ──────────────────────────────────────────────

const { mockGetTranslations } = vi.hoisted(() => ({
  mockGetTranslations: vi.fn(),
}))

// ── LocaleProvider mock ───────────────────────────────────────────────

vi.mock('@/components/LocaleProvider', () => ({
  useLocale: () => ({ locale: 'zh-TW' as const, setLocale: vi.fn() }),
}))

// ── api mock ─────────────────────────────────────────────────────────

vi.mock('@/lib/api', () => ({
  api: {
    tags: {
      getTranslations: mockGetTranslations,
    },
  },
}))

// ── swr mock ─────────────────────────────────────────────────────────

interface SwrCall {
  key: unknown
  fetcher: (() => unknown) | null
  options: Record<string, unknown>
}

const swrCalls: SwrCall[] = []
const MOCK_SWR_RETURN = { data: undefined, isLoading: false, error: undefined }

const { mockUseSWR } = vi.hoisted(() => ({
  mockUseSWR: vi.fn(
    (key: unknown, fetcher: (() => unknown) | null, options: Record<string, unknown> = {}) => {
      swrCalls.push({ key, fetcher, options })
      return MOCK_SWR_RETURN
    },
  ),
}))

vi.mock('swr', () => ({
  default: mockUseSWR,
  mutate: vi.fn(),
}))

// ── Import hook after mocks ───────────────────────────────────────────

import { useTagTranslations } from '@/hooks/useTagTranslations'

// ── Setup ─────────────────────────────────────────────────────────────

beforeEach(() => {
  vi.clearAllMocks()
  swrCalls.length = 0
  mockGetTranslations.mockResolvedValue({ 'artist:bob': 'Bob', 'parody:foo': 'Foo' })
})

afterEach(() => {
  vi.clearAllMocks()
})

function lastCall(): SwrCall {
  return swrCalls[swrCalls.length - 1]
}

// ── Tests ─────────────────────────────────────────────────────────────

describe('useTagTranslations — SWR key derivation', () => {
  it('should pass a null key to useSWR when the tags array is empty', () => {
    useTagTranslations([])
    expect(lastCall().key).toBeNull()
  })

  it('should pass an array key when the tags array is non-empty', () => {
    useTagTranslations(['artist:bob'])
    expect(Array.isArray(lastCall().key)).toBe(true)
  })

  it('should use "tags/translations" as the first element of the key', () => {
    useTagTranslations(['artist:bob'])
    expect((lastCall().key as [string, string])[0]).toBe('tags/translations')
  })

  it('should use the derived language as the second element of the key', () => {
    useTagTranslations(['artist:bob'])
    expect((lastCall().key as [string, string, string])[1]).toBe('zh')
  })

  it('should join sorted tags with "," as the third element of the key', () => {
    useTagTranslations(['parody:foo', 'artist:bob'])
    // sorted: ['artist:bob', 'parody:foo']
    expect((lastCall().key as [string, string, string])[2]).toBe('artist:bob,parody:foo')
  })

  it('should produce the same cache key regardless of input order', () => {
    useTagTranslations(['parody:foo', 'artist:bob'])
    const keyA = (lastCall().key as [string, string, string])[2]

    swrCalls.length = 0

    useTagTranslations(['artist:bob', 'parody:foo'])
    const keyB = (lastCall().key as [string, string, string])[2]

    expect(keyA).toBe(keyB)
  })
})

describe('useTagTranslations — fetcher', () => {
  it('should call api.tags.getTranslations with the original tags when the fetcher runs', async () => {
    const tags = ['artist:bob', 'parody:foo']
    useTagTranslations(tags)

    expect(lastCall().fetcher).not.toBeNull()

    await lastCall().fetcher!()

    expect(mockGetTranslations).toHaveBeenCalledOnce()
    expect(mockGetTranslations).toHaveBeenCalledWith(tags, 'zh')
  })

  it('should not invoke api.tags.getTranslations when tags array is empty', () => {
    useTagTranslations([])
    // With a null key SWR will never call the fetcher.
    expect(mockGetTranslations).not.toHaveBeenCalled()
  })
})

describe('useTagTranslations — SWR configuration', () => {
  it('should set revalidateOnFocus to false', () => {
    useTagTranslations(['artist:bob'])
    expect(lastCall().options.revalidateOnFocus).toBe(false)
  })

  it('should set revalidateOnReconnect to false', () => {
    useTagTranslations(['artist:bob'])
    expect(lastCall().options.revalidateOnReconnect).toBe(false)
  })

  it('should set dedupingInterval to 86400000 (24 hours)', () => {
    useTagTranslations(['artist:bob'])
    expect(lastCall().options.dedupingInterval).toBe(86_400_000)
  })
})

describe('useTagTranslations — return value', () => {
  it('should return the object provided by useSWR', () => {
    const result = useTagTranslations(['artist:bob'])
    expect(result).toBe(MOCK_SWR_RETURN)
  })

  it('should pass through resolved translation data from SWR', () => {
    const translations = { 'artist:bob': 'Bob', 'parody:foo': 'Foo' }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    mockUseSWR.mockReturnValueOnce({
      data: translations,
      isLoading: false,
      error: undefined,
    } as any)

    const result = useTagTranslations(['artist:bob', 'parody:foo'])
    expect(result.data).toEqual(translations)
  })
})
