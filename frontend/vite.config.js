import { defineConfig } from 'vite'

// The browser only talks to Vite; /api is forwarded to FastAPI so keys never reach the frontend.
export default defineConfig({
  server: {
    port: 5190,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8800',
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
