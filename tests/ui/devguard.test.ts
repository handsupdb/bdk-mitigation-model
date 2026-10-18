/**
 * file:// guard test for the repository root index.html (the Vite dev
 * template).
 *
 * Opening the root index.html directly from disk renders a blank page: its
 * entry is a module script (/src/main.tsx), and browsers block module loads
 * from file:// origins (CORS). The inline <script data-dev-only> guard in
 * <head> must detect file: and replace the body with a guidance panel
 * pointing at dist-single/index.html (or the dev/build commands).
 *
 * The guard must stay inert over http(s) — the dev server serves the app
 * through this same file. Stripping it from the single-file build is
 * verified at build time (vite.singlefile.config.ts) and by the offline
 * e2e render test, which would fail if the guard wiped #root there.
 */
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { JSDOM } from 'jsdom'

const devTemplate = fileURLToPath(new URL('../../index.html', import.meta.url))

function load(url: string): JSDOM {
  return new JSDOM(readFileSync(devTemplate, 'utf8'), {
    url,
    runScripts: 'dangerously',
    pretendToBeVisual: true,
  })
}

describe('root index.html file:// guard', () => {
  it(
    'replaces the body with a guidance panel when opened from file://',
    async () => {
      const dom = load('file:///index.html')
      try {
        // The guard runs in <head>, before <body> is parsed, so it waits for
        // DOMContentLoaded; jsdom fires that on a later tick. Poll the body
        // until the panel lands (or the deadline passes and asserts fail).
        const deadline = Date.now() + 5_000
        let html = dom.window.document.body?.innerHTML ?? ''
        while (!html.includes('needs a web server') && Date.now() < deadline) {
          await new Promise((resolve) => setTimeout(resolve, 50))
          html = dom.window.document.body?.innerHTML ?? ''
        }

        expect(html).toContain('This page needs a web server')
        expect(html).toContain('href="dist-single/index.html"')
        expect(html).toContain('npm install &amp;&amp; npm run dev')
        expect(html).toContain('npm run build:single')
      } finally {
        dom.window.close()
      }
    },
    15_000,
  )

  it('is inert when served over http (dev server)', async () => {
    const dom = load('http://localhost:5173/index.html')
    try {
      // Give the (inert) guard its DOMContentLoaded tick, then confirm the
      // dev template body is untouched: #root still present, no panel.
      await new Promise((resolve) => setTimeout(resolve, 200))
      const html = dom.window.document.body?.innerHTML ?? ''
      expect(html).toContain('id="root"')
      expect(html).not.toContain('needs a web server')
    } finally {
      dom.window.close()
    }
  })
})
