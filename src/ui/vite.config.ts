import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const apiTarget = process.env.LINEAGE_API_URL ?? 'http://127.0.0.1:8000'
const apiPrefixes = ['/projects', '/targets', '/lineage', '/steps', '/relations', '/catalog']
// The UI talks to the API under this prefix (matches the other deployment's reverse proxy).
const uiApiPrefix = '/data-lineage/api'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      ...Object.fromEntries(apiPrefixes.map((p) => [p, { target: apiTarget, changeOrigin: true }])),
      [uiApiPrefix]: {
        target: apiTarget,
        changeOrigin: true,
        rewrite: (path: string) => path.replace(new RegExp(`^${uiApiPrefix}`), ''),
      },
    },
  },
})
