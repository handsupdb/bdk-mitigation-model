# BDK Mitigation Model

A community rebuild of Kyrasis's 12.1 Blood Death Knight mitigation
spreadsheet (`excel_mitigation_model.xlsx`) as a **serverless web app**.
Enter your character inputs and get the same mitigation/DPS-weight outputs
(including Pawn strings) the original spreadsheet produces — no Excel, no
server, no install.

## Quickstart

**Just want to use it?** Download this repo and open
`dist-single/index.html` directly in a browser. That's it — the file is
fully self-contained (all JS/CSS inlined, ~1.2 MB), so it works offline,
from a local folder, a USB stick, or an email attachment.

**Contributing?**

```bash
npm install
npm run dev            # dev server at http://localhost:5173
npm test               # vitest, node environment
npm run build          # type-check (tsc -b) + production build -> dist/
npm run build:single   # self-contained single HTML file -> dist-single/index.html
```

## How it works

- The calculation engine is **TypeScript modules generated from tracked
  formula data** in `data/wow-12.1/formulas/` (one TSV per sheet: cell
  reference + formula/literal content). The generator is
  `tools/emit_module.py`; its output lives in `src/engine/generated/`.
- The engine evaluates every cell of every sheet in dependency order,
  reproducing Excel semantics (including cyclic/iterative cells, string
  math, and exact float formatting).
- The **golden test suite** (`tests/engine/golden.test.ts`) reproduces the
  original spreadsheet's outputs **bit-exactly**: every evaluated cell of
  all 14 sheets is compared against per-sheet golden fixtures extracted
  from the workbook — **15,464 cell comparisons**, all passing.

## Running tests

```bash
npm test
```

11 test files / 653 tests, including the golden suite above plus unit
tests for the engine's Excel-semantics helpers (number formatting, string
math, comparison operators, lazy/cyclic evaluation).

## Project layout

```
data/wow-12.1/formulas/   tracked formula TSVs (one per sheet) — the source
                          of truth for the engine
src/engine/               calculation engine core (evaluation, Excel
                          semantics, cell grid)
src/engine/generated/     one generated module per sheet (DO NOT EDIT —
                          produced by tools/emit_module.py)
src/ui/                   React UI (inputs editor, outputs view, talents)
tools/                    Python codegen + extraction tooling (.venv/)
tests/                    vitest suites + golden fixtures
dist-single/index.html    the distributable single-file app
```

## Patch updates

When a new patch changes the spreadsheet's formulas:

1. Edit the formula TSVs in `data/wow-12.1/formulas/` (one per sheet).
2. Regenerate the engine modules — for each changed sheet:
   ```bash
   .venv/bin/python tools/emit_module.py <sheet>
   ```
   (e.g. `Baseline`, `Comparison`, `Inputs`, `Outputs`, `_Haste`, …)
3. Run `npm test` — the golden suite verifies every cell still matches.

Planned next: the structured game-data refactor, the SimC/Wowhead
proposed-diff pipeline, and `docs/FLAGGED_ISSUES.md`.
