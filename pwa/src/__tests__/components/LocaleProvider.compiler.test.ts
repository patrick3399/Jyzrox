/**
 * LocaleProvider.compiler.test.ts
 *
 * Regression guard for the React Compiler locale-update bug.
 *
 * The project builds with React Compiler (`reactCompiler: true` in
 * next.config.ts). The compiler memoizes the LocaleContext value object on the
 * fields it references. LocaleProvider re-renders after a lazily-loaded
 * dictionary resolves by bumping a `dictionaryVersion` state — but if that
 * value is NOT part of the context value, the compiler reuses the cached value
 * object and cached element, React bails out of the subtree, and every
 * useLocale() consumer keeps showing the pre-load (English fallback) strings.
 *
 * Vitest does not run React Compiler, so a rendering test cannot reproduce this.
 * Instead we run the actual compiler over the source and assert that the
 * memoized context-value block depends on `dictionaryVersion`.
 */

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'
import babel from '@babel/core'
import reactCompiler from 'babel-plugin-react-compiler'

const source = readFileSync(resolve(process.cwd(), 'src/components/LocaleProvider.tsx'), 'utf8')
const layoutShellSource = readFileSync(
  resolve(process.cwd(), 'src/components/LayoutShell.tsx'),
  'utf8',
)

function compile(src: string): string {
  const out = babel.transformSync(src, {
    filename: 'LocaleProvider.tsx',
    parserOpts: { plugins: ['typescript', 'jsx'] },
    plugins: [[reactCompiler, { target: '19' }]],
    configFile: false,
    babelrc: false,
  })
  if (!out?.code) throw new Error('React Compiler produced no output')
  return out.code
}

describe('LocaleProvider under React Compiler', () => {
  it('re-renders consumers after a dictionary load (value memo depends on dictionaryVersion)', () => {
    const compiled = compile(source)

    // The compiler emits a guarded assignment for the context value object.
    // Locate the block that builds `{ locale, setLocale, isAutomatic, ... }`.
    const valueAssign = compiled.indexOf('setLocale,')
    expect(valueAssign).toBeGreaterThan(-1)

    // The guard immediately preceding that assignment must list dictionaryVersion
    // as a change dependency; otherwise the post-load bump is a no-op and the UI
    // stays on the English fallback.
    const guardStart = compiled.lastIndexOf('if (', valueAssign)
    const guard = compiled.slice(guardStart, valueAssign)
    expect(guard).toContain('dictionaryVersion')
  })

  it('keeps dictionaryVersion as a live read binding in the source', () => {
    // Regression: dropping the binding back to `const [, setDictionaryVersion]`
    // would let the compiler dead-code-eliminate the read and reintroduce the bug.
    expect(source).not.toMatch(/\[\s*,\s*setDictionaryVersion\s*\]/)
    expect(source).toMatch(/const \[dictionaryVersion, setDictionaryVersion\] = useState\(0\)/)
    expect(source).toContain('dictionaryVersion }')
  })

  it('invalidates the app shell when a lazy dictionary finishes loading', () => {
    expect(layoutShellSource).toMatch(/const \{\s*locale,\s*dictionaryVersion\s*\} = useLocale\(\)/)
    expect(layoutShellSource).toContain('key={`${locale}:${dictionaryVersion}`}')
  })
})
