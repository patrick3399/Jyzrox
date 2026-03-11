import type { NextConfig } from 'next'
import { createRequire } from 'module'

const require = createRequire(import.meta.url)
const nextPkg = require('next/package.json')

const config: NextConfig = {
  output: 'standalone',
  env: {
    NEXT_PUBLIC_NEXTJS_VERSION: nextPkg.version,
  },
}

export default config
