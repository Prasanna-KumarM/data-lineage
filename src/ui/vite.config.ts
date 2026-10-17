import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const apiTarget = process.env.LINEAGE_API_URL ?? 'http://127.0.0.1:8000'
const apiPrefixes = ['/projects', '/targets', '/lineage', '/steps', '/relations']

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: Object.fromEntries(apiPrefixes.map((p) => [p, { target: apiTarget, changeOrigin: true }])),
  },
})
