import nextConfig from 'eslint-config-next'
import nextCoreWebVitals from 'eslint-config-next/core-web-vitals'
import nextTypescript from 'eslint-config-next/typescript'
import prettier from 'eslint-config-prettier'

export default [
  ...nextConfig,
  ...nextCoreWebVitals,
  ...nextTypescript,
  prettier,
  {
    rules: {
      // TypeScript
      '@typescript-eslint/no-unused-vars': [
        'warn',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      '@typescript-eslint/no-explicit-any': 'warn',

      // next/image is not usable for proxied/dynamic EH images with crossOrigin requirements
      '@next/next/no-img-element': 'off',

      // Legitimate pattern: reset derived state when deps change (synchronous within effect)
      'react-hooks/set-state-in-effect': 'off',

      // useCallback referencing itself via closure is valid; false positive in ws.ts
      'react-hooks/immutability': 'off',

      // False positive on manual useCallback deps that are correct
      'react-hooks/preserve-manual-memoization': 'off',
    },
  },
  {
    // A bare router.back() is a no-op on a one-entry history (share link, new
    // tab, PWA relaunch) and skips the nav-tab restore climb; on chrome-less
    // routes like the Reader that traps the user (FE-T3, FE-T18).
    // lib/navBack.ts is the one place that decides when history back is safe.
    files: ['src/**/*.{ts,tsx}'],
    ignores: ['src/lib/navBack.ts'],
    rules: {
      'no-restricted-syntax': [
        'error',
        {
          selector:
            "CallExpression[callee.property.name='back']:matches([callee.object.name=/[rR]outer$/], [callee.object.property.name=/[rR]outer$/], [callee.object.callee.name='useRouter'])",
          message:
            "Bare router.back() does nothing on a one-entry history (share link, new tab, PWA relaunch). Use smartBack(router, fallback) from '@/lib/navBack'.",
        },
        {
          selector: "VariableDeclarator[init.callee.name='useRouter'] > ObjectPattern > Property[key.name='back']",
          message:
            "Don't pull back() out of useRouter(): a bare back does nothing on a one-entry history. Use smartBack(router, fallback) from '@/lib/navBack'.",
        },
      ],
    },
  },
]
