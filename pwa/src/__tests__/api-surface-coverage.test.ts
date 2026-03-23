/**
 * API Surface Coverage — static analysis test
 *
 * Detects API client methods in api.ts that are never called from any
 * frontend component, hook, or page. This prevents the situation where
 * a backend endpoint has a client method but no UI wiring.
 *
 * How it works:
 * 1. Import the `api` object and enumerate all namespace.method paths
 * 2. Read all .ts/.tsx source files (excluding api.ts itself and tests)
 * 3. For each method, check if `namespace.method` appears in any source file
 * 4. Methods in the ALLOWED_UNUSED list are exempt (intentionally external-only)
 * 5. Test fails if any method is unused and not in the allowlist
 */

import { describe, it, expect } from 'vitest'
import { api } from '@/lib/api'
import { readdirSync, readFileSync, statSync } from 'fs'
import { join } from 'path'

// ── Allowlist: methods intentionally not called from frontend ──────────
// These serve external consumers (RSS readers, OPDS clients, API tokens, etc.)
// or are URL builders used inline (not via api.X.Y() call pattern).
const ALLOWED_UNUSED: Set<string> = new Set([
  // URL builders — used as string in img src / href, not as api.X.Y() calls
  'eh.thumbProxyUrl',
  'pixiv.imageProxyUrl',
  'export.kohyaUrl',

  // Backend-only: setSiteCredential covers this use case
  'settings.setGenericCookie',

  // TODO: wire these to UI — backend ready, frontend pending
  'settings.ehLogin',             // credentials page: username/password login
  'settings.checkEhCookies',      // credentials page: cookie validation button
  'tags.batchImportTranslations',  // admin: bulk tag translation import
  'import_.rescanGallery',         // library detail: per-gallery rescan button
])

// ── Source file scanner ───────────────────────────────────────────────

const SRC_DIR = join(__dirname, '..')
const EXCLUDED_DIRS = new Set(['__tests__', 'node_modules', '.next'])
const EXCLUDED_FILES = new Set(['api.ts'])

function collectSourceFiles(dir: string): string[] {
  const files: string[] = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (EXCLUDED_DIRS.has(entry)) continue
    const stat = statSync(full)
    if (stat.isDirectory()) {
      files.push(...collectSourceFiles(full))
    } else if (/\.(ts|tsx)$/.test(entry) && !EXCLUDED_FILES.has(entry)) {
      files.push(full)
    }
  }
  return files
}

function loadSourceContent(): string {
  const files = collectSourceFiles(SRC_DIR)
  return files.map((f) => readFileSync(f, 'utf-8')).join('\n')
}

// ── Extract all api methods ───────────────────────────────────────────

interface ApiMethod {
  namespace: string
  method: string
  path: string // "namespace.method"
}

function extractApiMethods(): ApiMethod[] {
  const methods: ApiMethod[] = []
  for (const [ns, obj] of Object.entries(api)) {
    if (typeof obj !== 'object' || obj === null) continue
    for (const [method, value] of Object.entries(obj as Record<string, unknown>)) {
      if (typeof value === 'function' || typeof value === 'object') {
        methods.push({ namespace: ns, method, path: `${ns}.${method}` })
      }
    }
  }
  return methods
}

// ── Test ──────────────────────────────────────────────────────────────

describe('API surface coverage', () => {
  const allMethods = extractApiMethods()
  const sourceContent = loadSourceContent()

  it('should have discovered API methods', () => {
    expect(allMethods.length).toBeGreaterThan(100)
  })

  it('every API method is either used in source or explicitly allowed unused', () => {
    const unused: string[] = []

    for (const m of allMethods) {
      if (ALLOWED_UNUSED.has(m.path)) continue

      // Check for usage patterns:
      // - api.namespace.method (direct call)
      // - namespace.method (destructured or aliased)
      // - .method( after a variable holding the namespace
      const patterns = [
        `${m.namespace}.${m.method}`,  // e.g. "library.getGalleries"
        `.${m.method}(`,               // e.g. ".getGalleries("
      ]

      const found = patterns.some((p) => sourceContent.includes(p))
      if (!found) {
        unused.push(m.path)
      }
    }

    if (unused.length > 0) {
      const msg = [
        `${unused.length} API method(s) defined in api.ts but never used in frontend source:`,
        '',
        ...unused.map((u) => `  - api.${u}`),
        '',
        'Fix by either:',
        '  1. Wiring the method to a UI element (button, page, hook)',
        '  2. Adding it to ALLOWED_UNUSED in api-surface-coverage.test.ts with a comment',
        '  3. Removing the dead method from api.ts',
      ].join('\n')
      expect.fail(msg)
    }
  })

  it('every ALLOWED_UNUSED entry still exists in the API', () => {
    const allPaths = new Set(allMethods.map((m) => m.path))
    const stale = [...ALLOWED_UNUSED].filter((p) => !allPaths.has(p))

    if (stale.length > 0) {
      expect.fail(
        `ALLOWED_UNUSED contains entries that no longer exist in api.ts:\n${stale.map((s) => `  - ${s}`).join('\n')}\nRemove them from the allowlist.`,
      )
    }
  })
})
