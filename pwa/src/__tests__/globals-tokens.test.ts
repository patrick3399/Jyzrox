import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

const css = readFileSync(path.resolve(__dirname, '../app/globals.css'), 'utf8')

function block(selector: string): string {
  const start = css.indexOf(`${selector} {`)
  expect(start, `${selector} block`).toBeGreaterThanOrEqual(0)
  return css.slice(start, css.indexOf('}', start))
}

const THEMED = ['--color-danger', '--color-danger-hover', '--color-success', '--color-warning', '--color-overlay', '--shadow-popup']

describe('globals.css design tokens', () => {
  it.each([':root', '.dark', '.amoled'])('%s defines every themed token', (selector) => {
    const body = block(selector)
    for (const token of THEMED) expect(body, `${selector} ${token}`).toContain(`${token}:`)
  })

  it('registers vault-hover and vault-bg-secondary, which components already use', () => {
    const theme = block('@theme inline')
    expect(theme).toContain('--color-vault-hover:')
    expect(theme).toContain('--color-vault-bg-secondary:')
  })

  it('defines the three motion durations and the two easings', () => {
    for (const token of ['--motion-fast:', '--motion-base:', '--motion-slow:']) expect(block(':root')).toContain(token)
    for (const token of ['--ease-vault-out:', '--ease-vault-in-out:']) expect(block('@theme inline')).toContain(token)
  })

  it('keeps colour tokens in hex form (pwa/CLAUDE.md)', () => {
    for (const selector of [':root', '.dark', '.amoled']) {
      for (const match of block(selector).matchAll(/--color-(?:danger|success|warning|overlay)[\w-]*:\s*([^;]+);/g)) {
        expect(match[1].trim()).toMatch(/^#[0-9a-f]{6}([0-9a-f]{2})?$/i)
      }
    }
  })
})
