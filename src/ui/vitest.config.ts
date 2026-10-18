import path from 'node:path'
import { fileURLToPath } from 'node:url'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const here = path.dirname(fileURLToPath(import.meta.url))

// Tests live in ../tests/ui, so the test root is the project root and their
// bare imports are pointed at ui/node_modules.
export default defineConfig({
  root: path.resolve(here, '../..'),
  cacheDir: path.join(here, 'node_modules/.vite'),
  plugins: [react()],
  resolve: {
    alias: [
      { find: /^@testing-library\/(react|user-event)$/, replacement: path.join(here, 'node_modules/@testing-library/$1') },
      { find: /^(react|react-dom)(\/.*)?$/, replacement: path.join(here, 'node_modules/$1$2') },
    ],
  },
  server: { fs: { allow: [path.resolve(here, '../..')] } },
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['tests/ui/**/*.test.{ts,tsx}'],
    globalSetup: ['tests/ui/globalSetup.ts'],
    setupFiles: ['tests/ui/setup.ts'],
    // Walk-through tests make several real API calls per hop.
    testTimeout: 20000,
  },
})
