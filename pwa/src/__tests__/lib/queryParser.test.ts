import { describe, it, expect } from 'vitest'
import { buildQuery, parseQuery, tagNameSearchTerm } from '@/lib/queryParser'

describe('tagNameSearchTerm', () => {
  it('test_tagNameSearchTerm_multiWordName_isQuotedSoItStaysOneToken', () => {
    expect(tagNameSearchTerm('jun ye tako')).toBe('"jun ye tako"')
  })

  it('test_tagNameSearchTerm_singleWordName_isUnchanged', () => {
    expect(tagNameSearchTerm('pantyhose')).toBe('pantyhose')
  })

  it('test_tagNameSearchTerm_multiWordName_parsesAsSingleBareTerm', () => {
    const parsed = parseQuery(tagNameSearchTerm('jun ye tako'))
    expect(parsed.nameOnlyTags).toEqual(['"jun ye tako"'])
    expect(buildQuery(parsed)).toBe('"jun ye tako"')
  })
})
