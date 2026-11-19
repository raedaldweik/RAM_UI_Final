import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // `npm run dev` serves the UI on :5173 and forwards API calls to the backend on :8000
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
  build: {
    // The map (MapLibre GL) is a lazy chunk of its own, loaded only for an answer
    // that carries a map; it is large by nature, so don't warn about it on every build.
    chunkSizeWarningLimit: 900,
  },
});
