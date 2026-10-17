import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { viteSingleFile } from 'vite-plugin-singlefile'

// Offline single-file build: produces dist-single/index.html with all JS/CSS
// inlined, so a community member can download one file and open it directly
// with no server. Run via: npm run build:single
export default defineConfig({
  plugins: [react(), viteSingleFile()],
  build: {
    outDir: 'dist-single',
  },
})
