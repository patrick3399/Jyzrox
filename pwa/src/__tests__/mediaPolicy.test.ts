import { describe, it, expect } from 'vitest'
import {
  DEFAULT_MEDIA_POLICY,
  isDefaultMediaPolicy,
  mediaPolicyFromOptions,
  parseMaxFiles,
  withMediaPolicy,
} from '@/lib/mediaPolicy'

describe('isDefaultMediaPolicy', () => {
  it('test_isDefaultMediaPolicy_defaultPolicy_returnsTrue', () => {
    expect(isDefaultMediaPolicy(DEFAULT_MEDIA_POLICY)).toBe(true)
  })

  it('test_isDefaultMediaPolicy_videosExcluded_returnsFalse', () => {
    expect(isDefaultMediaPolicy({ max_files: null, include_videos: false })).toBe(false)
  })

  it('test_isDefaultMediaPolicy_maxFilesSet_returnsFalse', () => {
    expect(isDefaultMediaPolicy({ max_files: 20, include_videos: true })).toBe(false)
  })
})

describe('mediaPolicyFromOptions', () => {
  it('test_mediaPolicyFromOptions_noMediaKey_returnsDefault', () => {
    expect(mediaPolicyFromOptions(undefined)).toEqual(DEFAULT_MEDIA_POLICY)
    expect(mediaPolicyFromOptions({ fanbox: {} })).toEqual(DEFAULT_MEDIA_POLICY)
  })

  it('test_mediaPolicyFromOptions_storedPolicy_isReadBack', () => {
    expect(mediaPolicyFromOptions({ media: { max_files: 200, include_videos: false } })).toEqual({
      max_files: 200,
      include_videos: false,
    })
  })

  it('test_mediaPolicyFromOptions_malformedMedia_fallsBackToDefault', () => {
    expect(mediaPolicyFromOptions({ media: 'all' })).toEqual(DEFAULT_MEDIA_POLICY)
    expect(mediaPolicyFromOptions({ media: { max_files: 0 } })).toEqual(DEFAULT_MEDIA_POLICY)
  })

  it('test_mediaPolicyFromOptions_returnsFreshObject_notTheSharedDefault', () => {
    expect(mediaPolicyFromOptions(undefined)).not.toBe(DEFAULT_MEDIA_POLICY)
  })
})

describe('withMediaPolicy', () => {
  it('withMediaPolicy_preserves_fanbox_key_when_setting_media', () => {
    const fanbox = { content: 'free_only' }
    const options = { fanbox }
    const result = withMediaPolicy(options, { max_files: 50, include_videos: false })

    expect(result.fanbox).toBe(fanbox)
    expect(result.media).toEqual({ max_files: 50, include_videos: false })
    // Input must not be mutated.
    expect(result).not.toBe(options)
    expect(options).toEqual({ fanbox })
  })

  it('withMediaPolicy_removes_media_key_when_default', () => {
    const options = {
      fanbox: { content: 'free_only' },
      media: { max_files: 5, include_videos: true },
    }
    const result = withMediaPolicy(options, { ...DEFAULT_MEDIA_POLICY })

    expect('media' in result).toBe(false)
    expect(result.fanbox).toEqual({ content: 'free_only' })
    // Input must not be mutated.
    expect(options.media).toEqual({ max_files: 5, include_videos: true })
  })

  it('withMediaPolicy_undefinedOptions_defaultPolicy_returnsEmptyObject', () => {
    expect(withMediaPolicy(undefined, DEFAULT_MEDIA_POLICY)).toEqual({})
  })

  it('withMediaPolicy_undefinedOptions_nonDefaultPolicy_setsMedia', () => {
    expect(withMediaPolicy(undefined, { max_files: null, include_videos: false })).toEqual({
      media: { max_files: null, include_videos: false },
    })
  })
})

describe('parseMaxFiles', () => {
  it('parseMaxFiles_emptyString_meansNoCap', () => {
    expect(parseMaxFiles('')).toBeNull()
  })

  it('parseMaxFiles_positiveInteger_returnsNumber', () => {
    expect(parseMaxFiles('200')).toBe(200)
    expect(parseMaxFiles('1')).toBe(1)
    expect(parseMaxFiles('100000')).toBe(100000)
  })

  it.each(['0', '-1', '1.5', '100001', 'abc'])(
    'parseMaxFiles_rejects_zero_negative_and_fraction: %j is invalid',
    (input) => {
      expect(parseMaxFiles(input)).toBeUndefined()
    },
  )
})
