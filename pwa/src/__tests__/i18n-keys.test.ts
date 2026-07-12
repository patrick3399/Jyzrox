/**
 * i18n-keys.test.ts — Vitest suite
 *
 * Test 1: All t() call sites reference keys that exist in en.ts
 * Test 2: (informational) Detect unused keys in en.ts
 * Test 3: Every locale file has full key parity with en.ts
 * Test 4: No orphan keys in locale files
 * Test 5: {param} placeholders match en.ts in every translation
 *
 * File scanning uses Node.js fs/path — no mocking required.
 * Only string-literal keys are checked; dynamic / template-literal
 * keys (e.g. t(variable), t(`foo.${bar}`)) are intentionally skipped.
 */

import { describe, it, expect } from 'vitest'
import * as fs from 'fs'
import * as path from 'path'
import { fileURLToPath } from 'url'

import en from '../lib/i18n/en'
import zhTW from '../lib/i18n/zh-TW'
import zhCN from '../lib/i18n/zh-CN'
import ja from '../lib/i18n/ja'
import ko from '../lib/i18n/ko'

// ---------------------------------------------------------------------------
// Path resolution
// ---------------------------------------------------------------------------

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

// pwa/src/
const SRC_ROOT = path.resolve(__dirname, '..')

// ---------------------------------------------------------------------------
// File discovery helpers
// ---------------------------------------------------------------------------

/** Recursively collect all .ts / .tsx files under `dir`, excluding `skip`. */
function collectSourceFiles(dir: string, skipDirs: string[]): string[] {
  const results: string[] = []

  function walk(current: string) {
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const full = path.join(current, entry.name)
      if (entry.isDirectory()) {
        const rel = path.relative(SRC_ROOT, full)
        if (skipDirs.some((s) => rel === s || rel.startsWith(s + path.sep))) continue
        walk(full)
      } else if (entry.isFile() && /\.(ts|tsx)$/.test(entry.name)) {
        results.push(full)
      }
    }
  }

  walk(dir)
  return results
}

// ---------------------------------------------------------------------------
// Key extraction helpers
// ---------------------------------------------------------------------------

/**
 * Extract all string-literal i18n keys referenced by t() calls in `source`.
 *
 * Handles:
 *   t('some.key')
 *   t("some.key")
 *   t('some.key', { ... })
 *   Multi-line calls:
 *     t(
 *       'some.key'
 *     )
 *
 * Skips:
 *   t(variable)
 *   t(`template.${literal}`)
 */
function extractKeys(source: string): string[] {
  // Match t( followed by optional whitespace/newlines then a quoted string literal.
  // Capture group 1 = the key content (inside quotes).
  const regex = /\bt\s*\(\s*(['"])([^'"]+)\1/g
  const keys: string[] = []
  let match: RegExpExecArray | null
  while ((match = regex.exec(source)) !== null) {
    keys.push(match[2])
  }
  return keys
}

// ---------------------------------------------------------------------------
// Build the full map: key → files that reference it
// ---------------------------------------------------------------------------

interface KeyUsage {
  key: string
  files: string[]
}

function buildKeyUsageMap(): Map<string, string[]> {
  const skipDirs = ['__tests__', 'lib/i18n']
  const files = collectSourceFiles(SRC_ROOT, skipDirs)

  const usage = new Map<string, string[]>()

  for (const file of files) {
    const source = fs.readFileSync(file, 'utf-8')
    const keys = extractKeys(source)
    for (const key of keys) {
      const rel = path.relative(SRC_ROOT, file)
      if (!usage.has(key)) usage.set(key, [])
      const list = usage.get(key)!
      if (!list.includes(rel)) list.push(rel)
    }
  }

  return usage
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('i18n key consistency', () => {
  // Build once for the entire suite.
  const keyUsageMap = buildKeyUsageMap()
  const enKeys = new Set(Object.keys(en))

  it('all t() call sites reference keys that exist in en.ts', () => {
    const missing: KeyUsage[] = []

    for (const [key, files] of keyUsageMap) {
      if (!enKeys.has(key)) {
        missing.push({ key, files })
      }
    }

    if (missing.length > 0) {
      const lines = missing.map(({ key, files }) => `  - ${key} (used in ${files.join(', ')})`)
      const message = `Missing i18n keys found:\n${lines.join('\n')}`
      expect.fail(message)
    }
  })

  it('en.ts has no unused keys (informational)', () => {
    const allReferencedKeys = new Set(keyUsageMap.keys())
    const unused: string[] = []

    for (const key of enKeys) {
      if (!allReferencedKeys.has(key)) {
        unused.push(key)
      }
    }

    if (unused.length > 0) {
      console.log(
        `[i18n] Potentially unused keys in en.ts (${unused.length}):\n` +
          unused.map((k) => `  - ${k}`).join('\n'),
      )
    }

    // Soft assertion: warn but do not fail, because keys may be constructed
    // dynamically at runtime (e.g. `t(\`common.locale.${locale}\`)`).
    expect(unused.length).toBeGreaterThanOrEqual(0)
  })

  const locales: Record<string, Record<string, string>> = {
    'zh-TW': zhTW,
    'zh-CN': zhCN,
    ja,
    ko,
  }

  it('all locale files contain every key from en.ts', () => {
    // Locales were fully caught up with en.ts; keep them that way.
    // When adding a key to en.ts, add its translation to every locale file.
    for (const [locale, dict] of Object.entries(locales)) {
      const missingKeys = Object.keys(en).filter((key) => !(key in dict))
      expect(missingKeys, `${locale} is missing keys from en.ts`).toEqual([])
    }
  })

  it('locale files have no orphan keys absent from en.ts', () => {
    for (const [locale, dict] of Object.entries(locales)) {
      const orphanKeys = Object.keys(dict).filter((key) => !(key in en))
      expect(orphanKeys, `${locale} has keys that do not exist in en.ts`).toEqual([])
    }
  })

  it('translations use the same {param} placeholders as en.ts', () => {
    const params = (value: string) => (value.match(/\{[a-zA-Z0-9_]+\}/g) ?? []).sort().join(',')

    for (const [locale, dict] of Object.entries(locales)) {
      const mismatched = Object.entries(dict)
        .filter(([key, value]) => key in en && params(value) !== params(en[key]))
        .map(([key]) => `${key} (en: "${params(en[key])}" vs ${locale}: "${params(dict[key])}")`)
      expect(mismatched, `${locale} has placeholder mismatches against en.ts`).toEqual([])
    }
  })
})
