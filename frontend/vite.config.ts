/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Pass /api requests on to the FastAPI backend, so the frontend can call
    // it without its own address. Start the backend first (see README.md).
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  test: {
    // jsdom is a pretend browser, so tests can render pages without opening one.
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
  },
})
