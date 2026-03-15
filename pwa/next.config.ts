import type { NextConfig } from 'next'
import { createRequire } from 'module'

const require = createRequire(import.meta.url)
const nextPkg = require('next/package.json')

const config: NextConfig = {
  output: 'standalone',
  env: {
    NEXT_PUBLIC_NEXTJS_VERSION: nextPkg.version,
  },
  // Explicitly run ESLint during `next build` so that react-hooks/rules-of-hooks
  // violations (e.g. hooks after early returns, React error #310) are caught at
  // build time and not only at runtime.
  eslint: {
    ignoreDuringBuilds: false,
  },
}

export default config
