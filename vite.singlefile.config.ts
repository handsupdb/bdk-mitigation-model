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
// the file directly). The rewritten tag is also moved from <head> to the end
// of <body>: a classic inline script executes in place (defer needs a src
// attribute), and in <head> it runs before <body> is parsed — #root does not
// exist yet and createRoot(null) throws (React error #299, blank page).

// Rewrites inlined <script type="module" ...> tags to classic <script> tags
// and moves them to the end of <body>. Runs after vite-plugin-singlefile
// inlines the bundle (same enforce tier, later in the plugins array).
function classicScriptTags(): Plugin {
  return {
    name: 'classic-script-tags',
    enforce: 'post',
    generateBundle(_options, bundle) {
      for (const file of Object.values(bundle)) {
        if (file.type === 'asset' && /\.html?$/.test(file.fileName)) {
          let source = String(file.source).replace(
            /<script\b([^>]*\stype="module"[^>]*)>/g,
            (_match, attrs: string) =>
              '<script' + attrs.replace(/\s+(?:type="module"|crossorigin)/g, '') + '>',
          )
          // Move the now-classic inline script from <head> to the end of
          // <body>, after the #root container (mirroring index.html, whose
          // entry tag sits after the div). Function replacement so `$`-style
          // patterns in the minified bundle are inserted verbatim.
          const script = source.match(/<script\b[^>]*>[\s\S]*?<\/script>/)
          if (!script) {
            throw new Error(
              'classic-script-tags: no inlined <script> found in ' +
                file.fileName +
                ' — cannot relocate it to <body>; the artifact would not render',
            )
          }
          source = source
            .replace(script[0], '')
            .replace(/<\/body>/, () => script[0] + '\n  </body>')
          file.source = source
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
