import path from 'path'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  esbuild: {
    jsx: 'automatic',
  },
  test: {
    environment: 'jsdom',
    // Node 25+ ships a native Web Storage global that shadows jsdom's
    // localStorage/sessionStorage; disable it so tests use jsdom's.
    execArgv: ['--no-experimental-webstorage'],
    globals: false,
    setupFiles: ['./src/__tests__/setup.ts'],
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
})
