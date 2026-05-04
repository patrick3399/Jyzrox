import type { NextConfig } from 'next'
import { createRequire } from 'module'
import { dirname } from 'path'
import { fileURLToPath } from 'url'

const require = createRequire(import.meta.url)
const nextPkg = require('next/package.json')
const appRoot = dirname(fileURLToPath(import.meta.url))

const config: NextConfig = {
  output: 'standalone',
  reactCompiler: true,
  turbopack: {
    root: appRoot,
  },
  env: {
    NEXT_PUBLIC_NEXTJS_VERSION: nextPkg.version,
  },
}

export default config
