import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// `base` is relative so one build works from a GitHub Pages project subpath, a
// custom domain, or a local `dist/` open — without rebuilding for each.
export default defineConfig({
  base: './',
  plugins: [react(), tailwindcss()],
  resolve: {
    // `@/` → `src/` (shadcn convention); mirrors the tsconfig paths.
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  build: {
    outDir: 'dist',
    // The payload is ~380 KB of JSON imported at build time. That is the entire
    // dataset, and it is expected to be large.
    chunkSizeWarningLimit: 1200,
    rollupOptions: {
      output: {
        // Vite 8 / Rolldown wants a function here, not an id→names map. Split
        // the ECharts runtime into its own chunk so the app shell and the data
        // stay cacheable independently of the (large, stable) charting library.
        manualChunks: (id) =>
          id.includes('node_modules/echarts') ||
          id.includes('node_modules/zrender') ||
          id.includes('echarts-for-react')
            ? 'echarts'
            : undefined,
      },
    },
  },
})
