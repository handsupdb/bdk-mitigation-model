# Proposed-diff pipeline (SimC + Wowhead vs our workbook)

Python side-tools that fetch upstream game data (SimC midnight spell data,
Wowhead live talent-calc data), compare it against our 12.1 workbook, and
write **hand-review reports**. They never edit `game.json`, the formula TSVs,
or any generated module — every `CHANGED` line is a *proposal* that a human
must verify and apply by hand.

Python: `.venv/bin/python` (repo venv). Node (only for `npm test` in step d):
`export PATH="/opt/homebrew/bin:$PATH"` first.

## Files

| file | role |
|---|---|
| `simc_data.py` | fetch + parse SimC `sc_spell_data.inc` (name → spell id → effect fields); CLI: `.venv/bin/python tools/pipeline/simc_data.py <spell> <effect#>` |
| `simc_diff.py` | compare our ability coefficients against SimC via `simc_mapping.json` → `extracted/simc_proposed_diffs.md` |
| `simc_mapping.json` | **curated** mapping: our ability → SimC spell/effect/field + our cell (see below) |
| `wowhead_diff.py` | compare our talent index against Wowhead talent trees → `extracted/wowhead_proposed_diffs.md` |
| `test_pipeline.py` | network-free unit tests (see [Tests](#tests)) |

## Workflow

### a) Fetch + diff (network; caches everything)

```bash
.venv/bin/python tools/pipeline/simc_diff.py      # SimC midnight spell data
.venv/bin/python tools/pipeline/wowhead_diff.py   # Wowhead talent trees
```

Each script downloads its source to `extracted/` on first run and reuses the
cache afterwards (`wowhead_diff.py --refresh` forces a re-download). Both
print a compact summary and write a full Markdown report:

- `extracted/simc_proposed_diffs.md` — per-ability verdicts: `match` /
  `CHANGED` (proposed diff) / `unmapped`, with our value + formula, the SimC
  value + spell/effect source, and the delta.
- `extracted/wowhead_proposed_diffs.md` — (a) Wowhead nodes not in our
  index, (b) our talents not in the Wowhead trees, (c) text-derived per-rank
  values for multi-rank talents (reference only).

Useful one-off lookups while reviewing:

```bash
.venv/bin/python tools/pipeline/simc_data.py "Heart Strike" 2   # effectN(2) fields
```

### b) Review the reports

Read both reports end to end. Treat `CHANGED` lines as *claims*, not facts:

- SimC values are per-spell-effect raw DBC data; our workbook may apply the
  coefficient differently (e.g. `H25 = 1.4256*1.15` bundles a multiplier).
  The report shows our formula next to the value for exactly this reason.
- Wowhead section (c) values are **text-derived** (tooltip/description
  strings), not numeric spell data — verify against SimC before trusting.
- `unmapped` entries mean "no comparison was possible" (no cell in the
  ability's row matched, spell absent from the source, …), not "OK".

### c) Apply accepted changes — BY HAND, never auto-applied

No tool in this directory writes to the workbook. For each proposal you
accept after verification, edit by hand:

- constants / literal cell values → `data/wow-12.1/game.json`
  (`{{name}}` game-data constants and `cellLiterals`);
- formulas → the per-sheet TSVs in `data/wow-12.1/formulas/`;
- talent/ability index rows → `data/wow-12.1/game.json` `index.talents` /
  `index.abilities` (regenerate with `tools/build_index.py` if the sheet
  rows changed).

If a `CHANGED` value is wrong or the mapping is off, fix
`simc_mapping.json` (see below) and re-run step a instead of the sheet.

### d) Regenerate modules + test

For every sheet whose TSV or literals changed (see the repo README's
"Patch updates" section):

```bash
.venv/bin/python tools/emit_module.py <sheet>   # e.g. Baseline, _Haste, …
export PATH="/opt/homebrew/bin:$PATH" && npm test
```

`npm test` (vitest, 653 tests) is the gate: the golden suite verifies every
cell still matches the frozen workbook values.

## The curated mapping (`simc_mapping.json`)

A JSON list, one entry per ability, comparing **one** SimC effect field
against **one** of our cells:

```json
{
  "ability":     "Blood Boil",              // our workbook ability name
  "simcSpell":   "Blood Boil",              // spell name for simc_data
  "effectIndex": 1,                         // 1-based, SimC effectN() convention
  "field":       "ap_coeff",                // parsed field to compare
  "ourCell":     "Baseline!H25",            // our cell; null = unmapped
  "spellId":     null,                      // optional: pin an ambiguous name
  "note":        null                       // optional curation note
}
```

- `effectIndex` is **1-based** (`effectN(1)` = the file's `_index` 0). The
  research doc `extracted/simc_research.md` labels effects 0-based ("eff1"
  there = `effectIndex: 2` here).
- `spellId` pins the exact spell when a name is ambiguous: names resolve to
  the **first** id in the file (e.g. "Consumption" → 205223, which has no
  `ap_coeff`; the damage spell SimC's class module uses is 1263825).
- `ourCell` is found by curation, not guessing: compare the SimC value
  against every numeric cell in the ability's `Baseline` row (literals +
  cached values + evaluated formulas) and take the one that matches.

**Extending the mapping** — to add an ability (or re-derive a cell):

```bash
.venv/bin/python tools/pipeline/simc_diff.py --discover "Death's Caress" \
    --effect 1 --field ap_coeff
# --simc-spell NAME   spell name when it differs from the ability label
```

`--discover` prints the SimC value, scans that ability's `Baseline` row for
a matching cell, and reports `MATCH <cell> = <value> (<source>)` or
"no matching cell → mark unmapped". Put the winner in `ourCell`, add a
`note` when something is subtle (see the existing entries for examples),
then re-run step a and check the new entry's verdict.

## Caches (regenerable, gitignored)

| cache | source | refresh |
|---|---|---|
| `extracted/simc_sc_spell_data.inc` (~29.6 MB) | `simulationcraft/simc` branch `midnight`, `engine/dbc/generated/sc_spell_data.inc` | delete the file (or any copy >20 MB is trusted) and re-run `simc_diff.py` |
| `extracted/wowhead_talents.js` (~1.7 MB) | `nether.wowhead.com/data/talents-dragonflight` | `wowhead_diff.py --refresh` |
| `extracted/simc_sc_death_knight.cpp` (~0.6 MB) | SimC midnight class module (reference for spell usage, e.g. `spell.consumption_damage`) | re-download from the same branch |

All three are download caches for the diff scripts — regenerable at any
time, never committed (`.gitignore`). The generated reports
(`extracted/simc_proposed_diffs.md`, `extracted/wowhead_proposed_diffs.md`)
are likewise regenerable outputs and gitignored. The hand-written research
notes (`extracted/simc_research.md`, `extracted/wowhead_research.md`) are
*not* regenerable — don't delete those.

## Tests

Network-free unit tests for the parsing logic, run on committed fixture
slices (no curl, no caches, no Node):

```bash
.venv/bin/python tools/pipeline/test_pipeline.py
```

- `tests/fixtures/pipeline/simc_spell_data_slice.inc` — ~48-line verbatim
  slice of the spell-data cache: the 3 mapped spells (Heart Strike, Blood
  Boil, Marrowrend) plus Consumption (both spell ids), unrelated spells,
  and nil placeholder rows.
- `tests/fixtures/pipeline/wowhead_talents_sample.js` — trimmed
  `WH.setPageData` payload: 7 trees / 14 nodes (warrior class tree for
  playerClass filtering, DK class tree, Frost + Blood spec trees for
  guide-URL discovery, Deathbringer / San'layn / Rider hero trees for
  `shownForSpecs` filtering).

30 tests cover: name → id → effect → coefficient lookups, 1-based
`effectN` indexing, alias handling, nil-row skipping, the `_class_flags[4]`
group not shifting field positions, tolerance classification, arithmetic
formula evaluation, `spellId` pinning, verdicts, Wowhead page-data parsing,
Blood DK tree discovery, node counts, name matching, and the full diff
model. Not covered (needs network): `fetch`/`fetch_tooltip`/
`per_rank_progression`.

The tests are **not** wired into `npm test` — the pipeline is a Python
side-tool and `npm test` stays Node-only. Run the command above directly
(e.g. after touching any parser in this directory).
