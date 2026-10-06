import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The app talks to FastAPI through /api on the same origin, so the session
// cookie stays first-party (SameSite=Strict) in development too.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
