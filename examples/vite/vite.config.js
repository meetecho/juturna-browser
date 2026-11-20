import { defineConfig } from 'vite';

// SharedArrayBuffer needs a cross-origin isolated page
const headers = {
  'Cross-Origin-Opener-Policy': 'same-origin',
  'Cross-Origin-Embedder-Policy': 'require-corp'
};

export default defineConfig({
  server: { headers },
  preview: { headers },
  // the pre-bundled copy of the package breaks the Worker URL in `vite` (dev)
  optimizeDeps: { exclude: ['juturna-browser'] },
  // main.js uses top-level await
  build: { target: 'esnext' }
});
