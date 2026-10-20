/// <reference types="vitest" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/creator': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/workflow-runs': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/providers': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/ready': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/agents': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/lineage': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/research': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/publishing': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/learning': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/approvals': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          three: ['three', '@react-three/fiber'],
        },
      },
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/tests/setup.ts'],
    testTimeout: 15000,
  },
});
