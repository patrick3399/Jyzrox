import { describe, it, expect } from 'vitest'
import { buildEntityIndex } from '@/lib/novels'
import type { NovelNoteSummary } from '@/lib/api/novels'

const note = (path: string, title: string, aliases: string[]): NovelNoteSummary => ({
  path,
  title,
  note_type: null,
  aliases,
  frontmatter: {},
})

describe('buildEntityIndex', () => {
  it('links by server-derived aliases, never by the note title', () => {
    // Titles like `設定-甲v2` never occur in prose; linking by title found
    // nothing in the real corpus.
    const index = buildEntityIndex([note('作品A/Setting/設定-甲v2.md', '設定-甲v2', ['甲', '小甲'])], '作品A')
    expect([...index.keys()]).toEqual(['甲', '小甲'])
    expect(index.get('甲')).toBe('作品A/Setting/設定-甲v2.md')
  })

  it('ignores notes from other works', () => {
    const index = buildEntityIndex([note('作品B/Setting/設定-甲.md', '甲', ['甲'])], '作品A')
    expect(index.size).toBe(0)
  })

  it('keeps the first note for a name shared by two notes', () => {
    const index = buildEntityIndex(
      [note('作品A/Setting/設定-甲.md', 't', ['甲']), note('作品A/Setting/setting.md', 't', ['甲'])],
      '作品A',
    )
    expect(index.get('甲')).toBe('作品A/Setting/設定-甲.md')
  })
})
