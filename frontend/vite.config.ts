import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Dev : `npm run dev` proxie /api vers Django (8420). Prod : Django sert frontend/dist.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  server: { proxy: { '/api': 'http://127.0.0.1:8420' } },
  test: { environment: 'jsdom', include: ['src/**/*.test.{ts,tsx}'] },  // DOC534.228: pages are rendered and clicked, not read as text
})
