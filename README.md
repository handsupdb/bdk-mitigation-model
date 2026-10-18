# BDK Mitigation Model

A community rebuild of **Kyrasis's** 12.1 Blood Death Knight mitigation
spreadsheet (`excel_mitigation_model.xlsx`) as a **serverless web app**.
Enter your character inputs and get the same mitigation/DPS-weight outputs
(including Pawn strings) the original spreadsheet produces — no Excel, no
server, no install.

> **Attribution — this project stands on Kyrasis's work.** The original
> model, math, and theorycrafting are entirely **Kyrasis's** — author of
> the 12.1 BDK mitigation spreadsheet (`excel_mitigation_model.xlsx`) and
> the Blood DK advanced guide (`bdk_advanced_guide.docx`) that this rebuild
> ports to the web. This is an unofficial community rebuild of those
> materials, not affiliated with or endorsed by Kyrasis. If the model
> helps you, go thank the original author.

## Quickstart

**Just want to use it?** Download the release zip
(`bdk-mitigation-model-<version>.zip` — attached to GitHub Releases, or
built locally with `tools/make_release.sh`), unzip it anywhere, and open
`index.html` in a browser. That's it — the app is fully self-contained
(all JS/CSS inlined, ~1.2 MB), so it works offline, from a local folder,
a USB stick, or an email attachment. No server, no install.

Cloned the repo instead? Open `dist-single/index.html` directly (build it
first with `npm run build:single` if it's not there yet).

**Contributing?**

```bash
npm install
npm run dev            # dev server at http://localhost:5173
npm test               # vitest, node environment
npm run build          # type-check (tsc -b) + production build -> dist/
npm run build:single   # self-contained single HTML file -> dist-single/index.html
```

### Content difficulty (Armor Constant)

The Armor Constant input (Conditional Variables → Armor Constant,
`Inputs!C156`) is a **per-difficulty user value**, not fixed game data.
For 12.1.5 set it to **4531.03** (Mythic+) or **5656.07** (Mythic Raid);
the saved profile's 3966.55 is stale.

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
- Known defects and oddities in the original workbook are carried into
  the rebuild **bug-for-bug** and catalogued in
  [`docs/FLAGGED_ISSUES.md`](docs/FLAGGED_ISSUES.md) — nothing is silently
  "fixed"; see that register before reporting anything as a bug.

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
data/wow-12.1/game.json   game-data constants + frozen cell literals
src/engine/               calculation engine core (evaluation, Excel
                          semantics, cell grid)
src/engine/generated/     one generated module per sheet (DO NOT EDIT —
                          produced by tools/emit_module.py)
src/ui/                   React UI (inputs editor, outputs view, talents)
tools/                    Python codegen + extraction tooling (.venv/)
tools/pipeline/           SimC/Wowhead proposed-diff pipeline (see its README)
tests/                    vitest suites + golden fixtures
dist-single/index.html    the distributable single-file app
```

## Patch updates

When a new patch changes the spreadsheet's math, update the tracked data
and regenerate — never edit `src/engine/generated/` by hand:

1. **Constants & literals** — edit `data/wow-12.1/game.json` (the `{{name}}`
   game-data constants and the frozen `cellLiterals` values).
2. **Formulas** — edit the per-sheet TSVs in `data/wow-12.1/formulas/`.
3. **Regenerate** the engine modules — for each changed sheet:
   ```bash
   .venv/bin/python tools/emit_module.py <sheet>
   ```
   (e.g. `Baseline`, `Comparison`, `Inputs`, `Outputs`, `_Haste`, …)
4. **Test** — `npm test`; the golden suite verifies every cell still
   matches the frozen workbook values.

To find out *what* changed upstream, use the proposed-diff pipeline
([`tools/pipeline/README.md`](tools/pipeline/README.md)): it fetches
SimulationCraft spell data and Wowhead talent trees, diffs them against
the workbook, and writes hand-review reports. It never edits anything
itself — every `CHANGED` line is a proposal that a human verifies and
applies via steps 1–2 above.

## Releases

`tools/make_release.sh` runs `npm run build:single` and packages
`dist-single/index.html` + this README (+ `LICENSE` when present) into
`release/bdk-mitigation-model-<version>.zip` (version from `package.json`).
The zip is gitignored — attach it to a GitHub Release, not a commit.

## Credits

- **Kyrasis** — the original 12.1 BDK mitigation spreadsheet
  (`excel_mitigation_model.xlsx`) and the Blood DK advanced guide this
  project rebuilds. All the theorycrafting is theirs.
- **SimulationCraft** — ability/spell coefficient data (consumed by the
  proposed-diff pipeline).
- **Wowhead** — talent tree data (consumed by the proposed-diff pipeline).

World of Warcraft and Blizzard Entertainment are trademarks or registered
trademarks of Blizzard Entertainment, Inc. This project is not affiliated
with Blizzard Entertainment, SimulationCraft, or Wowhead.

## Contributing

Issues and PRs are welcome. The golden suite (`npm test`, 653/653) must
stay green — outputs are bit-exact vs the original workbook, so anything
that would change a golden value should be discussed against
[`docs/FLAGGED_ISSUES.md`](docs/FLAGGED_ISSUES.md) first. For data changes,
follow the "Patch updates" workflow above.
