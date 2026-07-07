import { describe, it, expect, vi } from 'vitest'
import { render } from '@testing-library/react'

vi.mock('@/lib/i18n', () => ({
  t: (key: string, vars?: Record<string, string | number>) =>
    vars ? `${key} ${Object.values(vars).join(' ')}` : key,
}))

import { MarkdownView } from '@/components/novels/MarkdownView'

describe('MarkdownView entity linking', () => {
  it('links a known entity name and leaves unknown text alone', () => {
    const { container } = render(
      <MarkdownView
        content={'張三走進來。陌生人也在。'}
        acts={[]}
        entityNames={['張三']}
        entityHrefFor={(n) => `/novels/note/${n}`}
      />,
    )
    const links = Array.from(container.querySelectorAll('a'))
    const target = links.find((a) => a.textContent === '張三')
    expect(target).toBeTruthy()
    expect(target?.getAttribute('href')).toBe('/novels/note/張三')
    expect(links.some((a) => a.textContent?.includes('陌生人'))).toBe(false)
  })

  it('links only the first occurrence of a repeated name', () => {
    const { container } = render(
      <MarkdownView
        content={'張三來了。後來張三又走了。'}
        acts={[]}
        entityNames={['張三']}
        entityHrefFor={(n) => `/novels/note/${n}`}
      />,
    )
    const nameLinks = Array.from(container.querySelectorAll('a')).filter((a) => a.textContent === '張三')
    expect(nameLinks).toHaveLength(1)
  })

  it('adds no links when no entity names are supplied', () => {
    const { container } = render(<MarkdownView content={'張三走進來。'} acts={[]} />)
    expect(container.querySelector('a')).toBeNull()
  })
})
