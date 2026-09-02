// `defineConfig` comes from vitest/config, not vite, so the `test` block below is typed.
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'

// The build lands inside the Python package so `t2e label --serve` serves the UI from the installed
// wheel with no separate dev server in the shipped path (PLAN.md D-007).
const outDir = fileURLToPath(new URL('../backend/src/t2e/web', import.meta.url))

export default defineConfig({
  plugins: [react()],
  build: {
    outDir,
    emptyOutDir: true,
    // The whole UI is a handful of screens; one chunk loads faster than several round trips.
    chunkSizeWarningLimit: 900,
  },
  server: {
    port: 5173,
    // Dev only: the SPA talks to the uvicorn process started by `make dev`.
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8765',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
})
