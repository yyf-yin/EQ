import { defineConfig } from 'vitest/config'
import { loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import tailwind from '@tailwindcss/vite'
export default defineConfig(({mode}) => ({plugins:[react(),tailwind()],server:{proxy:{'/api':loadEnv(mode, '.', 'CDR_').CDR_API_TARGET || 'http://127.0.0.1:8000'}},test:{environment:'jsdom',setupFiles:['./tests/setup.ts'],exclude:['e2e/**','node_modules/**']}}))
