import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
export default defineConfig({
  plugins: [react(), tailwindcss(), { name: 'offline-no-hmr-client', transformIndexHtml: { order: 'post', handler: html => html.replace(/<script type="module" src="\/@vite\/client"><\/script>/g, '') } }],
  server: { host: '127.0.0.1', port: 5173, strictPort: true, hmr: false },
  preview: { host: '127.0.0.1', port: 5173, strictPort: true },
})
