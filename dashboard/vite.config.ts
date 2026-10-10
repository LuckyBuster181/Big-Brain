import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Leitet alle /api/*-Anfragen an das FastAPI-Backend weiter. Für den
      // Browser laufen Frontend und Backend dadurch auf derselben Adresse -
      // es braucht kein CORS und keine fest verdrahtete Backend-URL.
      //
      // Ziel ist bewusst 127.0.0.1 statt localhost: Windows löst "localhost"
      // zuerst nach ::1 (IPv6) auf, uvicorn lauscht aber auf 127.0.0.1.
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        // Claude braucht mit viel Vault-Kontext auch mal eine Minute
        timeout: 120_000,
        proxyTimeout: 120_000,
      },
    },
  },
})
