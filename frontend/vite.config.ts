import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const backendUrl = env.VITE_BACKEND_URL || 'http://localhost:8080'

  return {
    plugins: [react()],
    server: {
      host: '0.0.0.0',
      port: 3000,
      allowedHosts: ['water-unroll-platypus.ngrok-free.dev'],
      proxy: {
        '/api': {
          target: backendUrl,
          changeOrigin: true,
          ws: true
        },
        '/ws': {
          target: backendUrl.replace(/^http/, 'ws'),
          ws: true
        }
      }
    }
  }
})
