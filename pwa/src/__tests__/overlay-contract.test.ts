import { readdirSync, readFileSync, statSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

const SRC = path.resolve(__dirname, '..')

// Hand-rolled overlays allowed to stay: Reader (high-risk, own layers), the mobile
// nav drawer (Phase 1), the images full-screen panel, and the primitives themselves.
const ALLOW = [
  'components/Reader/',
  'components/MobileNav.tsx',
  'app/images/page.tsx',
  'components/ui/',
]

function files(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name)
    if (name === '__tests__' || name === 'node_modules') continue
    if (statSync(full).isDirectory()) files(full, out)
    else if (name.endsWith('.tsx')) out.push(full)
  }
  return out
}

const sources = [...files(path.join(SRC, 'app')), ...files(path.join(SRC, 'components'))]
  .map((file) => ({
    rel: path.relative(SRC, file).split(path.sep).join('/'),
    src: readFileSync(file, 'utf8'),
  }))
  .filter(({ rel }) => !ALLOW.some((prefix) => rel.startsWith(prefix)))

describe('overlay contract', () => {
  it('has no hand-rolled full-screen overlay outside components/ui', () => {
    expect(
      sources
        .filter(({ src }) => !src.includes("'@base-ui/react/") && /\bfixed inset-0\b/.test(src))
        .map(({ rel }) => rel),
    ).toEqual([])
  })

  it('has no createPortal outside components/ui', () => {
    expect(sources.filter(({ src }) => src.includes('createPortal')).map(({ rel }) => rel)).toEqual(
      [],
    )
  })
})
