/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  test: {
    // jsdom is a pretend browser, so tests can render pages without opening one.
    environment: 'jsdom',
    setupFiles: './src/test/setup.ts',
  },
})
