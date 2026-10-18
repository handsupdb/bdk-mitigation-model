import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import { viteSingleFile } from 'vite-plugin-singlefile'

// Offline single-file build: produces dist-single/index.html with all JS/CSS
// inlined, so a community member can download one file and open it directly
// with no server. Run via: npm run build:single
//
// The bundle is emitted as a classic (non-module) IIFE and the inlined
// <script> tag is rewritten to drop type="module"/crossorigin, because some
// browsers block module scripts from file:// origins (blank page when opening
// the file directly).

// Rewrites inlined <script type="module" ...> tags to classic <script> tags.
// Runs after vite-plugin-singlefile inlines the bundle (same enforce tier,
// later in the plugins array).
function classicScriptTags(): Plugin {
  return {
    name: 'classic-script-tags',
    enforce: 'post',
    generateBundle(_options, bundle) {
      for (const file of Object.values(bundle)) {
        if (file.type === 'asset' && /\.html?$/.test(file.fileName)) {
          file.source = String(file.source).replace(
            /<script\b([^>]*\stype="module"[^>]*)>/g,
            (_match, attrs: string) =>
              '<script' + attrs.replace(/\s+(?:type="module"|crossorigin)/g, '') + '>',
          )
        }
      }
    },
  }
}

export default defineConfig({
  plugins: [react(), viteSingleFile(), classicScriptTags()],
  build: {
    outDir: 'dist-single',
    // Classic (non-module) IIFE output so the file opens from file:// in any
    // browser; some browsers block module scripts from file:// origins.
    rollupOptions: { output: { format: 'iife', inlineDynamicImports: true } },
    modulePreload: false,
    target: 'es2018',
  },
})
