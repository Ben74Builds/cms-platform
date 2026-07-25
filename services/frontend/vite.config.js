import { defineConfig } from 'vite'
import { resolve } from 'path'

export default defineConfig({
  // Root is where index.html lives during dev
  root: resolve(__dirname, 'app'),

  // Base public path for production build
  base: '/static/',

  // Public directory (files copied as-is)
  publicDir: resolve(__dirname, 'app/static/data'),

  // Development server
  server: {
    port: 5173,
    strictPort: true,
    // Allow FastAPI to serve the app, Vite handles assets
    origin: 'http://localhost:5173',
  },

  // Build configuration
  build: {
    outDir: resolve(__dirname, 'app/static/dist'),
    emptyOutDir: true,
    manifest: 'manifest.json',

    rollupOptions: {
      input: {
        // Bundle all app JS into one file
        app: resolve(__dirname, 'src/main.js'),
      },
      output: {
        entryFileNames: 'js/[name]-[hash].js',
        chunkFileNames: 'js/[name]-[hash].js',
        assetFileNames: (assetInfo) => {
          const ext = assetInfo.name?.split('.').pop()
          if (ext === 'css') return 'css/[name]-[hash][extname]'
          if (/png|jpe?g|svg|gif|ico|webp/.test(ext)) return 'img/[name]-[hash][extname]'
          return 'assets/[name]-[hash][extname]'
        }
      }
    }
  },

  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
      '@static': resolve(__dirname, 'app/static'),
    }
  }
})
