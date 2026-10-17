# BDK Mitigation Model

A from-scratch rebuild of the Kyrasis 12.1 Blood Death Knight mitigation
spreadsheet (`excel_mitigation_model.xlsx`) as a serverless web app, so a
community member can open a single HTML file — no Excel, no server — enter
their character inputs, and get the same mitigation/DPS-weight outputs
(including Pawn strings) the spreadsheet produces.

## Tech stack

- **Vite 8** + **TypeScript** + **React 19** — app shell and UI
- **Vitest** (node environment) — engine tests against golden fixtures
- **vite-plugin-singlefile** — offline single-file build (`dist-single/index.html`)
- **Python 3 + openpyxl** (`.venv/`) — extraction tooling only; not needed to
  run the app

## Run

```bash
npm install
npm run dev            # dev server at http://localhost:5173
npm test               # vitest, node environment
npm run build          # type-check (tsc -b) + production build -> dist/
npm run build:single   # self-contained single HTML file -> dist-single/index.html
```

The `build:single` output is the distributable artifact: download
`dist-single/index.html` and open it directly in a browser.

## Project layout

```
excel_mitigation_model.xlsx   source spreadsheet (reference, do not modify)
*.docx                        reference docs (model support, BDK guide, APL info)
extract_xlsx.py               workbook -> extracted/ TSVs + metadata (openpyxl)
extracted/                    extraction artifacts (raw TSVs/metadata untracked;
                              analysis notes + crossrefs tracked)
tools/make_golden_fixtures.py extracted/*__values.tsv -> tests/fixtures/golden/
tests/fixtures/golden/        per-sheet golden values: {cell_ref: value} + "uncached"
tests/                        vitest suites (golden.smoke.test.ts) + helpers
src/                          React app (App.tsx placeholder; engine pending)
src/engine/                   calculation engine port (placeholder module)
```

## Status

**Scaffolding complete, engine port pending.** The spreadsheet is fully
extracted (15 sheets; data flow Inputs → Baseline → {Comparison, 10 +Stat
sheets} → Outputs), golden fixtures are committed, and the app/test/build
pipeline is verified. Next: port the calculation logic into `src/engine/`,
verified cell-by-cell against the golden fixtures.
