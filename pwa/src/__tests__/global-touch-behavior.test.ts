import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const readSource = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8')

describe('global touch behavior', () => {
  it('keeps browser viewport zoom disabled while the reader owns image zoom', () => {
    const layout = readSource('src/app/layout.tsx')

    expect(layout).toMatch(/maximumScale:\s*1/)
    expect(layout).toMatch(/userScalable:\s*false/)
  })

  it('provides an opt-in long-press suppression utility', () => {
    const css = readSource('src/app/globals.css')

    expect(css).toMatch(/\.app-touch-controls[\s\S]*-webkit-touch-callout:\s*none/)
    expect(css).toMatch(/\.app-touch-controls[\s\S]*-webkit-user-select:\s*none/)
    expect(css).toMatch(/\.app-touch-controls[\s\S]*-webkit-user-drag:\s*none/)
  })
})
