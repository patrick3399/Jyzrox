import { describe, expect, it } from 'vitest'
import { parseDatasetIds } from '@/lib/datasets'

describe('parseDatasetIds', () => {
  it('parses comma and whitespace separated positive IDs', () => {
    expect(parseDatasetIds('12, 34\n56  78')).toEqual([12, 34, 56, 78])
  })

  it('deduplicates IDs and rejects invalid values', () => {
    expect(parseDatasetIds('4, 4, -1, 0, nope, 2.5, 7')).toEqual([4, 7])
  })
})
