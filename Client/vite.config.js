import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/signup': {
        target: 'https://mediscope-2-server.onrender.com',
        changeOrigin: true,
      },
      '/login': {
        target: 'https://mediscope-2-server.onrender.com',
        changeOrigin: true,
      },
      '/process': {
        target: 'https://mediscope-2-server.onrender.com',
        changeOrigin: true,
      },
      '/api': {
        target: 'https://mediscope-2-server.onrender.com',
        changeOrigin: true,
      },
    },
  },
})
