import type { NextConfig } from 'next'

// eslint-disable-next-line @typescript-eslint/no-require-imports
const nextPkg = require('next/package.json')

const config: NextConfig = {
  output: 'standalone',
  env: {
    NEXT_PUBLIC_NEXTJS_VERSION: nextPkg.version,
  },
}

export default config
