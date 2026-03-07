import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./src/**/*.{ts,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        vault: {
          bg: '#0a0a0a',
          card: '#111111',
          border: '#2a2a2a',
          accent: '#6366f1',
        },
      },
    },
  },
  plugins: [],
}

export default config
