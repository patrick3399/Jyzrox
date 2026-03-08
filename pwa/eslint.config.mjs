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
]
