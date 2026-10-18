/**
 * End-to-end render test for the offline single-file build
 * (dist-single/index.html, produced by `npm run build:single`).
 *
 * Prior verification of that artifact was build-level only (the file exists
 * and the bundle is inlined). This loads the exact HTML a user opens with
 * jsdom, lets the inline classic script execute, and polls #root until React
 * commits the app — the engine evaluates ~15k cells on mount, so the first
 * commit can take a few seconds.
 *
 * Skipped when the artifact is absent (a fresh clone before build:single).
 */
import { existsSync, readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import { JSDOM } from 'jsdom'

const artifact = fileURLToPath(new URL('../../dist-single/index.html', import.meta.url))

describe.skipIf(!existsSync(artifact))('offline single-file build (dist-single/index.html)', () => {
  it(
    'renders the app into #root',
    async () => {
      const dom = new JSDOM(readFileSync(artifact, 'utf8'), {
        runScripts: 'dangerously',
        pretendToBeVisual: true,
      })
      try {
        // Poll #root for non-empty content: the engine evaluates ~15k cells
        // on mount, so React's first commit lands a few seconds in.
        const deadline = Date.now() + 10_000
        let innerHTML = ''
        while (Date.now() < deadline) {
          innerHTML = dom.window.document.getElementById('root')?.innerHTML ?? ''
          if (innerHTML.length > 0) break
          await new Promise((resolve) => setTimeout(resolve, 100))
        }

        // Static app chrome (src/App.tsx h1/h2) plus a grid-backed section
        // title (src/ui/InputsEditor.tsx; Inputs!B145 in the workbook data).
        expect(innerHTML).toContain('BDK Mitigation Model')
        expect(innerHTML).toContain('Conditional Variables')
        expect(innerHTML).toContain('Comparison — Talents')
      } finally {
        dom.window.close()
      }
    },
    30_000,
  )
})
